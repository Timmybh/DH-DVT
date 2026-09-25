"""Quản trị Roadmap Scenario / Version / Milestone / Target / Technology link / Rule registry (Task 5 — Issue #11).

- Lifecycle (GPT Issue #11 mục 9): Scenario & Version DRAFT→READY→REVIEWED→APPROVED, ARCHIVED; version chỉ sửa được ở DRAFT,
  khóa business inputs từ READY (không phải từ lần run). Không hard-delete scenario/version. Đổi input => version mới (copy).
- Rule registry: versioned, APPROVED bất biến; KHÔNG seed rule nào. Duyệt rule = `roadmap.approve` (kiểm ở API).
- Validation: metric hợp lệ, target numeric hữu hạn, unit bắt buộc, target_date hợp lệ, sequence/code duy nhất trong version, scope hợp lệ.
"""

from __future__ import annotations

import math
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import Factory, User
from app.models.future_technology import FutureTechnologyCandidate
from app.models.resources import MachineType
from app.models.roadmap import (
    BASELINE_BASES,
    LIFECYCLE_STATUSES,
    LIFECYCLE_TRANSITIONS,
    METRIC_CODES,
    PERIOD_TYPES,
    RULE_PERIODS,
    RULE_PROPOSAL_TYPES,
    SCOPE_TYPES,
    TARGET_KINDS,
    TECH_LINK_TYPES,
    RoadmapMilestone,
    RoadmapRule,
    RoadmapScenario,
    RoadmapScenarioVersion,
    RoadmapStatusHistory,
    RoadmapTarget,
    RoadmapTechnologyLink,
)
from app.models.technology_process import TechnologyProcessVersion
from app.services.audit import write_audit


def _bad(msg: str, code: int = 422) -> HTTPException:
    return HTTPException(code, msg)


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _num(v, name: str) -> float:
    if isinstance(v, bool) or v is None:
        raise _bad(f"{name} phải là số")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise _bad(f"{name} phải là số") from None
    if not math.isfinite(f):
        raise _bad(f"{name} phải là số hữu hạn")
    return f


def _date(v, name: str) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return date.fromisoformat(str(v))
    except (TypeError, ValueError):
        raise _bad(f"{name} phải dạng YYYY-MM-DD hợp lệ") from None


def _hist(db: Session, object_type: str, object_id: int, from_status: str | None, to_status: str, reason: str, actor: str) -> None:
    db.add(RoadmapStatusHistory(object_type=object_type, object_id=object_id, from_status=from_status, to_status=to_status, reason=reason or "", actor=actor))


def list_history(db: Session, object_type: str, object_id: int) -> list[dict]:
    rows = db.query(RoadmapStatusHistory).filter_by(object_type=object_type, object_id=object_id).order_by(RoadmapStatusHistory.id).all()
    return [{"id": h.id, "from_status": h.from_status, "to_status": h.to_status, "reason": h.reason, "actor": h.actor, "at": _iso(h.at)} for h in rows]


def _validate_scope(db: Session, scope_type: str | None, scope_value: str | None) -> tuple[str, str]:
    st = scope_type or "TOTAL"
    if st not in SCOPE_TYPES:
        raise _bad(f"scope_type phải là một trong {SCOPE_TYPES} (Task 5 chưa hỗ trợ LINE)")
    sv = (scope_value or "").strip()
    if st == "TOTAL":
        return "TOTAL", ""
    if not sv or db.query(Factory.id).filter(Factory.code == sv).first() is None:
        raise _bad(f"scope FACTORY cần factory code hợp lệ (nhận '{sv}')")
    return "FACTORY", sv


# ================================================================== Scenario
def scenario_view(s: RoadmapScenario, versions: list[RoadmapScenarioVersion] | None = None) -> dict:
    out = {
        "id": s.id, "scenario_code": s.scenario_code, "name": s.name, "description": s.description, "scope_type": s.scope_type, "scope_value": s.scope_value,
        "owner": s.owner, "status": s.status, "allowed_transitions": list(LIFECYCLE_TRANSITIONS.get(s.status, ())),
        "created_by": s.created_by, "created_at": _iso(s.created_at), "updated_by": s.updated_by, "updated_at": _iso(s.updated_at),
        "approved_by": s.approved_by, "approved_at": _iso(s.approved_at),
    }
    if versions is not None:
        out["versions"] = [{"id": v.id, "version_no": v.version_no, "status": v.status, "note": v.note, "locked_at": _iso(v.locked_at)} for v in versions]
    return out


def get_scenario(db: Session, scenario_id: int) -> RoadmapScenario:
    s = db.get(RoadmapScenario, scenario_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy Roadmap Scenario")
    return s


def list_scenarios(db: Session, status: str = "") -> list[RoadmapScenario]:
    q = db.query(RoadmapScenario)
    if status:
        q = q.filter(RoadmapScenario.status == status)
    return q.order_by(RoadmapScenario.id.desc()).all()


def scenario_versions(db: Session, scenario_id: int) -> list[RoadmapScenarioVersion]:
    return db.query(RoadmapScenarioVersion).filter_by(scenario_id=scenario_id).order_by(RoadmapScenarioVersion.version_no).all()


def create_scenario(db: Session, user: User, d: dict) -> RoadmapScenario:
    name = (d.get("name") or "").strip()
    if not name:
        raise _bad("Cần name")
    st, sv = _validate_scope(db, d.get("scope_type"), d.get("scope_value"))
    s = RoadmapScenario(scenario_code="PENDING", name=name, description=(d.get("description") or "").strip(), scope_type=st, scope_value=sv,
                        owner=(d.get("owner") or user.username).strip(), status="DRAFT", created_by=user.username)
    db.add(s)
    db.flush()
    s.scenario_code = f"RM-{s.id:06d}"  # bất biến
    _hist(db, "SCENARIO", s.id, None, "DRAFT", "created", user.username)
    db.commit()
    write_audit("ROADMAP_SCENARIO_CREATE", user=user, object_type="RoadmapScenario", object_id=s.scenario_code, detail=f"{name} [{st}/{sv or 'TOTAL'}]")
    return s


def update_scenario(db: Session, user: User, scenario_id: int, d: dict) -> RoadmapScenario:
    s = get_scenario(db, scenario_id)
    if s.status == "ARCHIVED":
        raise _bad("Scenario đã ARCHIVED — không sửa được", 409)
    if "scenario_code" in d or "status" in d:
        raise _bad("scenario_code bất biến; status chỉ đổi qua transition")
    if "name" in d:
        if not (d["name"] or "").strip():
            raise _bad("name không được để trống")
        s.name = d["name"].strip()
    if "description" in d:
        s.description = (d["description"] or "").strip()
    if "owner" in d:
        s.owner = (d["owner"] or "").strip()
    if "scope_type" in d or "scope_value" in d:
        if scenario_versions(db, s.id):
            raise _bad("Scope chỉ đổi được khi scenario chưa có version nào (version đã khóa scope riêng)", 409)
        s.scope_type, s.scope_value = _validate_scope(db, d.get("scope_type", s.scope_type), d.get("scope_value", s.scope_value))
    s.updated_by, s.updated_at = user.username, utcnow()
    db.commit()
    write_audit("ROADMAP_SCENARIO_UPDATE", user=user, object_type="RoadmapScenario", object_id=s.scenario_code, detail=s.name)
    return s


def requires_approve(from_status: str, to_status: str) -> bool:
    return to_status == "APPROVED"


def transition_scenario(db: Session, user: User, scenario_id: int, to_status: str, reason: str = "") -> RoadmapScenario:
    s = get_scenario(db, scenario_id)
    _check_transition(s.status, to_status, reason)
    now = utcnow()
    frm = s.status
    s.status, s.updated_by, s.updated_at = to_status, user.username, now
    if to_status == "APPROVED":
        s.approved_by, s.approved_at = user.username, now
    _hist(db, "SCENARIO", s.id, frm, to_status, reason, user.username)
    db.commit()
    write_audit("ROADMAP_SCENARIO_TRANSITION", user=user, object_type="RoadmapScenario", object_id=s.scenario_code, detail=f"{frm} -> {to_status}")
    return s


def _check_transition(frm: str, to: str, reason: str) -> None:
    if to not in LIFECYCLE_STATUSES:
        raise _bad(f"status phải là một trong {LIFECYCLE_STATUSES}")
    if to not in LIFECYCLE_TRANSITIONS.get(frm, ()):
        raise _bad(f"Không cho chuyển {frm} -> {to} (cho phép: {list(LIFECYCLE_TRANSITIONS.get(frm, ())) or 'không có'})", 409)
    if to == "ARCHIVED" and not (reason or "").strip():
        raise _bad("Chuyển sang ARCHIVED bắt buộc có reason")


# ================================================================== Version
def get_version(db: Session, version_id: int) -> RoadmapScenarioVersion:
    v = db.get(RoadmapScenarioVersion, version_id)
    if v is None:
        raise HTTPException(404, "Không tìm thấy Roadmap Scenario Version")
    return v


def version_milestones(db: Session, version_id: int) -> list[RoadmapMilestone]:
    return db.query(RoadmapMilestone).filter_by(version_id=version_id).order_by(RoadmapMilestone.sequence).all()


def milestone_targets(db: Session, milestone_id: int) -> list[RoadmapTarget]:
    return db.query(RoadmapTarget).filter_by(milestone_id=milestone_id).order_by(RoadmapTarget.id).all()


def version_links(db: Session, version_id: int) -> list[RoadmapTechnologyLink]:
    return db.query(RoadmapTechnologyLink).filter_by(version_id=version_id).order_by(RoadmapTechnologyLink.id).all()


def target_view(t: RoadmapTarget) -> dict:
    return {
        "id": t.id, "milestone_id": t.milestone_id, "metric_code": t.metric_code, "target_kind": t.target_kind, "target_value": t.target_value, "unit": t.unit,
        "scope_type": t.scope_type, "scope_value": t.scope_value, "period_type": t.period_type, "period_year": t.period_year, "period_month": t.period_month,
        "baseline_basis": t.baseline_basis, "baseline_ref_year": t.baseline_ref_year, "baseline_ref_month": t.baseline_ref_month, "note": t.note,
    }


def version_view(db: Session, v: RoadmapScenarioVersion, with_detail: bool = True) -> dict:
    s = get_scenario(db, v.scenario_id)
    out = {
        "id": v.id, "scenario_id": v.scenario_id, "scenario_code": s.scenario_code, "scenario_name": s.name, "version_no": v.version_no, "status": v.status,
        "scope_type": v.scope_type, "scope_value": v.scope_value, "note": v.note, "copied_from_version_id": v.copied_from_version_id,
        "locked_at": _iso(v.locked_at), "editable": v.status == "DRAFT", "allowed_transitions": list(LIFECYCLE_TRANSITIONS.get(v.status, ())),
        "reviewed_by": v.reviewed_by, "approved_by": v.approved_by, "created_by": v.created_by, "created_at": _iso(v.created_at),
    }
    if with_detail:
        out["milestones"] = [
            {"id": m.id, "code": m.code, "name": m.name, "target_date": _iso(m.target_date), "sequence": m.sequence, "note": m.note,
             "targets": [target_view(t) for t in milestone_targets(db, m.id)]}
            for m in version_milestones(db, v.id)
        ]
        out["technology_links"] = [{"id": k.id, "link_type": k.link_type, "ref_id": k.ref_id, "note": k.note} for k in version_links(db, v.id)]
    return out


def _ensure_editable(v: RoadmapScenarioVersion) -> None:
    if v.status != "DRAFT":
        raise _bad(f"Version {v.status} đã khóa business inputs — muốn đổi hãy tạo version mới (copy)", 409)


def _ensure_scenario_open(db: Session, scenario_id: int) -> RoadmapScenario:
    s = get_scenario(db, scenario_id)
    if s.status == "ARCHIVED":
        raise _bad("Scenario đã ARCHIVED", 409)
    return s


def create_version(db: Session, user: User, scenario_id: int, copy_from_version_id: int | None = None, note: str = "") -> RoadmapScenarioVersion:
    s = _ensure_scenario_open(db, scenario_id)
    src = None
    if copy_from_version_id is not None:
        src = get_version(db, copy_from_version_id)
        if src.scenario_id != s.id:
            raise _bad("copy_from_version_id phải thuộc cùng scenario")
    existing = scenario_versions(db, s.id)
    v = RoadmapScenarioVersion(scenario_id=s.id, version_no=(existing[-1].version_no + 1 if existing else 1), status="DRAFT", scope_type=s.scope_type,
                               scope_value=s.scope_value, note=(note or "")[:300], copied_from_version_id=src.id if src else None, created_by=user.username)
    db.add(v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Trùng version_no do request đồng thời — thử lại") from None
    if src is not None:
        for m in version_milestones(db, src.id):
            nm = RoadmapMilestone(version_id=v.id, code=m.code, name=m.name, target_date=m.target_date, sequence=m.sequence, note=m.note)
            db.add(nm)
            db.flush()
            for t in milestone_targets(db, m.id):
                db.add(RoadmapTarget(milestone_id=nm.id, metric_code=t.metric_code, target_kind=t.target_kind, target_value=t.target_value, unit=t.unit,
                                     scope_type=t.scope_type, scope_value=t.scope_value, period_type=t.period_type, period_year=t.period_year,
                                     period_month=t.period_month, baseline_basis=t.baseline_basis, baseline_ref_year=t.baseline_ref_year,
                                     baseline_ref_month=t.baseline_ref_month, note=t.note))
        for k in version_links(db, src.id):
            db.add(RoadmapTechnologyLink(version_id=v.id, link_type=k.link_type, ref_id=k.ref_id, note=k.note))
    _hist(db, "VERSION", v.id, None, "DRAFT", f"created{' (copy of #' + str(src.id) + ')' if src else ''}", user.username)
    db.commit()
    write_audit("ROADMAP_VERSION_CREATE", user=user, object_type="RoadmapScenarioVersion", object_id=str(v.id), detail=f"{s.scenario_code} v{v.version_no}")
    return v


def transition_version(db: Session, user: User, version_id: int, to_status: str, reason: str = "") -> RoadmapScenarioVersion:
    v = get_version(db, version_id)
    _check_transition(v.status, to_status, reason)
    if to_status != "ARCHIVED":
        _ensure_scenario_open(db, v.scenario_id)
    if to_status == "READY":
        ms = version_milestones(db, v.id)
        if not ms or not any(milestone_targets(db, m.id) for m in ms):
            raise _bad("Không thể READY: version cần ít nhất 1 milestone có ít nhất 1 target")
    now = utcnow()
    frm = v.status
    v.status = to_status
    if to_status == "READY":
        v.locked_at = now  # khóa business inputs từ READY
    if to_status == "REVIEWED":
        v.reviewed_by, v.reviewed_at = user.username, now
    if to_status == "APPROVED":
        v.approved_by, v.approved_at = user.username, now
    _hist(db, "VERSION", v.id, frm, to_status, reason, user.username)
    db.commit()
    write_audit("ROADMAP_VERSION_TRANSITION", user=user, object_type="RoadmapScenarioVersion", object_id=str(v.id), detail=f"{frm} -> {to_status}")
    return v


# ================================================================== Milestone
def _validate_milestone(d: dict, existing: RoadmapMilestone | None) -> dict:
    code = (d["code"] if "code" in d else (existing.code if existing else "")) or ""
    code = code.strip()
    if not code:
        raise _bad("Milestone cần code")
    td = _date(d["target_date"] if "target_date" in d else (existing.target_date if existing else None), "target_date")
    return {"code": code[:40], "name": ((d.get("name") if "name" in d else (existing.name if existing else "")) or "").strip()[:150], "target_date": td,
            "note": ((d.get("note") if "note" in d else (existing.note if existing else "")) or "")[:300]}


def add_milestone(db: Session, user: User, version_id: int, d: dict) -> RoadmapMilestone:
    v = get_version(db, version_id)
    _ensure_editable(v)
    _ensure_scenario_open(db, v.scenario_id)
    f = _validate_milestone(d, None)
    ms = version_milestones(db, v.id)
    seq = d.get("sequence")
    seq = int(_num(seq, "sequence")) if seq is not None else (ms[-1].sequence + 1 if ms else 1)
    if seq < 1:
        raise _bad("sequence phải >= 1")
    if any(m.code == f["code"] for m in ms):
        raise _bad(f"Trùng milestone code '{f['code']}' trong version", 409)
    if any(m.sequence == seq for m in ms):
        raise _bad(f"Trùng sequence {seq} trong version", 409)
    m = RoadmapMilestone(version_id=v.id, sequence=seq, **f)
    db.add(m)
    db.commit()
    write_audit("ROADMAP_MILESTONE_ADD", user=user, object_type="RoadmapMilestone", object_id=str(m.id), detail=f"v{v.id} {m.code} {m.target_date}")
    return m


def get_milestone(db: Session, milestone_id: int) -> RoadmapMilestone:
    m = db.get(RoadmapMilestone, milestone_id)
    if m is None:
        raise HTTPException(404, "Không tìm thấy milestone")
    return m


def update_milestone(db: Session, user: User, milestone_id: int, d: dict) -> RoadmapMilestone:
    m = get_milestone(db, milestone_id)
    v = get_version(db, m.version_id)
    _ensure_editable(v)
    f = _validate_milestone(d, m)
    seq = int(_num(d["sequence"], "sequence")) if "sequence" in d else m.sequence
    if seq < 1:
        raise _bad("sequence phải >= 1")
    others = [x for x in version_milestones(db, v.id) if x.id != m.id]
    if any(x.code == f["code"] for x in others):
        raise _bad(f"Trùng milestone code '{f['code']}' trong version", 409)
    if any(x.sequence == seq for x in others):
        raise _bad(f"Trùng sequence {seq} trong version", 409)
    m.code, m.name, m.target_date, m.note, m.sequence = f["code"], f["name"], f["target_date"], f["note"], seq
    db.commit()
    write_audit("ROADMAP_MILESTONE_UPDATE", user=user, object_type="RoadmapMilestone", object_id=str(m.id), detail=f"v{v.id} {m.code}")
    return m


def remove_milestone(db: Session, user: User, milestone_id: int) -> None:
    m = get_milestone(db, milestone_id)
    v = get_version(db, m.version_id)
    _ensure_editable(v)  # chỉ DRAFT — DRAFT chưa có run nên không mất lịch sử
    for t in milestone_targets(db, m.id):
        db.delete(t)
    code = m.code
    db.delete(m)
    db.commit()
    write_audit("ROADMAP_MILESTONE_REMOVE", user=user, object_type="RoadmapMilestone", object_id=str(milestone_id), detail=f"v{v.id} {code}")


# ================================================================== Target
def _validate_target(db: Session, v: RoadmapScenarioVersion, m: RoadmapMilestone, d: dict, existing: RoadmapTarget | None) -> dict:
    def pick(k, default=None):
        return d[k] if k in d else (getattr(existing, k) if existing is not None else default)

    metric = pick("metric_code")
    if metric not in METRIC_CODES:
        raise _bad(f"metric_code phải là một trong {METRIC_CODES}")
    kind = pick("target_kind", "ABSOLUTE") or "ABSOLUTE"
    if kind not in TARGET_KINDS:
        raise _bad(f"target_kind phải là một trong {TARGET_KINDS}")
    value = _num(pick("target_value"), "target_value")
    if kind == "ABSOLUTE" and value < 0:
        raise _bad("target_value ABSOLUTE không được âm")
    unit = (pick("unit") or "").strip()
    if not unit:
        raise _bad("unit bắt buộc")  # khác canonical => UNIT_MISMATCH lúc run, không convert ngầm
    st_in, sv_in = pick("scope_type"), pick("scope_value")
    st, sv = _validate_scope(db, st_in or v.scope_type, sv_in if st_in else v.scope_value)  # mặc định = scope version
    ptype = pick("period_type", "MONTH") or "MONTH"
    if ptype not in PERIOD_TYPES:
        raise _bad(f"period_type phải là một trong {PERIOD_TYPES}")
    pyear = pick("period_year") or m.target_date.year
    pmonth = pick("period_month") if ptype == "MONTH" else None
    if ptype == "MONTH" and pmonth is None:
        pmonth = m.target_date.month
    pyear = int(_num(pyear, "period_year"))
    if not 1900 <= pyear <= 2200:
        raise _bad("period_year không hợp lệ")
    if ptype == "MONTH":
        pmonth = int(_num(pmonth, "period_month"))
        if not 1 <= pmonth <= 12:
            raise _bad("period_month phải trong 1..12")
    basis = pick("baseline_basis")
    if basis in ("", None):
        basis = None
    elif basis not in BASELINE_BASES[metric]:
        raise _bad(f"baseline_basis của {metric} phải là một trong {BASELINE_BASES[metric]}")
    ry, rm = pick("baseline_ref_year"), pick("baseline_ref_month")
    if ry is None and rm is not None:
        raise _bad("baseline_ref_month cần baseline_ref_year")
    if ry is not None:
        ry = int(_num(ry, "baseline_ref_year"))
        if ptype == "MONTH":
            if rm is None:
                raise _bad("Kỳ tham chiếu theo MONTH cần cả baseline_ref_year và baseline_ref_month")
            rm = int(_num(rm, "baseline_ref_month"))
            if not 1 <= rm <= 12:
                raise _bad("baseline_ref_month phải trong 1..12")
        else:
            rm = None
    else:
        rm = None
    return {"metric_code": metric, "target_kind": kind, "target_value": value, "unit": unit[:20], "scope_type": st, "scope_value": sv, "period_type": ptype,
            "period_year": pyear, "period_month": pmonth if ptype == "MONTH" else None, "baseline_basis": basis, "baseline_ref_year": ry, "baseline_ref_month": rm,
            "note": ((pick("note", "") or "")[:300])}


def add_target(db: Session, user: User, milestone_id: int, d: dict) -> RoadmapTarget:
    m = get_milestone(db, milestone_id)
    v = get_version(db, m.version_id)
    _ensure_editable(v)
    t = RoadmapTarget(milestone_id=m.id, **_validate_target(db, v, m, d, None))
    db.add(t)
    db.commit()
    write_audit("ROADMAP_TARGET_ADD", user=user, object_type="RoadmapTarget", object_id=str(t.id), detail=f"v{v.id} {m.code} {t.metric_code} {t.target_kind} {t.target_value} {t.unit}")
    return t


def get_target(db: Session, target_id: int) -> RoadmapTarget:
    t = db.get(RoadmapTarget, target_id)
    if t is None:
        raise HTTPException(404, "Không tìm thấy target")
    return t


def update_target(db: Session, user: User, target_id: int, d: dict) -> RoadmapTarget:
    t = get_target(db, target_id)
    m = get_milestone(db, t.milestone_id)
    v = get_version(db, m.version_id)
    _ensure_editable(v)
    for k, val in _validate_target(db, v, m, d, t).items():
        setattr(t, k, val)
    db.commit()
    write_audit("ROADMAP_TARGET_UPDATE", user=user, object_type="RoadmapTarget", object_id=str(t.id), detail=f"v{v.id} {m.code} {t.metric_code}")
    return t


def remove_target(db: Session, user: User, target_id: int) -> None:
    t = get_target(db, target_id)
    m = get_milestone(db, t.milestone_id)
    v = get_version(db, m.version_id)
    _ensure_editable(v)
    db.delete(t)
    db.commit()
    write_audit("ROADMAP_TARGET_REMOVE", user=user, object_type="RoadmapTarget", object_id=str(target_id), detail=f"v{v.id} {m.code}")


# ================================================================== Technology links (chỉ link + snapshot, BR-516)
def add_link(db: Session, user: User, version_id: int, link_type: str, ref_id: int, note: str = "") -> RoadmapTechnologyLink:
    v = get_version(db, version_id)
    _ensure_editable(v)
    if link_type not in TECH_LINK_TYPES:
        raise _bad(f"link_type phải là một trong {TECH_LINK_TYPES}")
    if link_type == "FUTURE_CANDIDATE" and db.get(FutureTechnologyCandidate, ref_id) is None:
        raise _bad(f"FutureTechnologyCandidate id {ref_id} không tồn tại")
    if link_type == "PROCESS_VERSION" and db.get(TechnologyProcessVersion, ref_id) is None:
        raise _bad(f"TechnologyProcessVersion id {ref_id} không tồn tại")
    if db.query(RoadmapTechnologyLink.id).filter_by(version_id=v.id, link_type=link_type, ref_id=ref_id).first():
        raise _bad("Liên kết đã tồn tại", 409)
    k = RoadmapTechnologyLink(version_id=v.id, link_type=link_type, ref_id=ref_id, note=(note or "")[:300])
    db.add(k)
    db.commit()
    write_audit("ROADMAP_LINK_ADD", user=user, object_type="RoadmapScenarioVersion", object_id=str(v.id), detail=f"{link_type}#{ref_id}")
    return k


def remove_link(db: Session, user: User, link_id: int) -> None:
    k = db.get(RoadmapTechnologyLink, link_id)
    if k is None:
        raise HTTPException(404, "Không tìm thấy liên kết")
    v = get_version(db, k.version_id)
    _ensure_editable(v)
    db.delete(k)
    db.commit()
    write_audit("ROADMAP_LINK_REMOVE", user=user, object_type="RoadmapScenarioVersion", object_id=str(v.id), detail=f"{k.link_type}#{k.ref_id}")


# ================================================================== Rule registry
def rule_view(r: RoadmapRule) -> dict:
    return {
        "id": r.id, "rule_code": r.rule_code, "rule_version": r.rule_version, "proposal_type": r.proposal_type, "title": r.title, "formula_type": r.formula_type,
        "formula_text": f"quantity = ceil(gap / rate_value)  (rate_value = {r.rate_value} {r.rate_unit} / {r.rate_period})", "rate_value": r.rate_value, "rate_unit": r.rate_unit,
        "rate_period": r.rate_period, "machine_type_code": r.machine_type_code, "basis_note": r.basis_note, "approval_status": r.approval_status,
        "approved_by": r.approved_by, "approved_at": _iso(r.approved_at), "created_by": r.created_by, "created_at": _iso(r.created_at),
    }


def get_rule(db: Session, rule_id: int) -> RoadmapRule:
    r = db.get(RoadmapRule, rule_id)
    if r is None:
        raise HTTPException(404, "Không tìm thấy rule")
    return r


def list_rules(db: Session, proposal_type: str = "", approval_status: str = "") -> list[RoadmapRule]:
    q = db.query(RoadmapRule)
    if proposal_type:
        q = q.filter(RoadmapRule.proposal_type == proposal_type)
    if approval_status:
        q = q.filter(RoadmapRule.approval_status == approval_status)
    return q.order_by(RoadmapRule.rule_code, RoadmapRule.rule_version).all()


def _validate_rule(db: Session, d: dict, existing: RoadmapRule | None) -> dict:
    def pick(k, default=None):
        return d[k] if k in d else (getattr(existing, k) if existing is not None else default)

    ptype = pick("proposal_type")
    if ptype not in RULE_PROPOSAL_TYPES:
        raise _bad(f"proposal_type của rule phải là một trong {RULE_PROPOSAL_TYPES} (CAPACITY_CHANGE/TECHNOLOGY_ADOPTION không tính số trong Task 5)")
    rate = _num(pick("rate_value"), "rate_value")
    if rate <= 0:
        raise _bad("rate_value phải > 0")
    period = pick("rate_period", "MONTH") or "MONTH"
    if period not in RULE_PERIODS:
        raise _bad(f"rate_period phải là một trong {RULE_PERIODS}")
    mt = (pick("machine_type_code") or None)
    if ptype == "MACHINE_PURCHASE":
        if not mt:
            raise _bad("Rule MACHINE_PURCHASE bắt buộc machine_type_code")
        if db.get(MachineType, mt) is None:
            raise _bad(f"Loại máy '{mt}' không tồn tại")
    else:
        mt = None
    return {"proposal_type": ptype, "title": (pick("title", "") or "")[:200], "rate_value": rate, "rate_unit": (pick("rate_unit", "") or "")[:40], "rate_period": period,
            "machine_type_code": mt, "basis_note": (pick("basis_note", "") or "")[:300]}


def create_rule(db: Session, user: User, d: dict) -> RoadmapRule:
    code = (d.get("rule_code") or "").strip().upper()
    if not code:
        raise _bad("Cần rule_code")
    if db.query(RoadmapRule.id).filter_by(rule_code=code).first():
        raise _bad(f"rule_code '{code}' đã tồn tại — dùng 'new-version' để tạo phiên bản mới", 409)
    r = RoadmapRule(rule_code=code[:40], rule_version=1, approval_status="DRAFT", created_by=user.username, **_validate_rule(db, d, None))
    db.add(r)
    db.flush()
    _hist(db, "RULE", r.id, None, "DRAFT", "created", user.username)
    db.commit()
    write_audit("ROADMAP_RULE_CREATE", user=user, object_type="RoadmapRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=f"{r.proposal_type} rate={r.rate_value}")
    return r


def update_rule(db: Session, user: User, rule_id: int, d: dict) -> RoadmapRule:
    r = get_rule(db, rule_id)
    if r.approval_status != "DRAFT":
        raise _bad("Rule đã APPROVED/RETIRED bất biến — sửa = tạo version mới", 409)
    if "rule_code" in d or "rule_version" in d or "approval_status" in d:
        raise _bad("rule_code/rule_version/approval_status không sửa trực tiếp")
    for k, val in _validate_rule(db, d, r).items():
        setattr(r, k, val)
    db.commit()
    write_audit("ROADMAP_RULE_UPDATE", user=user, object_type="RoadmapRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=f"rate={r.rate_value}")
    return r


def new_rule_version(db: Session, user: User, rule_id: int) -> RoadmapRule:
    src = get_rule(db, rule_id)
    latest = db.query(RoadmapRule).filter_by(rule_code=src.rule_code).order_by(RoadmapRule.rule_version.desc()).first()
    if latest.approval_status == "DRAFT":
        raise _bad("Đã có version DRAFT của rule này — sửa/duyệt version đó", 409)
    r = RoadmapRule(rule_code=src.rule_code, rule_version=latest.rule_version + 1, proposal_type=src.proposal_type, title=src.title, formula_type=src.formula_type,
                    rate_value=src.rate_value, rate_unit=src.rate_unit, rate_period=src.rate_period, machine_type_code=src.machine_type_code, basis_note=src.basis_note,
                    approval_status="DRAFT", created_by=user.username)
    db.add(r)
    db.flush()
    _hist(db, "RULE", r.id, None, "DRAFT", f"new version of v{src.rule_version}", user.username)
    db.commit()
    write_audit("ROADMAP_RULE_NEW_VERSION", user=user, object_type="RoadmapRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=f"from v{src.rule_version}")
    return r


def approve_rule(db: Session, user: User, rule_id: int) -> RoadmapRule:
    """Quyền `roadmap.approve` do API kiểm. Không có rule nào được seed/auto-approve."""
    r = get_rule(db, rule_id)
    if r.approval_status != "DRAFT":
        raise _bad(f"Chỉ duyệt được rule DRAFT (hiện {r.approval_status})", 409)
    if not (r.basis_note or "").strip() or not (r.rate_unit or "").strip():
        raise _bad("Duyệt rule bắt buộc có rate_unit và basis_note (nguồn/căn cứ của rate)")
    now = utcnow()
    for old in db.query(RoadmapRule).filter(RoadmapRule.rule_code == r.rule_code, RoadmapRule.approval_status == "APPROVED", RoadmapRule.id != r.id).all():
        old.approval_status = "RETIRED"
        _hist(db, "RULE", old.id, "APPROVED", "RETIRED", f"superseded by v{r.rule_version}", user.username)
    r.approval_status, r.approved_by, r.approved_at = "APPROVED", user.username, now
    _hist(db, "RULE", r.id, "DRAFT", "APPROVED", "", user.username)
    db.commit()
    write_audit("ROADMAP_RULE_APPROVE", user=user, object_type="RoadmapRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=f"{r.proposal_type} rate={r.rate_value}")
    return r


def retire_rule(db: Session, user: User, rule_id: int, reason: str = "") -> RoadmapRule:
    r = get_rule(db, rule_id)
    if r.approval_status != "APPROVED":
        raise _bad(f"Chỉ retire được rule APPROVED (hiện {r.approval_status})", 409)
    if not (reason or "").strip():
        raise _bad("Retire rule bắt buộc có reason")
    r.approval_status = "RETIRED"
    _hist(db, "RULE", r.id, "APPROVED", "RETIRED", reason, user.username)
    db.commit()
    write_audit("ROADMAP_RULE_RETIRE", user=user, object_type="RoadmapRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=reason[:150])
    return r
