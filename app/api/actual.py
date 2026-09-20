from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.actual import ActualMapping, ActualObservation
from app.models.core import User
from app.models.data import SyncRun
from app.services import actual_service as svc
from app.services.audit import write_audit
from app.services.dashboard import today_local

router = APIRouter(prefix="/planning/actual", tags=["actual"])

View = Depends(require_perm("mapping.view"))
Manage = Depends(require_perm("mapping.manage"))


def _map_view(m: ActualMapping) -> dict:
    return {
        "id": m.id, "actual_key": m.actual_key, "source_system": m.source_system, "source_id": m.source_id, "fingerprint": m.fingerprint, "po": m.po, "style": m.style,
        "customer": m.customer, "factory_code": m.factory_code, "line": m.line, "attrs": m.attrs or {}, "status": m.status, "method": m.method, "confidence": m.confidence,
        "reason": m.reason, "candidates": m.candidates or [], "mapped_version_id": m.mapped_version_id, "mapped_row_uid": m.mapped_row_uid,
        "reconciled_at": m.reconciled_at.isoformat() if m.reconciled_at else None, "reconciled_by": m.reconciled_by,
    }


@router.get("/summary")
def summary(db: Session = Depends(get_db), _: User = View):
    ver = svc.reference_version(db)
    by_status = dict(db.query(ActualMapping.status, func.count(ActualMapping.id)).group_by(ActualMapping.status).all())
    last = db.query(func.max(ActualObservation.sync_run_id)).scalar()
    run = db.get(SyncRun, last) if last else None
    return {
        "version": {"id": ver.id, "code": ver.code, "status": ver.status} if ver else None,
        "mappings": {k: by_status.get(k, 0) for k in ("MATCHED", "REVIEW", "UNMATCHED", "OUT_OF_PLAN", "IGNORED")},
        "observations": db.query(func.count(ActualObservation.id)).scalar() or 0,
        "last_run": {"id": run.id, "code": run.run_code, "at": run.started_at.isoformat()} if run else None,
    }


@router.get("/mappings")
def list_mappings(status: str = "", q: str = "", factory: str = "", limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = View):
    query = db.query(ActualMapping)
    if status:
        query = query.filter(ActualMapping.status == status)
    if factory:
        query = query.filter(ActualMapping.factory_code == factory)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(ActualMapping.po.ilike(like) | ActualMapping.style.ilike(like) | ActualMapping.customer.ilike(like))
    total = query.count()
    rows = query.order_by(ActualMapping.confidence, ActualMapping.po).offset(offset).limit(limit).all()
    return {"total": total, "rows": [_map_view(m) for m in rows]}


@router.get("/mappings/{mid}/candidates")
def candidates(mid: int, db: Session = Depends(get_db), _: User = View):
    """Các dòng kế hoạch cùng PO trong phiên bản tham chiếu — để người dùng chọn khi gán tay."""
    from app.models.planning import PlanningVersionRow

    m = db.get(ActualMapping, mid)
    if m is None:
        raise HTTPException(404, "Không có bản ghi mapping")
    ver = svc.reference_version(db)
    if ver is None:
        return []
    rows = db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == ver.id, func.upper(PlanningVersionRow.po_number) == svc.norm(m.po)).all()
    return [{"row_uid": r.row_uid, "po": r.po_number, "style": r.style_cc, "customer": r.customer, "factory_code": r.factory_code, "line": r.line_raw or r.primary_line, "quantity": r.quantity,
             "begin": r.begin_prod_date.isoformat() if r.begin_prod_date else None, "end": r.end_prod_date.isoformat() if r.end_prod_date else None} for r in rows]


@router.post("/reconcile")
def reconcile(db: Session = Depends(get_db), user: User = Manage):
    res = svc.reconcile(db, user.username)
    db.commit()
    write_audit("ACTUAL_RECONCILE", user=user, object_type="ActualMapping", detail=str(res))
    return res


class MapBody(BaseModel):
    row_uid: str = Field(min_length=1, max_length=40)


@router.post("/mappings/{mid}/map")
def map_manual(mid: int, body: MapBody, db: Session = Depends(get_db), user: User = Manage):
    try:
        m = svc.set_manual(db, mid, body.row_uid, user.username)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    write_audit("ACTUAL_MAP_MANUAL", user=user, object_type="ActualMapping", object_id=str(mid), detail=f"{m.actual_key} -> {body.row_uid}")
    return _map_view(m)


class IgnoreBody(BaseModel):
    reason: str = Field("", max_length=200)


@router.post("/mappings/{mid}/ignore")
def ignore(mid: int, body: IgnoreBody, db: Session = Depends(get_db), user: User = Manage):
    try:
        m = svc.set_ignored(db, mid, user.username, body.reason)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()
    write_audit("ACTUAL_MAP_IGNORE", user=user, object_type="ActualMapping", object_id=str(mid), detail=m.actual_key)
    return _map_view(m)


@router.post("/mappings/{mid}/reset")
def reset(mid: int, db: Session = Depends(get_db), user: User = Manage):
    try:
        svc.reset_mapping(db, mid)
        db.flush()
        svc.reconcile(db, user.username)
        m = db.get(ActualMapping, mid)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()
    write_audit("ACTUAL_MAP_RESET", user=user, object_type="ActualMapping", object_id=str(mid), detail=m.actual_key)
    return _map_view(m)


@router.get("/plan-vs-actual")
def plan_vs_actual(status: str = "", factory: str = "", q: str = "", overdue: bool = False, limit: int = Query(300, ge=1, le=2000), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), _: User = View):
    data = svc.plan_vs_actual(db, today_local())
    rows = data["rows"]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    if status:
        rows = [r for r in rows if r["status"] == status]
    if factory:
        rows = [r for r in rows if r["factory_code"] == factory]
    if overdue:
        rows = [r for r in rows if r["overdue"]]
    if q:
        ql = q.strip().upper()
        rows = [r for r in rows if ql in (r["po"] or "").upper() or ql in (r["style"] or "").upper() or ql in (r["customer"] or "").upper()]
    return {"version": data["version"], "counts": counts, "total": len(rows), "rows": rows[offset:offset + limit]}


@router.get("/history")
def history(po: str = Query(min_length=1), factory: str = "", line: str = "", db: Session = Depends(get_db), _: User = View):
    return svc.history(db, po, factory or None, line or None)


@router.get("/runs")
def runs(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db), _: User = View):
    stats = db.query(ActualObservation.sync_run_id, func.count(ActualObservation.id), func.sum(cast(ActualObservation.is_new, Integer))).group_by(ActualObservation.sync_run_id).order_by(ActualObservation.sync_run_id.desc()).limit(limit).all()
    out = []
    for rid, n, new in stats:
        run = db.get(SyncRun, rid)
        out.append({"run_id": rid, "code": run.run_code if run else str(rid), "at": run.started_at.isoformat() if run else None, "observations": n, "new": int(new or 0), "changed": n - int(new or 0)})
    return out


@router.get("/runs/{run_id}/changes")
def run_changes(run_id: int, limit: int = Query(500, ge=1, le=2000), db: Session = Depends(get_db), _: User = View):
    return svc.run_changes(db, run_id, limit)


@router.get("/state")
def state(run_id: int, po: str = "", db: Session = Depends(get_db), _: User = View):
    """Thực tế tại lần đồng bộ `run_id` là gì?"""
    return svc.state_at(db, run_id, po or None)
