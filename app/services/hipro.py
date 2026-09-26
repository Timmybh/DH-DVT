"""Nguồn HiPro (SQL Server, cùng máy chủ eGMF, database riêng): sản lượng từng chuyền × mã hàng × ngày.

Chuỗi nối (khảo sát 2026-09-26):
    pro_nscl.pro_ke_hoach_san_xuat_id -> pro_ke_hoach_san_xuat (ngày, chuyền, sản phẩm)
    -> pro_chuyen (số chuyền) -> pro_nha_may (xí nghiệp), pro_san_pham (mã hàng, PO)
    pro_nscl.pro_check_point_id -> pro_check_point (điểm quét của chuyền; mỗi dòng kế hoạch chỉ đi qua đúng điểm quét của chuyền đó)
`thuc_hien_ngay` / `ngay_san_xuat` của pro_nscl rỗng ở toàn bộ dữ liệu — sản lượng ngày = tổng qty_1_h … qty_14_h.
Chỉ đọc HiPro; ghi vào bảng line_output_daily của DVT.
"""

import logging
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.resources import LineOutputDaily

log = logging.getLogger("dvt.hipro")

_engine: Engine | None = None
_QTY = " + ".join(f"ISNULL(n.qty_{i}_h, 0)" for i in range(1, 15))

LINE_OUTPUT_SQL = f"""
SELECT CAST(k.ngay_san_xuat AS date) AS d, nm.ten AS xn, c.ten AS line, sp.ma_san_pham AS style, sp.po AS po, SUM({_QTY}) AS qty
FROM dbo.pro_nscl n
JOIN dbo.pro_ke_hoach_san_xuat k ON k.id = n.pro_ke_hoach_san_xuat_id
JOIN dbo.pro_chuyen c ON c.id = k.pro_chuyen_id
JOIN dbo.pro_nha_may nm ON nm.id = c.pro_nha_may_id
JOIN dbo.pro_san_pham sp ON sp.id = k.pro_san_pham_id
JOIN dbo.pro_check_point cp ON cp.id = n.pro_check_point_id AND cp.pro_chuyen_id = k.pro_chuyen_id
WHERE k.ngay_san_xuat >= :since
GROUP BY CAST(k.ngay_san_xuat AS date), nm.ten, c.ten, sp.ma_san_pham, sp.po
HAVING SUM({_QTY}) > 0"""


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = URL.create("mssql+pyodbc", username=settings.sqlserver_user, password=settings.sqlserver_password, host=settings.sqlserver_host,
                         port=settings.sqlserver_port, database=settings.hipro_db, query={"driver": settings.sqlserver_driver, "TrustServerCertificate": "yes"})
        _engine = create_engine(url, pool_pre_ping=True, connect_args={"timeout": settings.sqlserver_timeout})
    return _engine


def rows_from_hipro(conn, since: date, sync_run_id: int | None = None) -> list[dict]:
    from app.services.egmf_ops import normalize_xn

    out = []
    for r in conn.execute(text(LINE_OUTPUT_SQL), {"since": since}):
        ma = normalize_xn(r.xn)
        if ma is None or r.d is None or not r.style:
            continue
        out.append(dict(day=r.d, factory_code=f"XN{ma}", line=str(r.line).strip()[:20], style=str(r.style).strip()[:60], po=(str(r.po).strip() if r.po else "")[:80], qty=int(r.qty or 0), sync_run_id=sync_run_id))
    return out


def apply_line_output(db: Session, rows: list[dict], since: date) -> dict:
    """Đối chiếu (mirror) cửa sổ [since, nay]: chỉ ghi dòng MỚI hoặc ĐỔI số lượng, xoá dòng HiPro không còn, bỏ qua dòng không đổi.

    HiPro không có cột "sửa lần cuối" (pro_nscl chỉ có ngay_tao; số lượng theo giờ được cập nhật tại chỗ), nên không thể lọc theo id/ngày tạo —
    đơn vị thay đổi là ngày sản xuất: quét lại cửa sổ ngày rồi so với bản đã lưu.
    """
    key = lambda d: (d["day"], d["factory_code"], d["line"], d["style"], d["po"])  # noqa: E731
    have = {(r.day, r.factory_code, r.line, r.style, r.po): r for r in db.query(LineOutputDaily).filter(LineOutputDaily.day >= since)}
    fresh = {key(r): r for r in rows}
    stats = {"read": len(rows), "inserted": 0, "updated": 0, "deleted": 0, "unchanged": 0}
    for k, r in fresh.items():
        cur = have.get(k)
        if cur is None:
            db.add(LineOutputDaily(**r))
            stats["inserted"] += 1
        elif cur.qty != r["qty"]:
            cur.qty, cur.sync_run_id = r["qty"], r["sync_run_id"]
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1
    for k, cur in have.items():
        if k not in fresh:
            db.delete(cur)
            stats["deleted"] += 1
    db.flush()
    return stats


def sync_line_output(db: Session, since: date, sync_run_id: int | None = None) -> dict:
    with get_engine().connect() as conn:
        rows = rows_from_hipro(conn, since, sync_run_id)
    return apply_line_output(db, rows, since)
