import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import SyncConfig, User
from app.models.data import SyncRun, SyncRunItem
from app.services.audit import write_audit
from app.services.egmf import run_revenue_sync
from app.services.plan_import import run_plan_import
from app.services.sync_core import SyncBusy

router = APIRouter(prefix="/sync", tags=["sync"])


def _run_out(r: SyncRun) -> dict:
    return {
        "id": r.id,
        "run_code": r.run_code,
        "source": r.source,
        "trigger_type": r.trigger_type,
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "duration_ms": r.duration_ms,
        "total_records": r.total_records,
        "matched": r.matched,
        "unmatched": r.unmatched,
        "ambiguous": r.ambiguous,
        "updated_rows": r.updated_rows,
        "trace_id": r.trace_id,
        "triggered_by": r.triggered_by,
        "retry_of": r.retry_of,
        "error_message": r.error_message,
    }


@router.get("/runs")
def list_runs(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(require_perm("sync.view"))):
    return [_run_out(r) for r in db.query(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit).all()]


@router.get("/runs/{run_id}")
def run_detail(
    run_id: int,
    kind: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_perm("sync.view")),
):
    run = db.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(404, "Không tìm thấy phiên đồng bộ")
    q = db.query(SyncRunItem).filter(SyncRunItem.run_id == run_id)
    if kind:
        q = q.filter(SyncRunItem.kind == kind)
    items = q.order_by(SyncRunItem.id).limit(1000).all()
    counts: dict[str, int] = {}
    for (k,) in db.query(SyncRunItem.kind).filter(SyncRunItem.run_id == run_id).all():
        counts[k] = counts.get(k, 0) + 1
    return {
        **_run_out(run),
        "summary": run.summary or {},
        "item_counts": counts,
        "items": [
            {"id": i.id, "kind": i.kind, "source_object": i.source_object, "source_key": i.source_key, "message": i.message}
            for i in items
        ],
    }


class RunRequest(BaseModel):
    source: str = "EGMF_REVENUE"


def _busy(exc: SyncBusy) -> HTTPException:
    return HTTPException(409, f"Đang có phiên đồng bộ chạy ({exc.run_code}), vui lòng đợi hoàn tất")


@router.post("/run")
def run_now(payload: RunRequest, db: Session = Depends(get_db), user: User = Depends(require_perm("sync.run"))):
    if payload.source != "EGMF_REVENUE":
        raise HTTPException(400, "Nguồn đồng bộ không hỗ trợ")
    try:
        return _run_out(run_revenue_sync(db, trigger="MANUAL", username=user.username))
    except SyncBusy as exc:
        raise _busy(exc)


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("sync.retry"))):
    """Retry luôn tạo Sync Run mới, không ghi đè kết quả run cũ."""
    old = db.get(SyncRun, run_id)
    if old is None:
        raise HTTPException(404, "Không tìm thấy phiên đồng bộ")
    if old.source != "EGMF_REVENUE":
        raise HTTPException(400, "Chỉ retry được phiên đồng bộ eGMF; với file Excel hãy nhập lại file")
    try:
        return _run_out(run_revenue_sync(db, trigger="RETRY", username=user.username, retry_of=old.id))
    except SyncBusy as exc:
        raise _busy(exc)


@router.post("/import-plan")
async def import_plan(file: UploadFile, db: Session = Depends(get_db), user: User = Depends(require_perm("sync.run"))):
    name = file.filename or "plan"
    suffix = Path(name).suffix.lower()
    if suffix not in (".xlsb", ".xlsx", ".xlsm"):
        raise HTTPException(400, "Chỉ hỗ trợ file .xlsb, .xlsx, .xlsm")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
        tmp.close()
        try:
            return _run_out(run_plan_import(db, Path(tmp.name), re.sub(r"[^\w\-. ()]", "_", name), user.username))
        except SyncBusy as exc:
            raise _busy(exc)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


class SyncConfigIO(BaseModel):
    enabled: bool
    scheduled_time: str


@router.get("/config", response_model=SyncConfigIO)
def get_config(db: Session = Depends(get_db), _: User = Depends(require_perm("sync.view"))):
    cfg = db.get(SyncConfig, 1) or SyncConfig(id=1)
    return SyncConfigIO(enabled=cfg.enabled, scheduled_time=cfg.scheduled_time)


@router.put("/config", response_model=SyncConfigIO)
def put_config(payload: SyncConfigIO, db: Session = Depends(get_db), user: User = Depends(require_perm("sync.run"))):
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", payload.scheduled_time):
        raise HTTPException(400, "Giờ chạy phải có dạng HH:MM (24 giờ)")
    cfg = db.get(SyncConfig, 1)
    if cfg is None:
        cfg = SyncConfig(id=1)
        db.add(cfg)
    cfg.enabled, cfg.scheduled_time = payload.enabled, payload.scheduled_time
    db.commit()
    write_audit("SYNC_CONFIG_CHANGE", user=user, object_type="SyncConfig", object_id="1", detail=f"enabled={cfg.enabled} time={cfg.scheduled_time}")
    return payload
