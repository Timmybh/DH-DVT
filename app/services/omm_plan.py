"""Kế hoạch theo tổ × mã hàng × ngày, dựng từ eGMF `OMM_KeHoachThang` (kế hoạch tháng).

Mỗi dòng OMM_KeHoachThang là một lát kế hoạch: SoLuong sản phẩm may từ NgayMayKeHoachBatDau đến NgayMayKeHoachKetThuc trên một chuyền.
Kế hoạch của ngày D = SoLuong × (phần thời gian may của lát đó nằm trong ngày D). Chuyền: Lib_CumChuyen (TenCum = số chuyền, PXId → Lib_PhanXuong → Lib_XiNghiep);
mã hàng: OMM_KeHoachThang.CTPOId → OMM_PO_ChiTiet → OMM_PO → OMM_DonHang.MaHang.
Ngày SX của một (chuyền, mã hàng) = từ ngày bắt đầu vào chuyền (NgayVaoChuyenKeHoachBatDau nhỏ nhất) đến ngày kết thúc may (NgayMayKeHoachKetThuc lớn nhất).
Sản lượng thực hiện lấy từ HiPro (line_output_daily); bảng này chỉ chứa KẾ HOẠCH.
"""

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.resources import LinePlanDaily

PLAN_SQL = """
SELECT xn.TenXiNghiep AS xn, e.TenCum AS line, dh.MaHang AS style, k.SoLuong AS qty,
       k.NgayVaoChuyenKeHoachBatDau AS vao, k.NgayMayKeHoachBatDau AS mbd, k.NgayMayKeHoachKetThuc AS mkt
FROM dbo.OMM_KeHoachThang k
JOIN dbo.OMM_PO_ChiTiet ct ON ct.POCTId = k.CTPOId
JOIN dbo.OMM_PO po ON po.POId = ct.POId
JOIN dbo.OMM_DonHang dh ON dh.DHId = po.DHId
JOIN dbo.Lib_CumChuyen e ON e.CumId = k.ChuyenId
LEFT JOIN dbo.Lib_PhanXuong px ON px.PXId = e.PXId
LEFT JOIN dbo.Lib_XiNghiep xn ON xn.XNId = px.XNId
WHERE k.ChuyenId IS NOT NULL AND k.SoLuong > 0 AND k.NgayMayKeHoachBatDau IS NOT NULL AND k.NgayMayKeHoachKetThuc IS NOT NULL
  AND k.NgayMayKeHoachBatDau < :hi AND k.NgayMayKeHoachKetThuc >= :lo"""


def _xn_code(name) -> str | None:
    m = re.search(r"(\d+)", str(name or ""))
    return f"XN{int(m.group(1))}" if m else None


def build_rows(raw: list, since: date, until: date) -> list[dict]:
    """raw: các dòng (xn, line, style, qty, vao, mbd, mkt). Trả các dòng (day, factory_code, line, style, plan_qty, in_line_from, sew_end) cho since ≤ ngày ≤ until."""
    plan: dict[tuple, float] = defaultdict(float)
    span: dict[tuple, list] = {}
    for r in raw:
        code = _xn_code(r.xn)
        if code is None or not r.style:
            continue
        line, style = str(r.line).strip(), str(r.style).strip().upper()
        k2 = (code, line, style)
        vao, mkt = (r.vao or r.mbd), r.mkt
        s = span.setdefault(k2, [vao, mkt])
        s[0], s[1] = min(s[0], vao), max(s[1], mkt)
        total = (r.mkt - r.mbd).total_seconds()
        d = max(since, r.mbd.date())
        while d <= min(until, r.mkt.date()):
            lo, hi = datetime.combine(d, datetime.min.time()), datetime.combine(d + timedelta(days=1), datetime.min.time())
            ov = (min(r.mkt, hi) - max(r.mbd, lo)).total_seconds()
            frac = 1.0 if total <= 0 else max(0.0, min(1.0, ov / total))
            if frac > 0:
                plan[(d, *k2)] += r.qty * frac
            d += timedelta(days=1)
    return [dict(day=k[0], factory_code=k[1], line=k[2], style=k[3], plan_qty=round(q, 2), in_line_from=span[k[1:]][0].date(), sew_end=span[k[1:]][1].date()) for k, q in plan.items() if q > 0.005]


def fetch_rows(conn, since: date, until: date) -> list[dict]:
    lo, hi = datetime.combine(since, datetime.min.time()), datetime.combine(until + timedelta(days=1), datetime.min.time())
    return build_rows(conn.execute(text(PLAN_SQL), {"lo": lo, "hi": hi}).all(), since, until)


def apply_line_plan(db: Session, rows: list[dict], since: date, sync_run_id: int | None = None) -> dict:
    """Đối chiếu cửa sổ [since, …]: thêm dòng mới, cập nhật dòng đổi, xoá dòng không còn trong kế hoạch, bỏ qua dòng không đổi."""
    key = lambda r: (r["day"], r["factory_code"], r["line"], r["style"])  # noqa: E731
    have = {(r.day, r.factory_code, r.line, r.style): r for r in db.query(LinePlanDaily).filter(LinePlanDaily.day >= since)}
    fresh = {key(r): r for r in rows}
    st = {"read": len(rows), "inserted": 0, "updated": 0, "deleted": 0, "unchanged": 0}
    for k, r in fresh.items():
        cur = have.get(k)
        if cur is None:
            db.add(LinePlanDaily(**r, sync_run_id=sync_run_id))
            st["inserted"] += 1
        elif (round(cur.plan_qty, 2), cur.in_line_from, cur.sew_end) != (r["plan_qty"], r["in_line_from"], r["sew_end"]):
            cur.plan_qty, cur.in_line_from, cur.sew_end, cur.sync_run_id = r["plan_qty"], r["in_line_from"], r["sew_end"], sync_run_id
            st["updated"] += 1
        else:
            st["unchanged"] += 1
    for k, cur in have.items():
        if k not in fresh:
            db.delete(cur)
            st["deleted"] += 1
    db.flush()
    return st
