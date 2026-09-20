"""Nghiệp vụ Planning có DB: phiên soạn thảo độc quyền, phiên bản, Unplanned pool."""

import logging
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import utcnow
from app.models.core import Factory, User
from app.models.data import PlanRow
from app.models.planning import PlanningEditSession, PlanningVersion, PlanningVersionRow, WorkingCalendarRule
from app.services.audit import write_audit
from app.services.calendar import CalendarResolver, Rule
from app.services.dashboard import current_batch, today_local
from app.services.planning_engine import (
    OpError,
    apply_ops,
    compare_versions,
    new_uid,
    ops_hash,
    parse_line_notation,
    recheck,
    reindex,
    sort_rows,
    source_key,
)

log = logging.getLogger(__name__)

ROW_COLUMNS = [
    "row_uid", "sequence", "origin", "source_key", "source_plan_row_id", "factory_code", "primary_line", "line_raw", "line_assignments",
    "transfer", "po_number", "style_cc", "model_code", "description", "customer", "sport", "season", "quantity", "capacity", "total_day",
    "begin_prod_date", "end_prod_date", "warehouse_date", "chd", "note", "extra",
]


# ------------------------------------------------------------------ lịch & danh mục
def load_resolver(db: Session) -> CalendarResolver:
    rules = [
        Rule(r.scope_type, r.scope_key, r.rule_type, r.weekday, r.rule_date)
        for r in db.query(WorkingCalendarRule).all()
    ]
    return CalendarResolver(rules)


def factory_codes(db: Session) -> set[str]:
    return {f.code for f in db.query(Factory).filter(Factory.is_active.is_(True)).all()}


# ------------------------------------------------------------------ phiên soạn thảo (§2.1, §14)
def _expire_stale(db: Session) -> None:
    cutoff = utcnow() - timedelta(seconds=settings.planning_session_timeout_seconds)
    stale = db.query(PlanningEditSession).filter(PlanningEditSession.status == "ACTIVE", PlanningEditSession.last_heartbeat < cutoff).all()
    for s in stale:
        s.status, s.ended_at, s.close_reason = "EXPIRED", utcnow(), "Mất heartbeat (hết thời gian chờ)"
        write_audit("EDIT_SESSION_EXPIRED", username=s.username, object_type="EditSession", object_id=s.id, result="EXPIRED")
    if stale:
        db.commit()


def get_active_session(db: Session) -> PlanningEditSession | None:
    _expire_stale(db)
    return db.query(PlanningEditSession).filter(PlanningEditSession.status == "ACTIVE").first()


def session_view(s: PlanningEditSession | None, me: User | None = None) -> dict | None:
    if s is None:
        return None
    return {
        "id": s.id,
        "username": s.username,
        "status": s.status,
        "started_at": s.started_at.isoformat(),
        "last_heartbeat": s.last_heartbeat.isoformat(),
        "base_version_id": s.base_version_id,
        "is_mine": bool(me and s.user_id == me.id),
        "timeout_seconds": settings.planning_session_timeout_seconds,
    }


def acquire_session(db: Session, user: User, base_version_id: int | None) -> tuple[PlanningEditSession, bool]:
    active = get_active_session(db)
    if active is not None:
        if active.user_id == user.id:  # khôi phục phiên của chính mình (F5/đóng tab)
            active.last_heartbeat = utcnow()
            db.commit()
            return active, True
        raise HTTPException(409, f"Kế hoạch đang được {active.username} chỉnh sửa. Bạn chỉ có thể xem (View Mode).")
    session = PlanningEditSession(id=f"ES-{new_uid('')}", user_id=user.id, username=user.username, base_version_id=base_version_id)
    db.add(session)
    try:
        db.commit()
    except IntegrityError:  # ràng buộc DB: chỉ 1 ACTIVE — người khác vừa giành được
        db.rollback()
        raise HTTPException(409, "Kế hoạch vừa được người khác chuyển sang chế độ chỉnh sửa.")
    db.refresh(session)
    write_audit("EDIT_SESSION_START", user=user, object_type="EditSession", object_id=session.id)
    return session, False


def require_session(db: Session, session_id: str, user: User) -> PlanningEditSession:
    """Backend kiểm tra lại EditSessionId trên mọi API ghi/commit."""
    _expire_stale(db)
    s = db.get(PlanningEditSession, session_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy phiên soạn thảo")
    if s.status != "ACTIVE":
        raise HTTPException(409, f"Phiên soạn thảo đã {s.status} ({s.close_reason or 'không còn hiệu lực'}). Hãy vào Edit Mode lại; bản nháp cục bộ được giữ để khôi phục.")
    if s.user_id != user.id:
        raise HTTPException(403, "Phiên soạn thảo thuộc người dùng khác")
    return s


def heartbeat(db: Session, session_id: str, user: User) -> PlanningEditSession:
    s = require_session(db, session_id, user)
    s.last_heartbeat = utcnow()
    db.commit()
    return s


def close_session(db: Session, s: PlanningEditSession, status: str, reason: str) -> None:
    s.status, s.ended_at, s.close_reason = status, utcnow(), reason
    db.commit()


def release_session(db: Session, session_id: str, user: User) -> None:
    s = require_session(db, session_id, user)
    close_session(db, s, "CLOSED", "Cancel Edit")
    write_audit("EDIT_SESSION_CLOSE", user=user, object_type="EditSession", object_id=s.id, detail="Cancel Edit")


def force_unlock(db: Session, session_id: str, admin: User) -> None:
    s = db.get(PlanningEditSession, session_id)
    if s is None or s.status != "ACTIVE":
        raise HTTPException(409, "Phiên không còn ACTIVE")
    close_session(db, s, "REVOKED", f"Force Unlock bởi {admin.username}")
    write_audit("FORCE_UNLOCK", user=admin, object_type="EditSession", object_id=s.id, detail=f"chủ phiên: {s.username}")


# ------------------------------------------------------------------ dữ liệu phiên bản
def row_to_dict(r: PlanningVersionRow) -> dict:
    return {c: getattr(r, c) for c in ROW_COLUMNS}


def load_rows(db: Session, version_id: int) -> list[dict]:
    rows = db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == version_id).all()
    return sort_rows(row_to_dict(r) for r in rows)


def _serialize_row(row: dict) -> dict:
    out = {c: row.get(c) for c in ROW_COLUMNS}
    out["extra"] = row.get("extra") or {}
    return out


def _insert_rows(db: Session, version_id: int, rows: list[dict]) -> None:
    payload = [{**_serialize_row(r), "version_id": version_id} for r in rows]
    for i in range(0, len(payload), 2000):
        db.bulk_insert_mappings(PlanningVersionRow, payload[i : i + 2000])


def get_version(db: Session, version_id: int) -> PlanningVersion:
    v = db.get(PlanningVersion, version_id)
    if v is None:
        raise HTTPException(404, "Không tìm thấy phiên bản")
    return v


def version_view(v: PlanningVersion) -> dict:
    return {
        "id": v.id, "code": v.code, "year": v.year, "week": v.week, "family": v.family, "major": v.major, "minor": v.minor,
        "parent_id": v.parent_id, "status": v.status, "note": v.note, "created_by": v.created_by, "created_at": v.created_at.isoformat(),
        "row_count": v.row_count, "recheck_result": v.recheck_result, "recheck_trace_id": v.recheck_trace_id,
        "recheck_at": v.recheck_at.isoformat() if v.recheck_at else None, "recheck_summary": v.recheck_summary or {},
        "issued_at": v.issued_at.isoformat() if v.issued_at else None, "issued_by": v.issued_by, "base_version_id": v.base_version_id,
    }


def next_code(db: Session, year: int, week: int, family: str, base: PlanningVersion | None, kind: str) -> dict:
    """v = phương án tuần chính, f = phương án con của một v cụ thể (handoff §19.1)."""
    if kind == "F" and base is not None:
        root = base if base.minor is None else db.get(PlanningVersion, base.parent_id)
        minor = (db.query(func.max(PlanningVersion.minor)).filter(PlanningVersion.parent_id == root.id).scalar() or 0) + 1
        return {"code": f"{root.code}.f{minor:02d}", "year": root.year, "week": root.week, "family": root.family,
                "major": root.major, "minor": minor, "parent_id": root.id}
    major = (
        db.query(func.max(PlanningVersion.major))
        .filter(PlanningVersion.year == year, PlanningVersion.week == week, PlanningVersion.family == family, PlanningVersion.minor.is_(None))
        .scalar()
        or 0
    ) + 1
    return {"code": f"{year}.W{week:02d}.{family}.v{major:02d}", "year": year, "week": week, "family": family, "major": major, "minor": None, "parent_id": None}


def _store_recheck(v: PlanningVersion, result: dict) -> None:
    v.recheck_result, v.recheck_trace_id, v.recheck_at = result["result"], result["trace_id"], utcnow()
    v.recheck_summary = {"counts": result["counts"], "by_rule": result["by_rule"], "duration_ms": result["duration_ms"]}


# ------------------------------------------------------------------ baseline từ file Excel đã nhập
def create_baseline(db: Session, user: User, from_date: date | None, note: str) -> tuple[PlanningVersion, dict]:
    batch = current_batch(db)
    if batch is None:
        raise HTTPException(409, "Chưa nhập file kế hoạch SX — không có dữ liệu để tạo phiên bản nền")
    fmap = {f.id: f.code for f in db.query(Factory).all()}
    q = db.query(PlanRow).filter(PlanRow.batch_id == batch.id, PlanRow.planning_status == "PLANNED")
    if from_date:
        q = q.filter(PlanRow.end_prod_date >= from_date)
    plan_rows = q.order_by(PlanRow.factory_id, PlanRow.line_raw, PlanRow.begin_prod_date, PlanRow.id).all()

    excluded = {"UNASSIGNED_FACTORY": 0, "NO_LINE": 0}
    rows: list[dict] = []
    for pr in plan_rows:
        assignments, transfer, display = parse_line_notation(pr.line_raw)
        if pr.factory_id is None:
            excluded["UNASSIGNED_FACTORY"] += 1
            continue
        if not assignments:
            excluded["NO_LINE"] += 1
            continue
        rows.append(
            {
                "row_uid": new_uid("R"), "sequence": 0, "origin": "EXISTING",
                "source_key": source_key(pr.po_number, pr.style_cc, pr.model_code, pr.customer, pr.quantity), "source_plan_row_id": pr.id,
                "factory_code": fmap[pr.factory_id], "primary_line": assignments[0], "line_raw": display,
                "line_assignments": assignments, "transfer": transfer,
                "po_number": pr.po_number, "style_cc": pr.style_cc, "model_code": pr.model_code, "description": pr.description,
                "customer": pr.customer, "sport": pr.sport, "season": pr.season, "quantity": pr.quantity, "capacity": pr.capacity,
                "total_day": pr.total_day, "begin_prod_date": pr.begin_prod_date, "end_prod_date": pr.end_prod_date,
                "warehouse_date": pr.warehouse_date, "chd": pr.chd, "note": pr.note, "extra": {},
            }
        )
    # thứ tự ban đầu trong chuyền = theo ngày vào chuyền (thứ tự nguồn)
    lanes: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        lanes.setdefault((r["factory_code"], r["primary_line"]), []).append(r)
    for lane in lanes.values():
        for i, r in enumerate(lane, start=1):
            r["sequence"] = i
    rows = sort_rows(rows)

    today = today_local()
    year, week = today.isocalendar()[0], today.isocalendar()[1]
    code = next_code(db, year, week, "Master", None, "V")
    version = PlanningVersion(**code, status="COMMITTED", note=note or f"Nền từ file {batch.filename}", created_by=user.username, row_count=len(rows))
    db.add(version)
    db.flush()
    _insert_rows(db, version.id, rows)
    result = recheck(rows, load_resolver(db), factory_codes(db))
    _store_recheck(version, result)
    db.commit()
    write_audit("PLANNING_BASELINE", user=user, object_type="PlanningVersion", object_id=version.code, detail=f"{len(rows)} dòng, recheck={result['result']}", trace_id=result["trace_id"])
    return version, {"rows": len(rows), "excluded": excluded, "recheck": result["result"]}


# ------------------------------------------------------------------ Unplanned pool
def _unplanned_base_query(db: Session):
    batch = current_batch(db)
    if batch is None:
        return None
    return db.query(PlanRow).filter(PlanRow.batch_id == batch.id, PlanRow.planning_status == "UNPLANNED")


def _placed_keys(db: Session, base_version_id: int | None) -> set[str]:
    if not base_version_id:
        return set()
    return {k for (k,) in db.query(PlanningVersionRow.source_key).filter(PlanningVersionRow.version_id == base_version_id).all()}


def _unplanned_dict(pr: PlanRow, fmap: dict[int, str]) -> dict:
    return {
        "id": pr.id, "source_key": source_key(pr.po_number, pr.style_cc, pr.model_code, pr.customer, pr.quantity),
        "factory_code": fmap.get(pr.factory_id, ""), "factory_assignment": pr.factory_assignment, "mapping_status": pr.mapping_status,
        "mapping_note": pr.mapping_note, "fac_raw": pr.fac_raw,
        "po_number": pr.po_number, "style_cc": pr.style_cc, "model_code": pr.model_code, "description": pr.description,
        "customer": pr.customer, "sport": pr.sport, "season": pr.season, "quantity": pr.quantity, "capacity": pr.capacity,
        "chd": pr.chd, "note": pr.note, "po_date": pr.po_date,
    }


def unplanned_lookup(db: Session, base_version_id: int | None) -> dict[int, dict]:
    q = _unplanned_base_query(db)
    if q is None:
        return {}
    placed = _placed_keys(db, base_version_id)
    fmap = {f.id: f.code for f in db.query(Factory).all()}
    out = {}
    for pr in q.all():
        d = _unplanned_dict(pr, fmap)
        if d["source_key"] not in placed:
            out[pr.id] = d
    return out


def unplanned_page(db: Session, base_version_id: int | None, f: dict, limit: int, offset: int) -> dict:
    """Bộ lọc riêng của panel Unplanned (Correction §3–4). xn: ALL|XN1|XN2|XN3|UNASSIGNED; quick: ALL|KNOWN|UNASSIGNED."""
    q = _unplanned_base_query(db)
    if q is None:
        return {"total": 0, "rows": []}
    fmap = {fac.id: fac.code for fac in db.query(Factory).all()}
    xn = (f.get("xn") or "ALL").upper()
    if xn == "UNASSIGNED":
        q = q.filter(PlanRow.factory_assignment == "UNASSIGNED")
    elif xn != "ALL":
        fid = next((i for i, c in fmap.items() if c == xn), -1)
        q = q.filter(PlanRow.factory_id == fid)
    quick = (f.get("quick") or "ALL").upper()
    if quick == "KNOWN":
        q = q.filter(PlanRow.factory_assignment == "KNOWN")
    elif quick == "UNASSIGNED":
        q = q.filter(PlanRow.factory_assignment == "UNASSIGNED")
    for col, key in ((PlanRow.customer, "customer"), (PlanRow.season, "season"), (PlanRow.sport, "sport")):
        if f.get(key):
            q = q.filter(func.lower(col) == f[key].lower())
    for col, key in ((PlanRow.po_number, "po"), (PlanRow.style_cc, "style"), (PlanRow.model_code, "model")):
        if f.get(key):
            q = q.filter(col.ilike(f"%{f[key]}%"))
    if f.get("q"):
        like = f"%{f['q']}%"
        q = q.filter(or_(PlanRow.po_number.ilike(like), PlanRow.style_cc.ilike(like), PlanRow.model_code.ilike(like), PlanRow.description.ilike(like),
                         PlanRow.customer.ilike(like), PlanRow.sport.ilike(like), PlanRow.season.ilike(like)))
    placed = _placed_keys(db, base_version_id)
    rows = [d for d in (_unplanned_dict(pr, fmap) for pr in q.order_by(PlanRow.customer, PlanRow.po_number, PlanRow.id).all()) if d["source_key"] not in placed]
    page = rows[offset : offset + limit]
    for d in page:
        for k in ("chd", "po_date"):
            d[k] = d[k].isoformat() if d[k] else None
    return {"total": len(rows), "rows": page}


def unplanned_facets(db: Session) -> dict:
    q = _unplanned_base_query(db)
    if q is None:
        return {"customers": [], "seasons": [], "sports": []}
    def distinct(col):
        return sorted(v for (v,) in q.with_entities(col).distinct().all() if v)
    return {"customers": distinct(PlanRow.customer), "seasons": distinct(PlanRow.season), "sports": distinct(PlanRow.sport)}


# ------------------------------------------------------------------ Recheck / Commit / Issue
def build_draft(db: Session, base_version_id: int, ops: list[dict]) -> list[dict]:
    get_version(db, base_version_id)
    base_rows = load_rows(db, base_version_id)
    try:
        rows, _ = apply_ops(base_rows, unplanned_lookup(db, base_version_id), ops, load_resolver(db), factory_codes(db))
    except OpError as exc:
        raise HTTPException(422, str(exc))
    return rows


def _row_out(r: dict) -> dict:
    out = {}
    for k, v in r.items():
        out[k] = v.isoformat() if isinstance(v, (date, datetime)) else v
    return out


def run_recheck(db: Session, user: User, session: PlanningEditSession, base_version_id: int, ops: list[dict], draft_revision: int) -> dict:
    rows = build_draft(db, base_version_id, ops)
    result = recheck(rows, load_resolver(db), factory_codes(db))
    session.last_recheck_revision, session.last_recheck_hash = draft_revision, ops_hash(ops)
    session.last_recheck_result, session.last_recheck_trace = result["result"], result["trace_id"]
    db.commit()
    changed_uids = {op.get("tempRowId") and "D" + "".join(c for c in str(op["tempRowId"]) if c.isalnum())[:30] for op in ops if op.get("type") == "ADD_FROM_UNPLANNED"}
    changed_uids |= {op["rowUid"] for op in ops if op.get("rowUid")}
    computed = [_row_out(r) for r in rows if r["row_uid"] in changed_uids]
    write_audit("PLANNING_RECHECK", user=user, object_type="EditSession", object_id=session.id, result=result["result"], detail=f"rev={draft_revision} rows={len(rows)}", trace_id=result["trace_id"])
    return {**result, "draft_revision": draft_revision, "computed_rows": computed}


def commit_draft(db: Session, user: User, session: PlanningEditSession, base_version_id: int, ops: list[dict], draft_revision: int, note: str, kind: str) -> PlanningVersion:
    if session.last_recheck_revision != draft_revision or session.last_recheck_hash != ops_hash(ops):
        raise HTTPException(409, "Bản nháp đã thay đổi sau lần Recheck gần nhất — cần Recheck All Plan lại trước khi Commit.")
    if session.last_recheck_result == "ERROR":
        raise HTTPException(422, "Recheck có ERROR — không thể Commit.")
    base = get_version(db, base_version_id)
    rows = build_draft(db, base_version_id, ops)
    result = recheck(rows, load_resolver(db), factory_codes(db))  # kiểm tra lại độc lập ở server ngay lúc commit
    if result["result"] == "ERROR":
        raise HTTPException(422, "Recheck tại thời điểm Commit có ERROR — không thể Commit.")
    today = today_local()
    code = next_code(db, today.isocalendar()[0], today.isocalendar()[1], base.family, base, kind)
    version = PlanningVersion(**code, status="COMMITTED", note=note[:300], created_by=user.username, source_session_id=session.id, base_version_id=base.id, row_count=len(rows))
    db.add(version)
    db.flush()
    _insert_rows(db, version.id, rows)
    _store_recheck(version, result)
    close_session(db, session, "CLOSED", f"Commit {version.code}")
    write_audit("PLANNING_COMMIT", user=user, object_type="PlanningVersion", object_id=version.code, detail=f"base={base.code} recheck={result['result']}", trace_id=result["trace_id"])
    return version


def recheck_version(db: Session, user: User, version_id: int) -> dict:
    v = get_version(db, version_id)
    result = recheck(load_rows(db, version_id), load_resolver(db), factory_codes(db))
    _store_recheck(v, result)
    db.commit()
    write_audit("PLANNING_RECHECK", user=user, object_type="PlanningVersion", object_id=v.code, result=result["result"], trace_id=result["trace_id"])
    return result


def issue_version(db: Session, user: User, version_id: int) -> PlanningVersion:
    v = get_version(db, version_id)
    if v.status != "COMMITTED":
        raise HTTPException(409, f"Chỉ Issue được phiên bản COMMITTED (hiện là {v.status})")
    ok = v.recheck_result == "PASS" if settings.planning_issue_requires_pass else v.recheck_result in ("PASS", "WARNING")
    if not ok:
        raise HTTPException(422, f"Chỉ Issue được phiên bản có Recheck = PASS (hiện: {v.recheck_result or 'chưa Recheck'}). Kết quả Recheck của phiên bản cha không dùng lại được.")
    prev = db.query(PlanningVersion).filter(PlanningVersion.status == "ISSUED").all()
    for p in prev:
        p.status = "SUPERSEDED"
    v.status, v.issued_at, v.issued_by = "ISSUED", utcnow(), user.username
    db.commit()
    write_audit("PLANNING_ISSUE", user=user, object_type="PlanningVersion", object_id=v.code, detail=f"thay thế: {', '.join(p.code for p in prev) or '—'}")
    return v


def compare(db: Session, a_id: int, b_id: int) -> dict:
    a, b = get_version(db, a_id), get_version(db, b_id)
    diff = compare_versions(load_rows(db, a_id), load_rows(db, b_id))
    return {"a": version_view(a), "b": version_view(b), **diff}
