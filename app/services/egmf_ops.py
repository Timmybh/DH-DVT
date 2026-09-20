"""Đồng bộ dữ liệu vận hành từ eGMF: tiến độ PO (may xong / nhập kho TP) và QA (tổng số lỗi).

Nguồn (xem docs/eGMF_Survey_OrderProgress_QA_2026-09-20.md):
  dbo.Report_BaoCaoMayRa                      nhật ký snapshot ~10 phút/lần -> lấy giá trị lũy kế lớn nhất + ngày đầu tiên đạt đủ SL
  dbo.Lib_XacNhanTemDongGoi                   Xác nhận đóng gói theo thùng (PO, Quantity, NgayXacNhan) -> nhập kho/đóng gói hoàn tất
  dbo.DFC_InLine_..._KiemTra_SanPham_CTLoi    Inline  (SLLoi > 0; XN qua ..._KiemTra_SanPham)
  dbo.DFCEndlineChitietloi                    Endline (mỗi dòng = một lần xuất hiện lỗi; XN qua DFC_EndLine_Detail -> DFC_Master)
  dbo.DFCDauChuyenChitietloi                  Đầu chuyền (như Endline, qua DFC_DauChuyen_Detail -> DFC_Master)
  dbo.DFCFinalChitietloiBoSung                Prefinal/Final (XN = DFC_Pre_Final_Master.FtyXN)
Khung thời gian QA: đầu tháng hiện tại → hôm nay (xem qa_window_start). Tiến độ PO không giới hạn theo tháng vì ngày hoàn thành cần toàn bộ lịch sử snapshot.
Nhóm QC nằm ở DB hipro — chưa kết nối. CUTTING_BTP_KiemTraChatLuong* bị loại khỏi phạm vi QA hiện tại.
"""

import logging
import re
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.models.data import PoPackDaily, PoProgress, QaDefectDaily, SyncRun
from app.models.resources import LaborDaily, MachineRequirement, MachineType
from app.services.sync_core import add_items

log = logging.getLogger(__name__)

QA_CATEGORIES = ("DAU_CHUYEN", "INLINE", "ENDLINE", "PREFINAL")
LATE_CLOSE_DAYS = 3  # những ngày đầu tháng còn đồng bộ thêm tháng trước để bắt các phiếu kiểm nhập muộn
_XN = re.compile(r"(?i)(?:XN|X[ÍI] ?NGHI[ỆE]P(?: MAY)?)\s*0?(\d)")


def qa_window_start(today: date) -> date:
    """Khung thời gian đồng bộ QA: từ đầu tháng hiện tại đến hôm nay (tháng cũ giữ nguyên số đã lưu).
    Trong LATE_CLOSE_DAYS ngày đầu tháng lấy thêm từ đầu tháng trước.
    """
    first = today.replace(day=1)
    if today.day <= LATE_CLOSE_DAYS:
        return (first - timedelta(days=1)).replace(day=1)
    return first


def normalize_xn(raw) -> int | None:
    """'XN1' / 'XÍ NGHIỆP MAY 2' -> 1 / 2; các phòng ban hoặc giá trị lạ -> None."""
    if raw is None:
        return None
    m = _XN.search(str(raw).strip())
    return int(m.group(1)) if m else None


def _chunks(seq, size=500):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _qa_queries(since: date) -> dict[str, str]:
    p = {"since": since}
    del p
    return {
        "INLINE": """
            SELECT CAST(l.NgayKiem AS date) AS d, s.XiNghiep AS xn, SUM(l.SLLoi) AS c
            FROM dbo.DFC_InLine_SoDoChuyen_Tram_KiemTra_SanPham_CTLoi l
            JOIN dbo.DFC_InLine_SoDoChuyen_Tram_KiemTra_SanPham s ON s.Id = l.IdSanPham
            WHERE l.SLLoi > 0 AND l.NgayKiem >= :since GROUP BY CAST(l.NgayKiem AS date), s.XiNghiep""",
        "ENDLINE": """
            SELECT CAST(l.thoiGianKiem AS date) AS d, m.XiNghiep AS xn, COUNT(*) AS c
            FROM dbo.DFCEndlineChitietloi l
            JOIN dbo.DFC_EndLine_Detail dt ON dt.Id = l.dfcEndlineDetailId
            JOIN dbo.DFC_Master m ON m.IdMaster = dt.MasterId
            WHERE l.thoiGianKiem >= :since GROUP BY CAST(l.thoiGianKiem AS date), m.XiNghiep""",
        "DAU_CHUYEN": """
            SELECT CAST(dt.ThoiGianTao AS date) AS d, m.XiNghiep AS xn, COUNT(*) AS c
            FROM dbo.DFCDauChuyenChitietloi l
            JOIN dbo.DFC_DauChuyen_Detail dt ON dt.Id = l.dfcDauChuyenDetailId
            JOIN dbo.DFC_Master m ON m.IdMaster = dt.MasterId
            WHERE dt.ThoiGianTao >= :since GROUP BY CAST(dt.ThoiGianTao AS date), m.XiNghiep""",
        "PREFINAL": """
            SELECT CAST(l.thoiGianKiem AS date) AS d, p.FtyXN AS xn, COUNT(*) AS c
            FROM dbo.DFCFinalChitietloiBoSung l
            JOIN dbo.DFC_Pre_Final_Master p ON p.Id = l.dfcPreFinalMasterId
            WHERE l.thoiGianKiem >= :since GROUP BY CAST(l.thoiGianKiem AS date), p.FtyXN""",
    }


LABOR_SQL = """
SELECT XiNghiep AS xn, TenChuyen AS line, CAST(Ngay AS date) AS d, MAX(TongSoLaoDong) AS total, MAX(SoLaoDongHienDien) AS present
FROM dbo.LCD_Truc_Quan_ChuyenMay_LaoDong WHERE Ngay >= :since AND TenChuyen IS NOT NULL GROUP BY XiNghiep, TenChuyen, CAST(Ngay AS date)"""

MACHINE_TYPE_SQL = "SELECT MaLoaiMay AS code, TenLoai AS name FROM dbo.Lib_ChungLoaiMay"

QTCN_SQL = """
SELECT m.MaHang AS style, d.TenThietBi AS machine, SUM(d.SoLuong) AS qty
FROM dbo.ChuyenMay_QTCN_QuyTrinhCongNghe_Master m
JOIN dbo.ChuyenMay_QTCN_QuyTrinhCongNghe_Detail d ON d.IdQTCN = m.Id
WHERE m.MaHang IS NOT NULL AND d.TenThietBi IS NOT NULL AND d.SoLuong > 0
GROUP BY m.MaHang, d.TenThietBi"""

PACK_SQL = """
SELECT PO AS po, CAST(NgayXacNhan AS date) AS d, SUM(Quantity) AS q
FROM dbo.Lib_XacNhanTemDongGoi WHERE PO IS NOT NULL GROUP BY PO, CAST(NgayXacNhan AS date)"""

PROGRESS_SQL = """
SELECT PO AS po, TenChuyen AS line, XiNghiep AS xn, MAX(KhachHang) AS customer, MAX(MaHang) AS style,
       MAX(SoLuong) AS qty, MAX(MayRaLuyKe) AS sewn_qty, MAX(NhapKhoLuyKe) AS fg_qty, MAX(NgayXuatHang) AS due_date,
       MIN(CASE WHEN SoLuong > 0 AND MayRaLuyKe >= SoLuong THEN NgaySanXuat END) AS sewn_done,
       MIN(CASE WHEN SoLuong > 0 AND NhapKhoLuyKe >= SoLuong THEN NgaySanXuat END) AS fg_done,
       MAX(NgaySanXuat) AS last_seen
FROM dbo.Report_BaoCaoMayRa
WHERE PO IS NOT NULL AND ThoiGianTao >= :since
GROUP BY PO, TenChuyen, XiNghiep"""


def sync_ops(db: Session, run: SyncRun, conn: Connection, fmap: dict[int, int]) -> dict:
    """Đồng bộ QA + tiến độ PO vào Postgres. Trả tóm tắt các đối tượng; lỗi từng phần được ghi thành ERROR nhưng không làm hỏng doanh thu."""
    since = qa_window_start(date.today())
    objects, unmatched_names, errors = [], defaultdict(int), []

    # ---- QA
    total_rows = 0
    for cat, sql in _qa_queries(since).items():
        try:
            agg: dict[tuple[int, date], int] = defaultdict(int)
            for r in conn.execute(text(sql), {"since": since}):
                if r.d is None or not r.c:
                    continue
                ma = normalize_xn(r.xn)
                fid = fmap.get(ma) if ma is not None else None
                if fid is None:
                    unmatched_names[f"{cat}: {r.xn or '(trống)'}"] += int(r.c)
                    continue
                agg[(fid, r.d)] += int(r.c)
            rows = [dict(factory_id=k[0], category=cat, day=k[1], defect_count=v, sync_run_id=run.id) for k, v in agg.items()]
            with db.begin_nested():  # savepoint: lỗi một nhóm không làm hỏng phần còn lại của phiên
                for part in _chunks(rows):
                    stmt = pg_insert(QaDefectDaily).values(part)
                    db.execute(stmt.on_conflict_do_update(constraint="uq_qa_defect_daily", set_={"defect_count": stmt.excluded.defect_count, "sync_run_id": stmt.excluded.sync_run_id}))
            objects.append({"name": f"QA {cat}", "read": len(rows), "matched": len(rows), "unmatched": 0})
            total_rows += len(rows)
        except Exception as exc:  # noqa: BLE001
            log.exception("Đồng bộ QA %s lỗi", cat)
            errors.append((f"QA {cat}", f"Không đồng bộ được: {str(exc)[:180]}", {}))
            objects.append({"name": f"QA {cat}", "read": 0, "matched": 0, "unmatched": 1})

    # ---- Tiến độ PO
    try:
        rows, bad = [], 0
        for r in conn.execute(text(PROGRESS_SQL), {"since": date(2026, 1, 1)}):
            ma = normalize_xn(f"XN{r.xn}") if r.xn is not None else None
            fid = fmap.get(ma) if ma is not None else None
            if fid is None:
                bad += 1
                continue
            rows.append(dict(
                po=str(r.po)[:80], line=str(r.line if r.line is not None else "")[:20], factory_id=fid, customer=(r.customer or "")[:100], style=(r.style or "")[:60],
                qty=int(r.qty or 0), sewn_qty=int(r.sewn_qty or 0), fg_qty=int(r.fg_qty or 0), due_date=r.due_date, sewn_done_date=r.sewn_done,
                fg_done_date=r.fg_done, last_seen=r.last_seen, sync_run_id=run.id,
            ))
        cols = ["customer", "style", "qty", "sewn_qty", "fg_qty", "due_date", "sewn_done_date", "fg_done_date", "last_seen", "sync_run_id"]
        with db.begin_nested():
            for part in _chunks(rows, 300):
                stmt = pg_insert(PoProgress).values(part)
                db.execute(stmt.on_conflict_do_update(constraint="uq_po_progress", set_={c: stmt.excluded[c] for c in cols}))
        objects.append({"name": "Tiến độ PO (Report_BaoCaoMayRa)", "read": len(rows) + bad, "matched": len(rows), "unmatched": bad})
        total_rows += len(rows)
        if bad:
            unmatched_names["Tiến độ PO: dòng không có xí nghiệp"] += bad
    except Exception as exc:  # noqa: BLE001
        log.exception("Đồng bộ tiến độ PO lỗi")
        errors.append(("Tiến độ PO", f"Không đồng bộ được: {str(exc)[:180]}", {}))
        objects.append({"name": "Tiến độ PO (Report_BaoCaoMayRa)", "read": 0, "matched": 0, "unmatched": 1})

    # ---- Xác nhận đóng gói theo PO/ngày (toàn bộ lịch sử: ngày hoàn thành cần số lũy kế)
    try:
        packs = [
            dict(po=str(r.po)[:80], day=r.d, qty=int(r.q or 0), sync_run_id=run.id)
            for r in conn.execute(text(PACK_SQL))
            if r.po and r.d and r.q
        ]
        with db.begin_nested():
            for part in _chunks(packs, 1000):
                stmt = pg_insert(PoPackDaily).values(part)
                db.execute(stmt.on_conflict_do_update(constraint="uq_po_pack_daily", set_={"qty": stmt.excluded.qty, "sync_run_id": stmt.excluded.sync_run_id}))
        objects.append({"name": "Xác nhận đóng gói (Lib_XacNhanTemDongGoi)", "read": len(packs), "matched": len(packs), "unmatched": 0})
        total_rows += len(packs)
    except Exception as exc:  # noqa: BLE001
        log.exception("Đồng bộ xác nhận đóng gói lỗi")
        errors.append(("Xác nhận đóng gói", f"Không đồng bộ được: {str(exc)[:180]}", {}))
        objects.append({"name": "Xác nhận đóng gói (Lib_XacNhanTemDongGoi)", "read": 0, "matched": 0, "unmatched": 1})

    # ---- Nguồn lực: lao động theo chuyền/ngày, danh mục loại máy, yêu cầu máy theo mã hàng (QTCN)
    try:
        labor = []
        for r in conn.execute(text(LABOR_SQL), {"since": since}):
            ma = normalize_xn(r.xn)
            if ma is None or r.d is None:
                continue
            labor.append(dict(factory_code=f"XN{ma}", line=str(r.line).strip()[:20], day=r.d, total=int(r.total or 0), present=int(r.present or 0), sync_run_id=run.id))
        types = [dict(code=str(r.code).strip()[:20], name=(r.name or "")[:100], source="EGMF") for r in conn.execute(text(MACHINE_TYPE_SQL)) if r.code]
        reqs = [dict(style_cc=str(r.style).strip()[:60], machine_type=str(r.machine).strip().upper()[:20], machine_name=str(r.machine)[:100], quantity=int(r.qty), source="QTCN")
                for r in conn.execute(text(QTCN_SQL))]
        with db.begin_nested():
            for part in _chunks(labor, 1000):
                stmt = pg_insert(LaborDaily).values(part)
                db.execute(stmt.on_conflict_do_update(constraint="uq_labor_daily", set_={"total": stmt.excluded.total, "present": stmt.excluded.present, "sync_run_id": stmt.excluded.sync_run_id}))
            for part in _chunks(types, 200):
                stmt = pg_insert(MachineType).values(part)
                db.execute(stmt.on_conflict_do_update(index_elements=["code"], set_={"name": stmt.excluded.name}))
            for part in _chunks(reqs, 200):  # không ghi đè yêu cầu do người dùng nhập tay
                stmt = pg_insert(MachineRequirement).values(part)
                db.execute(stmt.on_conflict_do_update(constraint="uq_machine_req", set_={"quantity": stmt.excluded.quantity, "machine_name": stmt.excluded.machine_name}, where=(MachineRequirement.source == "QTCN")))
        objects.append({"name": "Lao động theo chuyền (LCD_Truc_Quan_ChuyenMay_LaoDong)", "read": len(labor), "matched": len(labor), "unmatched": 0})
        objects.append({"name": "Loại máy + yêu cầu máy theo mã hàng (QTCN)", "read": len(types) + len(reqs), "matched": len(types) + len(reqs), "unmatched": 0})
        total_rows += len(labor) + len(types) + len(reqs)
    except Exception as exc:  # noqa: BLE001
        log.exception("Đồng bộ nguồn lực lỗi")
        errors.append(("Nguồn lực", f"Không đồng bộ được: {str(exc)[:180]}", {}))
        objects.append({"name": "Nguồn lực (lao động / máy)", "read": 0, "matched": 0, "unmatched": 1})

    if unmatched_names:
        add_items(db, run.id, "UNMATCHED", "QA / Tiến độ eGMF", [(k, f"Không gán được xí nghiệp — {v:,} bản ghi/lỗi bị bỏ qua (phòng ban hoặc tên lạ)", {"count": v}) for k, v in unmatched_names.items()])
    if errors:
        add_items(db, run.id, "ERROR", "QA / Tiến độ eGMF", errors)
    return {"objects": objects, "rows": total_rows, "unmatched": len(unmatched_names), "errors": len(errors)}
