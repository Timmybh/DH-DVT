from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.models.planning import PlanningVersion, PlanningVersionRow
from app.services import planning_service as svc
from app.services.audit import write_audit

router = APIRouter(prefix="/planning", tags=["planning"])

MAX_OPS = 5000


# ------------------------------------------------------------------ phiên soạn thảo
class AcquireBody(BaseModel):
    base_version_id: int | None = None


@router.get("/session/current")
def current_session(db: Session = Depends(get_db), user: User = Depends(require_perm("planning.view"))):
    return {"active": svc.session_view(svc.get_active_session(db), user)}


@router.post("/session")
def acquire(body: AcquireBody, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.edit"))):
    session, resumed = svc.acquire_session(db, user, body.base_version_id)
    return {"session": svc.session_view(session, user), "resumed": resumed}


@router.post("/session/{session_id}/heartbeat")
def heartbeat(session_id: str, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.edit"))):
    return svc.session_view(svc.heartbeat(db, session_id, user), user)


@router.post("/session/{session_id}/release")
def release(session_id: str, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.edit"))):
    svc.release_session(db, session_id, user)
    return {"ok": True}


@router.post("/session/{session_id}/force-unlock")
def force_unlock(session_id: str, db: Session = Depends(get_db), admin: User = Depends(require_perm("planning.force_unlock"))):
    svc.force_unlock(db, session_id, admin)
    return {"ok": True}


class DraftBody(BaseModel):
    base_version_id: int
    ops: list[dict] = Field(default_factory=list)
    draft_revision: int = 0


class CommitBody(DraftBody):
    note: str = ""
    kind: str = Field("F", pattern="^(F|V)$")  # F = phương án con của version cơ sở, V = phương án tuần mới


def _stamp(ops: list[dict], username: str) -> list[dict]:
    """Người thực hiện ghi đè OFF DAYS lấy từ phiên đăng nhập (client chỉ gửi giá trị, lý do, thời điểm)."""
    for op in ops:
        if op.get("type") == "SET_OFF_DAYS":
            op["by"] = username
    return ops


def _check_ops(ops: list[dict]) -> None:
    if len(ops) > MAX_OPS:
        raise HTTPException(413, f"Quá nhiều thao tác trong một bản nháp (tối đa {MAX_OPS})")


@router.post("/session/{session_id}/recheck")
def recheck_draft(session_id: str, body: DraftBody, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.recheck"))):
    _check_ops(body.ops)
    _stamp(body.ops, user.username)
    session = svc.require_session(db, session_id, user)
    return svc.run_recheck(db, user, session, body.base_version_id, body.ops, body.draft_revision)


@router.post("/session/{session_id}/commit")
def commit(session_id: str, body: CommitBody, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.commit"))):
    _check_ops(body.ops)
    _stamp(body.ops, user.username)
    session = svc.require_session(db, session_id, user)
    version = svc.commit_draft(db, user, session, body.base_version_id, body.ops, body.draft_revision, body.note, body.kind)
    return svc.version_view(version)


# ------------------------------------------------------------------ phiên bản
@router.get("/versions")
def list_versions(db: Session = Depends(get_db), _: User = Depends(require_perm("planning.view"))):
    versions = db.query(PlanningVersion).order_by(PlanningVersion.year.desc(), PlanningVersion.week.desc(), PlanningVersion.major.desc(), PlanningVersion.minor.asc().nullsfirst()).all()
    return [svc.version_view(v) for v in versions]


class BaselineBody(BaseModel):
    from_date: date | None = None
    note: str = ""


@router.post("/baseline")
def baseline(body: BaselineBody, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.commit"))):
    version, info = svc.create_baseline(db, user, body.from_date, body.note)
    return {"version": svc.version_view(version), **info}


@router.get("/versions/{version_id}")
def version_detail(version_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("planning.view"))):
    return svc.version_view(svc.get_version(db, version_id))


@router.get("/versions/{version_id}/lanes")
def version_lanes(version_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("planning.view"))):
    svc.get_version(db, version_id)
    rows = (
        db.query(PlanningVersionRow.factory_code, PlanningVersionRow.primary_line, func.count(PlanningVersionRow.id), func.coalesce(func.sum(PlanningVersionRow.quantity), 0.0))
        .filter(PlanningVersionRow.version_id == version_id)
        .group_by(PlanningVersionRow.factory_code, PlanningVersionRow.primary_line)
        .order_by(PlanningVersionRow.factory_code, PlanningVersionRow.primary_line)
        .all()
    )
    return [{"factory": f, "line": l, "rows": n, "quantity": float(q)} for f, l, n, q in rows]


@router.get("/versions/{version_id}/rows")
def version_rows(
    version_id: int,
    factory: str | None = None,
    line: str | None = None,
    q: str | None = None,
    limit: int = Query(300, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_perm("planning.view")),
):
    svc.get_version(db, version_id)
    query = db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == version_id)
    if factory:
        query = query.filter(PlanningVersionRow.factory_code == factory)
    if line:
        query = query.filter(PlanningVersionRow.primary_line == line)
    if q:
        like = f"%{q}%"
        query = query.filter(PlanningVersionRow.po_number.ilike(like) | PlanningVersionRow.description.ilike(like) | PlanningVersionRow.customer.ilike(like) | PlanningVersionRow.style_cc.ilike(like))
    total = query.count()
    rows = query.order_by(PlanningVersionRow.factory_code, PlanningVersionRow.primary_line, PlanningVersionRow.sequence).offset(offset).limit(limit).all()
    dicts = [svc.row_to_dict(r) for r in rows]
    from app.services import so_service

    so_service.attach_so(db, dicts)
    refs = svc.refs_for_rows(db, dicts)
    return {"total": total, "rows": [{**svc._row_out(d), "ref": refs.get(d["row_uid"], {}), "calc": svc.row_calc(d, refs.get(d["row_uid"]))} for d in dicts]}


@router.post("/versions/{version_id}/recheck")
def recheck_version(version_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.recheck"))):
    result = svc.recheck_version(db, user, version_id)
    return {**result, "issues": result["issues"][:500]}


@router.post("/versions/{version_id}/issue")
def issue(version_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("planning.issue"))):
    return svc.version_view(svc.issue_version(db, user, version_id))


@router.get("/compare")
def compare(a: int, b: int, db: Session = Depends(get_db), _: User = Depends(require_perm("planning.view"))):
    return svc.compare(db, a, b)


# ------------------------------------------------------------------ Unplanned pool
@router.get("/unplanned")
def unplanned(
    base_version_id: int | None = None,
    xn: str = "ALL",
    quick: str = "ALL",
    customer: str | None = None,
    season: str | None = None,
    sport: str | None = None,
    po: str | None = None,
    style: str | None = None,
    model: str | None = None,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_perm("planning.view")),
):
    if xn.upper() not in ("ALL", "UNASSIGNED") and xn.upper() not in svc.factory_codes(db):
        raise HTTPException(400, "Giá trị lọc Xí nghiệp không hợp lệ")
    if quick.upper() not in ("ALL", "KNOWN", "UNASSIGNED"):
        raise HTTPException(400, "Giá trị Quick filter không hợp lệ")
    filters = dict(xn=xn, quick=quick, customer=customer, season=season, sport=sport, po=po, style=style, model=model, q=q)
    return svc.unplanned_page(db, base_version_id, filters, limit, offset)


@router.get("/unplanned/facets")
def unplanned_facets(db: Session = Depends(get_db), _: User = Depends(require_perm("planning.view"))):
    return svc.unplanned_facets(db)
