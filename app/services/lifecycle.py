"""Phase 7 — vòng đời năm (handoff §27): kết chuyển cuối năm -> kiểm tra -> áp dụng sang năm sau -> lưu trữ dữ liệu giao dịch theo năm (có phục hồi).

- Master/reference data (nhà máy, cột, công thức, Capacity Definition, lịch, người dùng, Audit...) KHÔNG bao giờ bị lưu trữ chỉ vì cũ.
- Chỉ lưu trữ khi kết chuyển của năm đó đã VALIDATED/APPLIED; mỗi bảng được xuất ra tệp .jsonl.gz kèm SHA-256, đọc lại đối chiếu số dòng rồi mới xóa.
- "Phân vùng theo năm" ở đây là phân vùng logic: dữ liệu năm cũ ra tệp lưu trữ, bảng nóng chỉ giữ năm hiện hành + các năm còn trong chính sách giữ online.
"""

import gzip
import hashlib
import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import Date, DateTime, func
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, settings
from app.db.session import utcnow
from app.models.actual import ActualMapping, ActualObservation
from app.models.data import QaDefectDaily, SyncRun, SyncRunItem
from app.models.lifecycle import CarryForwardItem, YearArchive, YearCarryForward
from app.models.planning import PlanningVersion, PlanningVersionRow
from app.models.resources import LaborDaily
from app.services import actual_service
from app.services.audit import write_audit

log = logging.getLogger(__name__)


def _today() -> date:
    return date.today()


def archive_root() -> Path:
    return Path(settings.archive_dir) if settings.archive_dir else ROOT_DIR / "archive"


def _year_range(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year + 1, 1, 1)


def _dt_range(year: int) -> tuple[datetime, datetime]:
    from datetime import timezone

    return datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year + 1, 1, 1, tzinfo=timezone.utc)


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


# --------------------------------------------------------------------------- kết chuyển cuối năm
def _snapshot(row) -> dict:
    d = {}
    for c in PlanningVersionRow.__table__.columns:
        if c.key in ("id", "version_id"):
            continue
        d[c.key] = _jsonable(getattr(row, c.key))
    return d


def build_carry_forward(db: Session, year: int, user, version_id: int | None = None, include_no_actual: bool = True, today: date | None = None) -> YearCarryForward:
    """Tạo bản kết chuyển từ phiên bản tham chiếu: mọi dòng CHƯA nhập kho đủ thành phẩm còn lại bao nhiêu thì chuyển sang năm sau bấy nhiêu."""
    ver = db.get(PlanningVersion, version_id) if version_id else actual_service.reference_version(db)
    if ver is None:
        raise HTTPException(409, "Chưa có phiên bản kế hoạch để kết chuyển")
    if ver.status == "SUPERSEDED":
        raise HTTPException(409, "Phiên bản đã bị thay thế — chọn phiên bản đang dùng")
    pva = {r["row_uid"]: r for r in actual_service.plan_vs_actual(db, today or _today(), version_id=ver.id)["rows"]}
    rows = {r.row_uid: r for r in db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == ver.id)}
    cf = YearCarryForward(year=year, status="DRAFT", source_version_id=ver.id, created_by=getattr(user, "username", ""))
    db.add(cf)
    db.flush()
    closed = carried = 0
    remaining_total = planned_total = 0.0
    by_reason: dict[str, int] = defaultdict(int)
    for uid, row in rows.items():
        p = pva.get(uid)
        if p is None:
            continue
        planned = float(row.quantity or 0)
        planned_total += planned
        if p["status"] == "FG_COMPLETE":
            closed += 1
            continue
        reason = "NO_ACTUAL" if p["status"] == "NO_ACTUAL" else "OPEN"
        if reason == "NO_ACTUAL" and not include_no_actual:
            closed += 1
            continue
        remaining = max(planned - float(p["fg_qty"] or 0), 0.0)
        if remaining <= 0:
            closed += 1
            continue
        carried += 1
        remaining_total += remaining
        by_reason[reason] += 1
        db.add(CarryForwardItem(
            cf_id=cf.id, row_uid=uid, source_key=row.source_key, factory_code=row.factory_code, line_raw=row.line_raw, po_number=row.po_number, style_cc=row.style_cc,
            customer=row.customer, planned_qty=planned, sewn_qty=float(p["sewn_qty"] or 0), fg_qty=float(p["fg_qty"] or 0), remaining_qty=remaining, planned_end=row.end_prod_date,
            has_transfer=bool(row.transfer), mapping_count=int(p["mappings"] or 0), reason=reason, row_snapshot=_snapshot(row),
        ))
    cf.summary = {
        "source_version": ver.code, "source_rows": len(rows), "carried": carried, "closed": closed, "planned_qty": round(planned_total, 1), "remaining_qty": round(remaining_total, 1),
        "by_reason": dict(by_reason), "include_no_actual": include_no_actual, "as_of": (today or _today()).isoformat(),
    }
    db.flush()
    validate_carry_forward(db, cf)
    db.commit()
    write_audit("CARRY_FORWARD_BUILD", user=user, object_type="YearCarryForward", object_id=str(cf.id), detail=f"{year}: {carried} mục, còn lại {remaining_total:,.0f} — {cf.status}")
    return cf


def validate_carry_forward(db: Session, cf: YearCarryForward) -> list[dict]:
    """Các kiểm tra bắt buộc trước khi cho áp dụng/lưu trữ. Có kiểm tra `blocking` không đạt -> FAILED."""
    items = db.query(CarryForwardItem).filter(CarryForwardItem.cf_id == cf.id).all()
    s = cf.summary or {}
    src_rows = db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == cf.source_version_id)
    src_count = src_rows.count()
    checks: list[dict] = []

    def add(code: str, ok: bool, message: str, blocking: bool = True):
        checks.append({"code": code, "ok": ok, "blocking": blocking, "message": message})

    add("ROW_RECONCILE", s.get("carried", 0) + s.get("closed", 0) == src_count == s.get("source_rows"), f"Đã kết chuyển {s.get('carried', 0)} + đã đóng {s.get('closed', 0)} = {src_count} dòng của phiên bản nguồn")
    add("ITEM_COUNT", len(items) == s.get("carried", 0), f"Số mục lưu ({len(items)}) khớp số mục kết chuyển ({s.get('carried', 0)})")
    bad = [i.row_uid for i in items if i.remaining_qty <= 0 or i.remaining_qty > i.planned_qty + 1e-6]
    add("REMAINING_RANGE", not bad, "Số lượng còn lại của mọi mục nằm trong (0, số lượng kế hoạch]" if not bad else f"{len(bad)} mục có số lượng còn lại không hợp lệ")
    total = round(sum(i.remaining_qty for i in items), 1)
    add("REMAINING_TOTAL", abs(total - float(s.get("remaining_qty", 0))) < 0.5, f"Tổng còn lại {total:,.0f} khớp tổng đã tính {float(s.get('remaining_qty', 0)):,.0f}")
    uids = [i.row_uid for i in items]
    add("UNIQUE_ROWS", len(uids) == len(set(uids)), "Không mục nào bị kết chuyển hai lần")
    snap_transfers = sum(1 for i in items if i.has_transfer)
    src_transfers = sum(1 for r in src_rows.filter(PlanningVersionRow.row_uid.in_(uids or [""])) if r.transfer)
    add("TRANSFER_STATE", snap_transfers == src_transfers, f"Giữ nguyên trạng thái chuyển chuyền đang hoạt động ({snap_transfers} mục)")
    review = db.query(func.count(ActualMapping.id)).filter(ActualMapping.status == "REVIEW", ActualMapping.mapped_row_uid.in_(uids or [""])).scalar() or 0
    add("MAPPING_REVIEW", review == 0, f"{review} mapping thực tế của các mục kết chuyển còn cần xác nhận" if review else "Mapping thực tế của các mục kết chuyển đã rõ ràng", blocking=False)
    stale = sum(1 for i in items if i.reason == "NO_ACTUAL")
    add("NO_ACTUAL_ITEMS", stale == 0, f"{stale} mục chưa có thực tế (kế hoạch/dự báo) — cần lập lại ngày sau khi sang năm" if stale else "Mọi mục đều có thực tế", blocking=False)
    add("SOURCE_VERSION", db.get(PlanningVersion, cf.source_version_id) is not None, "Phiên bản nguồn còn tồn tại")
    cf.report = checks
    cf.status = "VALIDATED" if all(c["ok"] or not c["blocking"] for c in checks) else "FAILED"
    cf.validated_at = utcnow()
    return checks


def apply_carry_forward(db: Session, cf_id: int, user) -> PlanningVersion:
    """Tạo phiên bản đầu năm sau chứa các mục kết chuyển (row_uid giữ nguyên để theo dõi liên tục; số lượng = còn lại)."""
    from app.services import formula_runtime as fx
    from app.services import planning_service as ps
    from app.services.planning_engine import calc_total_day, recheck, sort_rows

    cf = db.get(YearCarryForward, cf_id)
    if cf is None:
        raise HTTPException(404, "Không tìm thấy bản kết chuyển")
    if cf.status == "APPLIED":
        raise HTTPException(409, "Bản kết chuyển này đã được áp dụng")
    if cf.status != "VALIDATED":
        raise HTTPException(409, "Chỉ áp dụng bản kết chuyển đã VALIDATED (đạt mọi kiểm tra bắt buộc)")
    items = db.query(CarryForwardItem).filter(CarryForwardItem.cf_id == cf.id).all()
    rows: list[dict] = []
    for it in items:
        d = dict(it.row_snapshot)
        for f in ("begin_prod_date", "end_prod_date", "warehouse_date", "chd"):
            d[f] = date.fromisoformat(d[f]) if d.get(f) else None
        planned = float(d.get("quantity") or 0)
        d["quantity"] = it.remaining_qty
        if d.get("capacity"):
            td = calc_total_day(it.remaining_qty, d["capacity"])
            d["total_day"] = td if td is not None else d.get("total_day")
        extra = dict(d.get("extra") or {})
        extra["carry_forward"] = {"from_year": cf.year, "from_version_id": cf.source_version_id, "planned_qty": planned, "fg_qty": it.fg_qty, "sewn_qty": it.sewn_qty, "reason": it.reason}
        d["extra"] = extra
        rows.append(d)
    rows = sort_rows(rows)
    code = ps.next_code(db, cf.year + 1, 1, "Master", None, "V")
    version = PlanningVersion(**code, status="COMMITTED", note=f"Kết chuyển từ năm {cf.year} ({len(rows)} mục còn dở)", created_by=user.username, row_count=len(rows), formula_set=fx.active().version_set())
    db.add(version)
    db.flush()
    ps._insert_rows(db, version.id, rows)
    result = recheck(rows, ps.load_resolver(db), ps.factory_codes(db), ps.load_resources(db).check)
    ps._store_recheck(version, result)
    cf.status, cf.target_version_id, cf.applied_at = "APPLIED", version.id, utcnow()
    db.commit()
    write_audit("CARRY_FORWARD_APPLY", user=user, object_type="YearCarryForward", object_id=str(cf.id), detail=f"{cf.year} -> {version.code}: {len(rows)} dòng, recheck={result['result']}")
    return version


def carry_forward_view(cf: YearCarryForward) -> dict:
    return {
        "id": cf.id, "year": cf.year, "status": cf.status, "source_version_id": cf.source_version_id, "target_version_id": cf.target_version_id, "created_by": cf.created_by,
        "created_at": cf.created_at.isoformat() if cf.created_at else None, "validated_at": cf.validated_at.isoformat() if cf.validated_at else None,
        "applied_at": cf.applied_at.isoformat() if cf.applied_at else None, "summary": cf.summary or {}, "report": cf.report or [],
    }


# --------------------------------------------------------------------------- lưu trữ theo năm
def _protected_version_ids(db: Session) -> set[int]:
    ids: set[int] = set()
    ref = actual_service.reference_version(db)
    if ref:
        ids.add(ref.id)
    ids.update(v for (v,) in db.query(ActualMapping.mapped_version_id).filter(ActualMapping.mapped_version_id.isnot(None)).distinct())
    ids.update(v for (v,) in db.query(YearCarryForward.target_version_id).filter(YearCarryForward.target_version_id.isnot(None)))
    return ids


def _latest_obs_ids(db: Session) -> set[int]:
    return {o.id for o in actual_service.latest_observations(db)}


def archive_plan(db: Session, year: int) -> list[tuple[str, type, list]]:
    """[(tên bảng, model, danh sách bản ghi)] theo thứ tự XÓA an toàn (bảng con trước)."""
    d0, d1 = _year_range(year)
    t0, t1 = _dt_range(year)
    versions = [v for v in db.query(PlanningVersion).filter(PlanningVersion.year == year) if v.id not in _protected_version_ids(db)]
    vids = [v.id for v in versions]
    vrows = db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id.in_(vids or [-1])).all()
    runs = db.query(SyncRun).filter(SyncRun.started_at >= t0, SyncRun.started_at < t1).all()
    run_ids = [r.id for r in runs]
    items = db.query(SyncRunItem).filter(SyncRunItem.run_id.in_(run_ids or [-1])).all()
    keep = _latest_obs_ids(db)  # trạng thái thực tế hiện tại của từng khóa luôn được giữ online
    obs = [o for o in db.query(ActualObservation).filter(ActualObservation.observed_at >= t0, ActualObservation.observed_at < t1) if o.id not in keep]
    return [
        ("planning_version_rows", PlanningVersionRow, vrows),
        ("planning_versions", PlanningVersion, versions),
        ("actual_observations", ActualObservation, obs),
        ("sync_run_items", SyncRunItem, items),
        ("sync_runs", SyncRun, runs),
        ("qa_defect_daily", QaDefectDaily, db.query(QaDefectDaily).filter(QaDefectDaily.day >= d0, QaDefectDaily.day < d1).all()),
        ("labor_daily", LaborDaily, db.query(LaborDaily).filter(LaborDaily.day >= d0, LaborDaily.day < d1).all()),
    ]


def _guard_archive(db: Session, year: int) -> YearCarryForward:
    if year >= _today().year:
        raise HTTPException(409, "Chỉ lưu trữ các năm đã kết thúc")
    cf = db.query(YearCarryForward).filter(YearCarryForward.year == year, YearCarryForward.status.in_(("VALIDATED", "APPLIED"))).order_by(YearCarryForward.id.desc()).first()
    if cf is None:
        raise HTTPException(409, f"Chưa có kết chuyển cuối năm {year} được VALIDATED — phải kết chuyển trước khi lưu trữ")
    if db.query(YearArchive).filter(YearArchive.year == year, YearArchive.status == "ARCHIVED").first():
        raise HTTPException(409, f"Năm {year} đã được lưu trữ")
    return cf


def archive_dry_run(db: Session, year: int) -> dict:
    cf = _guard_archive(db, year)
    return {"year": year, "carry_forward_id": cf.id, "tables": {name: len(recs) for name, _m, recs in archive_plan(db, year)}, "path": str(archive_root() / str(year))}


def _row_dict(obj) -> dict:
    return {c.key: _jsonable(getattr(obj, c.key)) for c in obj.__table__.columns}


def _write_gz(path: Path, rows: list[dict]) -> str:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def archive_year(db: Session, year: int, user) -> YearArchive:
    cf = _guard_archive(db, year)
    plan = archive_plan(db, year)
    out_dir = archive_root() / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    # 1) Xuất + đọc lại đối chiếu số dòng và SHA-256 TRƯỚC khi xóa bất cứ thứ gì
    for name, _model, recs in plan:
        rows = [_row_dict(r) for r in recs]
        path = out_dir / f"{name}.jsonl.gz"
        sha = _write_gz(path, rows)
        back = _read_gz(path)
        if len(back) != len(rows) or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise HTTPException(500, f"Đối chiếu tệp lưu trữ {name} thất bại — chưa xóa dữ liệu nào")
        manifest[name] = {"rows": len(rows), "sha256": sha, "file": path.name}
    (out_dir / "manifest.json").write_text(json.dumps({"year": year, "created_at": utcnow().isoformat(), "tables": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    # 2) Xóa trong một giao dịch (bảng con trước); lỗi -> rollback, dữ liệu nguyên vẹn
    try:
        for name, model, recs in plan:
            ids = [r.id for r in recs]
            for i in range(0, len(ids), 2000):
                db.query(model).filter(model.id.in_(ids[i:i + 2000])).delete(synchronize_session=False)
        arch = YearArchive(year=year, status="ARCHIVED", path=str(out_dir), manifest=manifest, carry_forward_id=cf.id, created_by=user.username, note=f"{sum(m['rows'] for m in manifest.values())} bản ghi")
        db.add(arch)
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_audit("YEAR_ARCHIVE", user=user, object_type="YearArchive", object_id=str(year), detail=json.dumps({k: v["rows"] for k, v in manifest.items()}))
    return arch


def _coerce(model, row: dict) -> dict:
    out = {}
    for c in model.__table__.columns:
        v = row.get(c.key)
        if v is not None and isinstance(c.type, DateTime):
            v = datetime.fromisoformat(v)
        elif v is not None and isinstance(c.type, Date):
            v = date.fromisoformat(v)
        out[c.key] = v
    return out


RESTORE_ORDER = [("planning_versions", PlanningVersion), ("planning_version_rows", PlanningVersionRow), ("sync_runs", SyncRun), ("sync_run_items", SyncRunItem),
                 ("actual_observations", ActualObservation), ("qa_defect_daily", QaDefectDaily), ("labor_daily", LaborDaily)]


def restore_year(db: Session, year: int, user) -> dict:
    arch = db.query(YearArchive).filter(YearArchive.year == year, YearArchive.status == "ARCHIVED").order_by(YearArchive.id.desc()).first()
    if arch is None:
        raise HTTPException(404, f"Không có bản lưu trữ ACTIVE của năm {year}")
    base = Path(arch.path)
    counts: dict[str, int] = {}
    try:
        for name, model in RESTORE_ORDER:
            meta = arch.manifest.get(name)
            if not meta:
                continue
            path = base / meta["file"]
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
                raise HTTPException(409, f"Tệp lưu trữ {name} thiếu hoặc bị thay đổi (SHA-256 không khớp) — không phục hồi")
            rows = [_coerce(model, r) for r in _read_gz(path)]
            for i in range(0, len(rows), 2000):
                db.bulk_insert_mappings(model, rows[i:i + 2000])
            counts[name] = len(rows)
        arch.status, arch.restored_at = "RESTORED", utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_audit("YEAR_RESTORE", user=user, object_type="YearArchive", object_id=str(year), detail=json.dumps(counts))
    return counts


# --------------------------------------------------------------------------- tổng quan / chính sách giữ dữ liệu
def year_overview(db: Session, today: date | None = None) -> dict:
    today = today or _today()
    sources = [
        ("planning_versions", PlanningVersion.year, None),
        ("actual_observations", ActualObservation.observed_at, "dt"),
        ("sync_runs", SyncRun.started_at, "dt"),
        ("qa_defect_daily", QaDefectDaily.day, "d"),
        ("labor_daily", LaborDaily.day, "d"),
    ]
    years: set[int] = {today.year}
    for _n, col, kind in sources:
        mn = db.query(func.min(col)).scalar()
        if mn is not None:
            years.add(mn if kind is None else mn.year)
    counts: dict[int, dict[str, int]] = {y: {} for y in sorted(years)}
    for y in counts:
        d0, d1 = _year_range(y)
        t0, t1 = _dt_range(y)
        counts[y]["planning_versions"] = db.query(func.count(PlanningVersion.id)).filter(PlanningVersion.year == y).scalar() or 0
        counts[y]["actual_observations"] = db.query(func.count(ActualObservation.id)).filter(ActualObservation.observed_at >= t0, ActualObservation.observed_at < t1).scalar() or 0
        counts[y]["sync_runs"] = db.query(func.count(SyncRun.id)).filter(SyncRun.started_at >= t0, SyncRun.started_at < t1).scalar() or 0
        counts[y]["qa_defect_daily"] = db.query(func.count(QaDefectDaily.id)).filter(QaDefectDaily.day >= d0, QaDefectDaily.day < d1).scalar() or 0
        counts[y]["labor_daily"] = db.query(func.count(LaborDaily.id)).filter(LaborDaily.day >= d0, LaborDaily.day < d1).scalar() or 0
    cfs = {}
    for cf in db.query(YearCarryForward).order_by(YearCarryForward.id):
        cfs[cf.year] = carry_forward_view(cf)
    arcs = {a.year: {"status": a.status, "created_at": a.created_at.isoformat(), "path": a.path, "rows": sum(m["rows"] for m in (a.manifest or {}).values())} for a in db.query(YearArchive).order_by(YearArchive.id)}
    keep = settings.retention_online_years
    return {
        "current_year": today.year, "retention_online_years": keep,
        "years": [{"year": y, "counts": c, "carry_forward": cfs.get(y), "archive": arcs.get(y), "past": y < today.year, "due_by_policy": y <= today.year - keep} for y, c in counts.items()],
        "note": "Master/reference data (nhà máy, cột, công thức, năng suất chuẩn, lịch, người dùng, Audit) luôn online. Chỉ dữ liệu giao dịch/lịch sử theo năm mới được lưu trữ.",
    }
