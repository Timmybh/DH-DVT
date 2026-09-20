"""Mục Snapshot: danh mục MỌI bảng ảnh chụp / lịch sử theo lần đồng bộ (chỉ đọc) để xem ở một chỗ.

Mỗi bộ dữ liệu khai báo: bảng nguồn, cột ngày "as of", cột xí nghiệp, cột tìm kiếm, cột hiển thị, ai dùng (Dashboard / Recheck / Đối soát) và cách giữ (bất biến, chỉ ghi khi đổi...).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.actual import ActualObservation
from app.models.core import Factory
from app.models.data import PlanImportBatch, PoPackDaily, PoProgress, QaDefectDaily, RevenueDaily, RevenueMonthly, RevenueYearly
from app.models.labor_snapshot import LaborSnapshot, LaborSnapshotLine
from app.models.planning import PlanningVersion
from app.models.resources import LaborDaily

Col = tuple[str, str]  # (thuộc tính, nhãn)


@dataclass
class Dataset:
    key: str
    title: str
    group: str
    description: str
    used_by: str
    retention: str
    model: Any
    columns: list[Col]
    order: list[Any] = field(default_factory=list)
    asof: str | None = None  # cột ngày/giờ "as of" để lọc và hiện "mới nhất"
    factory_code: str | None = None  # cột chứa mã XN (XN1..)
    factory_id: str | None = None  # cột chứa id XN
    search: list[str] = field(default_factory=list)
    parent: str | None = None  # cột khóa cha (VD snapshot_id)


DATASETS: list[Dataset] = [
    Dataset("labor_snapshots", "Lao động — ảnh chụp cho Dashboard", "Dashboard", "Ảnh chụp lao động eGMF mỗi lần đồng bộ (chỉ ghi khi số liệu đổi): có mặt / biên chế theo xí nghiệp.",
            "Dashboard → Tình hình nhân sự", "Bất biến, giữ lâu dài", LaborSnapshot,
            [("id", "ID"), ("as_of_date", "Ngày dữ liệu"), ("taken_at", "Chụp lúc"), ("sync_run_id", "Lần đồng bộ"), ("lines", "Số chuyền"), ("stale_lines", "Chuyền cũ bỏ qua"), ("present", "Có mặt"), ("total", "Biên chế"), ("by_factory", "Theo XN")],
            [LaborSnapshot.as_of_date.desc(), LaborSnapshot.id.desc()], asof="as_of_date"),
    Dataset("labor_snapshot_lines", "Lao động — chi tiết theo chuyền của ảnh chụp", "Dashboard", "Từng chuyền trong mỗi ảnh chụp lao động (lọc theo ID ảnh chụp).",
            "Dashboard → Xem theo tổ/chuyền", "Cùng vòng đời với ảnh chụp", LaborSnapshotLine,
            [("snapshot_id", "Ảnh chụp"), ("factory_code", "XN"), ("line", "Chuyền"), ("day", "Ngày"), ("present", "Có mặt"), ("total", "Biên chế")],
            [LaborSnapshotLine.snapshot_id.desc(), LaborSnapshotLine.factory_code, LaborSnapshotLine.id], asof="day", factory_code="factory_code", parent="snapshot_id"),
    Dataset("actual_observations", "Thực tế eGMF — lịch sử theo lần đồng bộ", "Đối soát", "Trạng thái MỚI hoặc THAY ĐỔI của từng (PO, XN, chuyền) ở mỗi lần đồng bộ, kèm chênh lệch so với lần trước.",
            "Thực tế & Đối soát, Kết chuyển", "Chỉ ghi khi đổi; lưu trữ theo năm (giữ trạng thái hiện tại)", ActualObservation,
            [("sync_run_id", "Lần đồng bộ"), ("observed_at", "Quan sát lúc"), ("po", "PO"), ("style", "Mã hàng"), ("customer", "Khách"), ("factory_code", "XN"), ("line", "Chuyền"), ("qty", "SL"),
             ("sewn_qty", "May xong"), ("fg_qty", "Nhập kho"), ("is_new", "Mới"), ("changes", "Thay đổi")],
            [ActualObservation.observed_at.desc(), ActualObservation.id.desc()], asof="observed_at", factory_code="factory_code", search=["po", "style", "customer"]),
    Dataset("po_progress", "Tiến độ PO — ảnh chụp mới nhất", "Dashboard", "Trạng thái mới nhất của từng PO/chuyền từ Report_BaoCaoMayRa (may xong, nhập kho, hạn giao).",
            "Dashboard → Order Progress", "Ghi đè bằng trạng thái mới nhất (lịch sử nằm ở Thực tế eGMF)", PoProgress,
            [("po", "PO"), ("line", "Chuyền"), ("factory_id", "XN"), ("customer", "Khách"), ("style", "Mã hàng"), ("qty", "SL"), ("sewn_qty", "May xong"), ("fg_qty", "Nhập kho"), ("due_date", "Hạn giao"),
             ("sewn_done_date", "Ngày may xong"), ("fg_done_date", "Ngày nhập kho đủ"), ("last_seen", "Thấy lần cuối"), ("sync_run_id", "Lần đồng bộ")],
            [PoProgress.last_seen.desc(), PoProgress.id.desc()], asof="last_seen", factory_id="factory_id", search=["po", "style", "customer"]),
    Dataset("po_pack_daily", "Xác nhận đóng gói theo PO / ngày", "Dashboard", "Số lượng đóng gói đã xác nhận (Lib_XacNhanTemDongGoi) — cơ sở tính ngày nhập kho hoàn tất.",
            "Dashboard → Order Progress (nhập kho TP)", "Ghi đè theo (PO, ngày)", PoPackDaily,
            [("po", "PO"), ("day", "Ngày"), ("qty", "SL"), ("sync_run_id", "Lần đồng bộ")], [PoPackDaily.day.desc(), PoPackDaily.id.desc()], asof="day", search=["po"]),
    Dataset("qa_defect_daily", "QA — tổng số lỗi theo ngày", "Dashboard", "Tổng số lỗi theo xí nghiệp / nhóm kiểm tra / ngày (cửa sổ từ đầu tháng hiện tại).",
            "Dashboard → Chất lượng QA", "Ghi đè theo (XN, nhóm, ngày); lưu trữ theo năm", QaDefectDaily,
            [("factory_id", "XN"), ("category", "Nhóm"), ("day", "Ngày"), ("defect_count", "Số lỗi"), ("sync_run_id", "Lần đồng bộ")], [QaDefectDaily.day.desc(), QaDefectDaily.id.desc()], asof="day", factory_id="factory_id"),
    Dataset("labor_daily", "Lao động theo chuyền / ngày (nguồn Recheck)", "Kế hoạch", "Lao động có mặt theo chuyền từng ngày (LCD_Truc_Quan_ChuyenMay_LaoDong) — dùng kiểm tra nhân lực khi Recheck.",
            "Recheck (LABOR_SHORTAGE), lịch nguồn lực rảnh", "Ghi đè theo (chuyền, ngày); lưu trữ theo năm. KHÔNG dùng cho Dashboard (đã có ảnh chụp riêng)", LaborDaily,
            [("factory_code", "XN"), ("line", "Chuyền"), ("day", "Ngày"), ("present", "Có mặt"), ("total", "Biên chế"), ("sync_run_id", "Lần đồng bộ")], [LaborDaily.day.desc(), LaborDaily.id.desc()], asof="day", factory_code="factory_code"),
    Dataset("revenue_daily", "Doanh thu theo ngày", "Dashboard", "Kế hoạch / thực tế / còn lại theo xí nghiệp từng ngày (eGMF).", "Dashboard → Doanh thu", "Ghi đè theo (XN, ngày)", RevenueDaily,
            [("factory_id", "XN"), ("report_date", "Ngày"), ("plan", "Kế hoạch"), ("actual", "Thực tế"), ("remaining", "Còn lại"), ("source", "Nguồn"), ("sync_run_id", "Lần đồng bộ")], [RevenueDaily.report_date.desc(), RevenueDaily.id.desc()], asof="report_date", factory_id="factory_id"),
    Dataset("revenue_monthly", "Doanh thu theo tháng", "Dashboard", "Kế hoạch / thực tế theo tháng (eGMF, bảng khai báo).", "Dashboard → Doanh thu (tháng, lũy kế)", "Ghi đè theo (XN, tháng)", RevenueMonthly,
            [("factory_id", "XN"), ("year", "Năm"), ("month", "Tháng"), ("plan", "Kế hoạch"), ("actual", "Thực tế"), ("remaining", "Còn lại"), ("declared_by", "Người khai báo"), ("source", "Nguồn")], [RevenueMonthly.year.desc(), RevenueMonthly.month.desc(), RevenueMonthly.id], factory_id="factory_id"),
    Dataset("revenue_yearly", "Doanh thu theo năm", "Dashboard", "Kế hoạch / thực tế theo năm (eGMF).", "Dashboard → Doanh thu (năm)", "Ghi đè theo (XN, năm)", RevenueYearly,
            [("factory_id", "XN"), ("year", "Năm"), ("plan", "Kế hoạch"), ("actual", "Thực tế"), ("remaining", "Còn lại"), ("declared_by", "Người khai báo"), ("source", "Nguồn")], [RevenueYearly.year.desc(), RevenueYearly.id], factory_id="factory_id"),
    Dataset("planning_versions", "Phiên bản kế hoạch (ảnh chụp bất biến)", "Kế hoạch", "Mỗi lần Commit tạo một phiên bản bất biến; Issue đánh dấu bản đang dùng.", "Kế hoạch, Đối soát, Kết chuyển",
            "Bất biến; lưu trữ theo năm (giữ bản đang Issue)", PlanningVersion,
            [("id", "ID"), ("code", "Mã"), ("status", "Trạng thái"), ("row_count", "Số dòng"), ("recheck_result", "Recheck"), ("created_by", "Người tạo"), ("created_at", "Tạo lúc"), ("issued_at", "Issue lúc")],
            [PlanningVersion.created_at.desc(), PlanningVersion.id.desc()], asof="created_at", search=["code"]),
    Dataset("plan_import_batches", "Lần nhập file kế hoạch Excel", "Kế hoạch", "Mỗi lần nhập file kế hoạch SX tạo một batch; chỉ batch hiện hành được dùng.", "Kế hoạch (phiên bản nền), Dashboard tiến độ PO",
            "Giữ lịch sử các batch", PlanImportBatch,
            [("id", "ID"), ("filename", "Tệp"), ("imported_at", "Nhập lúc"), ("imported_by", "Người nhập"), ("is_current", "Hiện hành"), ("sync_run_id", "Lần đồng bộ")], [PlanImportBatch.imported_at.desc(), PlanImportBatch.id.desc()], asof="imported_at", search=["filename"]),
]
BY_KEY = {d.key: d for d in DATASETS}


def _ser(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _attr(d: Dataset, name: str):
    return getattr(d.model, name)


def catalog(db: Session) -> list[dict]:
    out = []
    for d in DATASETS:
        count = db.query(func.count()).select_from(d.model).scalar() or 0
        latest = db.query(func.max(_attr(d, d.asof))).scalar() if d.asof else None
        out.append({"key": d.key, "title": d.title, "group": d.group, "description": d.description, "used_by": d.used_by, "retention": d.retention, "rows": count, "latest": _ser(latest),
                    "table": d.model.__tablename__, "columns": [{"key": k, "label": l} for k, l in d.columns], "filters": {"asof": bool(d.asof), "factory": bool(d.factory_code or d.factory_id), "search": bool(d.search), "parent": d.parent}})
    return out


def rows(db: Session, key: str, limit: int = 100, offset: int = 0, q: str = "", factory: str = "", date_from: date | None = None, date_to: date | None = None, parent_id: int | None = None) -> dict:
    d = BY_KEY.get(key)
    if d is None:
        raise HTTPException(404, "Không có bộ snapshot này")
    query = db.query(d.model)
    if q and d.search:
        like = f"%{q.strip()}%"
        query = query.filter(or_(*[_attr(d, c).ilike(like) for c in d.search]))
    if factory:
        if d.factory_code:
            query = query.filter(_attr(d, d.factory_code) == factory)
        elif d.factory_id:
            fid = db.query(Factory.id).filter(Factory.code == factory).scalar()
            query = query.filter(_attr(d, d.factory_id) == (fid if fid is not None else -1))
    if d.asof and (date_from or date_to):
        col = _attr(d, d.asof)
        is_dt = "DATETIME" in str(col.type).upper() or "TIMESTAMP" in str(col.type).upper()
        if date_from:
            query = query.filter(col >= (datetime.combine(date_from, datetime.min.time()) if is_dt else date_from))
        if date_to:
            query = query.filter(col < (datetime.combine(date_to + timedelta(days=1), datetime.min.time()) if is_dt else date_to + timedelta(days=1)))
    if parent_id is not None and d.parent:
        query = query.filter(_attr(d, d.parent) == parent_id)
    total = query.count()
    recs = query.order_by(*d.order).offset(offset).limit(limit).all()
    fmap = {f.id: f.code for f in db.query(Factory).all()}
    out = []
    for r in recs:
        row = {}
        for k, _l in d.columns:
            v = getattr(r, k)
            row[k] = fmap.get(v, v) if k == d.factory_id else _ser(v)
        out.append(row)
    return {"key": d.key, "total": total, "rows": out}
