"""Executable rule registry (Task 6 — Issue #13, GPT FORMULA CONTRACT).

- Rule = tham số productivity do business khai báo + adapter allowlist (code). Productivity KHÔNG suy từ bảng nguồn nào; KHÔNG seed rule nào.
- Workflow DRAFT -> UNDER_REVIEW -> APPROVED -> RETIRED. Quyền: manage (DRAFT/UNDER_REVIEW), approve (APPROVE/RETIRE — API kiểm).
- Four-eyes: reviewer (người chuyển DRAFT->UNDER_REVIEW) != approver.
- APPROVED bất biến (sửa = version mới). APPROVED chỉ khi: adapter allowlist, owner, source_ref, source_kind thuộc nhóm được phép, effective_from,
  dimension scope/period/unit đúng, assumptions, sample calculation chạy lại bằng adapter khớp expected, reviewer khác approver.
- Không tie-break/rank: nhiều rule APPROVED hiệu lực => mỗi rule một proposal line (engine). Hai version cùng rule_code không được APPROVED chồng hiệu lực.
"""

from __future__ import annotations

import math
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.resources import MachineType
from app.models.roadmap import EXEC_APPROVABLE_SOURCE_KINDS, EXEC_BLOCKED_SOURCE_KINDS, PERIOD_TYPES, RoadmapExecutableRule, RoadmapRule
from app.services import roadmap as rm
from app.services import roadmap_adapters as ad
from app.services.audit import write_audit

_bad = rm._bad
_iso = rm._iso
EDITABLE_FIELDS = ("title", "adapter_code", "metadata_rule_id", "scope_type", "scope_value", "period_type", "machine_type_code", "productivity_value", "productivity_unit", "owner",
                   "source_kind", "source_ref", "effective_from", "effective_to", "assumptions", "sample_input", "sample_expected")


def rule_view(r: RoadmapExecutableRule) -> dict:
    a = ad.get_adapter(r.adapter_code)
    return {
        "id": r.id, "rule_code": r.rule_code, "rule_version": r.rule_version, "title": r.title, "adapter_code": r.adapter_code, "adapter_version": r.adapter_version,
        "proposal_type": r.proposal_type, "metadata_rule_id": r.metadata_rule_id, "scope_type": r.scope_type, "scope_value": r.scope_value, "period_type": r.period_type,
        "machine_type_code": r.machine_type_code, "productivity_value": r.productivity_value, "productivity_unit": r.productivity_unit, "owner": r.owner,
        "source_kind": r.source_kind, "source_ref": r.source_ref, "effective_from": _iso(r.effective_from), "effective_to": _iso(r.effective_to), "assumptions": r.assumptions,
        "sample_input": r.sample_input_json or {}, "sample_expected": r.sample_expected_json or {}, "status": r.status, "executable": r.status == "APPROVED",
        "reviewed_by": r.reviewed_by, "reviewed_at": _iso(r.reviewed_at), "approved_by": r.approved_by, "approved_at": _iso(r.approved_at), "created_by": r.created_by,
        "created_at": _iso(r.created_at), "adapter_contract": a.contract() if a else None,
    }


def snapshot(r: RoadmapExecutableRule) -> dict:
    """Snapshot business-value (vào fingerprint + run snapshot, đủ để reproduce sau khi bị supersede). KHÔNG chứa timestamp."""
    return {"rule_code": r.rule_code, "rule_version": r.rule_version, "adapter_code": r.adapter_code, "adapter_version": r.adapter_version, "proposal_type": r.proposal_type,
            "scope_type": r.scope_type, "scope_value": r.scope_value, "period_type": r.period_type, "machine_type_code": r.machine_type_code,
            "productivity_value": r.productivity_value, "productivity_unit": r.productivity_unit, "owner": r.owner, "source_kind": r.source_kind, "source_ref": r.source_ref,
            "effective_from": _iso(r.effective_from), "effective_to": _iso(r.effective_to), "assumptions": r.assumptions, "metadata_rule_id": r.metadata_rule_id,
            "sample_input": r.sample_input_json or {}, "sample_expected": r.sample_expected_json or {}, "reviewed_by": r.reviewed_by, "approved_by": r.approved_by}


def get_rule(db: Session, rule_id: int) -> RoadmapExecutableRule:
    r = db.get(RoadmapExecutableRule, rule_id)
    if r is None:
        raise HTTPException(404, "Không tìm thấy executable rule")
    return r


def list_rules(db: Session, proposal_type: str = "", status: str = "") -> list[RoadmapExecutableRule]:
    q = db.query(RoadmapExecutableRule)
    if proposal_type:
        q = q.filter(RoadmapExecutableRule.proposal_type == proposal_type)
    if status:
        q = q.filter(RoadmapExecutableRule.status == status)
    return q.order_by(RoadmapExecutableRule.rule_code, RoadmapExecutableRule.rule_version).all()


def approved_rules(db: Session) -> list[RoadmapExecutableRule]:
    return db.query(RoadmapExecutableRule).filter(RoadmapExecutableRule.status == "APPROVED").order_by(RoadmapExecutableRule.rule_code, RoadmapExecutableRule.rule_version).all()


def is_effective(r: RoadmapExecutableRule, on: date | None) -> bool:
    if on is None or r.effective_from is None:
        return False
    return r.effective_from <= on and (r.effective_to is None or on <= r.effective_to)


# ------------------------------------------------------------------ validate (cấu trúc — áp dụng khi tạo/sửa)
def _validate(db: Session, d: dict, existing: RoadmapExecutableRule | None) -> dict:
    def pick(k, default=None):
        return d[k] if k in d else (getattr(existing, k) if existing is not None and hasattr(existing, k) else default)

    code = (pick("adapter_code") or "").strip()
    adapter = ad.get_adapter(code)
    if adapter is None:
        raise _bad(f"adapter_code phải nằm trong allowlist {ad.ALLOWLISTED_ADAPTERS} (nhận '{code}')")
    period = pick("period_type")
    if period not in PERIOD_TYPES:
        raise _bad(f"period_type phải là một trong {PERIOD_TYPES} — không quy đổi DAY→MONTH/YEAR")
    st, sv = rm._validate_scope(db, pick("scope_type"), pick("scope_value"))
    pv = pick("productivity_value")
    if isinstance(pv, bool) or pv is None:
        raise _bad("productivity_value bắt buộc và phải là số > 0 (business khai báo, không suy từ DB)")
    try:
        pv = float(pv)
    except (TypeError, ValueError):
        raise _bad("productivity_value phải là số > 0") from None
    if not math.isfinite(pv) or pv <= 0:
        raise _bad("productivity_value phải là số hữu hạn > 0")
    unit = (pick("productivity_unit") or "").strip()
    expected_unit = adapter.unit_for(period)
    if unit != expected_unit:
        raise _bad(f"productivity_unit phải đúng '{expected_unit}' (nhận '{unit}') — dimension phải khớp period, không quy đổi")
    mt = (pick("machine_type_code") or "").strip() or None
    if adapter.needs_machine_type:
        if not mt:
            raise _bad("Adapter machine bắt buộc machine_type_code explicit (1 rule = 1 loại máy)")
        if db.get(MachineType, mt) is None:
            raise _bad(f"Loại máy '{mt}' không tồn tại")
    elif mt:
        raise _bad("Adapter labor không dùng machine_type_code")
    mid = pick("metadata_rule_id")
    if mid is not None:
        m = db.get(RoadmapRule, mid)
        if m is None or m.proposal_type != adapter.proposal_type:
            raise _bad("metadata_rule_id không tồn tại hoặc khác proposal_type của adapter")
    ef = rm._date(pick("effective_from"), "effective_from") if pick("effective_from") else None
    et = rm._date(pick("effective_to"), "effective_to") if pick("effective_to") else None
    if et is not None and (ef is None or et < ef):
        raise _bad("effective_to phải >= effective_from (và cần effective_from)")
    si = d["sample_input"] if "sample_input" in d else (existing.sample_input_json if existing is not None else None)
    se = d["sample_expected"] if "sample_expected" in d else (existing.sample_expected_json if existing is not None else None)
    for nm, val in (("sample_input", si), ("sample_expected", se)):
        if val is not None and not isinstance(val, dict):
            raise _bad(f"{nm} phải là JSON object")
        if val is not None and len(str(val)) > 4000:
            raise _bad(f"{nm} quá lớn")
    sk = (pick("source_kind") or "").strip().upper()  # tự do ở DRAFT/UNDER_REVIEW; chặn ở APPROVE
    return {"title": (pick("title", "") or "")[:200], "adapter_code": adapter.code, "adapter_version": adapter.version, "proposal_type": adapter.proposal_type, "metadata_rule_id": mid,
            "scope_type": st, "scope_value": sv, "period_type": period, "machine_type_code": mt, "productivity_value": pv, "productivity_unit": unit,
            "owner": (pick("owner", "") or "").strip()[:100], "source_kind": sk[:30], "source_ref": (pick("source_ref", "") or "").strip()[:300], "effective_from": ef, "effective_to": et,
            "assumptions": (pick("assumptions", "") or "").strip()[:500], "sample_input_json": si or {}, "sample_expected_json": se or {}}


# ------------------------------------------------------------------ sample calculation
def verify_sample(r: RoadmapExecutableRule) -> dict:
    """Chạy lại sample bằng adapter và đối chiếu expected (exact Decimal). Sample phải khớp chính rule (productivity/unit/period/machine type)."""
    a = ad.get_adapter(r.adapter_code)
    errors: list[str] = []
    si, se = r.sample_input_json or {}, r.sample_expected_json or {}
    if a is None:
        return {"ok": False, "errors": [f"adapter '{r.adapter_code}' không nằm trong allowlist"], "actual": None}
    if not si or not se:
        return {"ok": False, "errors": ["Thiếu sample_input và/hoặc sample_expected (sample calculation bắt buộc)"], "actual": None}
    if si.get("period_type") != r.period_type:
        errors.append("sample_input.period_type khác period_type của rule")
    if si.get("productivity_unit") != r.productivity_unit:
        errors.append("sample_input.productivity_unit khác productivity_unit của rule")
    if not ad.same_number(si.get(a.productivity_key), r.productivity_value):
        errors.append(f"sample_input.{a.productivity_key} khác productivity_value của rule")
    if a.needs_machine_type and si.get("machine_type_code") != r.machine_type_code:
        errors.append("sample_input.machine_type_code khác machine_type_code của rule")
    actual = None
    try:
        actual = ad.run_adapter(r.adapter_code, si)
    except ad.AdapterInputError as e:
        errors.append(f"sample_input không hợp lệ: {e}")
    if actual is not None:
        for k in a.result_keys:
            if k not in se:
                errors.append(f"sample_expected thiếu '{k}'")
            elif not ad.same_number(se[k], actual[k]):
                errors.append(f"sample_expected.{k}={se[k]} không khớp kết quả adapter {actual[k]}")
    return {"ok": not errors, "errors": errors, "actual": actual}


def _completeness_errors(r: RoadmapExecutableRule) -> list[str]:
    errs = []
    if not r.owner:
        errs.append("owner")
    if not r.source_kind:
        errs.append("source_kind")
    if not r.source_ref:
        errs.append("source_ref")
    if r.effective_from is None:
        errs.append("effective_from")
    if not r.assumptions:
        errs.append("assumptions")
    out = [f"Thiếu: {', '.join(errs)}"] if errs else []
    out += verify_sample(r)["errors"]
    return out


# ------------------------------------------------------------------ CRUD / workflow
def create_rule(db: Session, user: User, d: dict) -> RoadmapExecutableRule:
    code = (d.get("rule_code") or "").strip().upper()
    if not code:
        raise _bad("Cần rule_code")
    if db.query(RoadmapExecutableRule.id).filter_by(rule_code=code).first():
        raise _bad(f"rule_code '{code}' đã tồn tại — dùng 'new-version' để tạo phiên bản mới", 409)
    r = RoadmapExecutableRule(rule_code=code[:40], rule_version=1, status="DRAFT", created_by=user.username, **_validate(db, d, None))
    db.add(r)
    db.flush()
    rm._hist(db, "EXEC_RULE", r.id, None, "DRAFT", "created", user.username)
    db.commit()
    write_audit("ROADMAP_EXEC_RULE_CREATE", user=user, object_type="RoadmapExecutableRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=r.adapter_code)
    return r


def update_rule(db: Session, user: User, rule_id: int, d: dict) -> RoadmapExecutableRule:
    r = get_rule(db, rule_id)
    if r.status != "DRAFT":
        raise _bad(f"Rule {r.status} bất biến — chỉ sửa được DRAFT; sửa = tạo version mới", 409)
    if any(k in d for k in ("rule_code", "rule_version", "status", "reviewed_by", "approved_by", "proposal_type", "adapter_version")):
        raise _bad("rule_code/rule_version/status/reviewer/approver/proposal_type/adapter_version không sửa trực tiếp")
    for k, val in _validate(db, d, r).items():
        setattr(r, k, val)
    db.commit()
    write_audit("ROADMAP_EXEC_RULE_UPDATE", user=user, object_type="RoadmapExecutableRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=r.adapter_code)
    return r


def new_version(db: Session, user: User, rule_id: int) -> RoadmapExecutableRule:
    src = get_rule(db, rule_id)
    latest = db.query(RoadmapExecutableRule).filter_by(rule_code=src.rule_code).order_by(RoadmapExecutableRule.rule_version.desc()).first()
    if latest.status in ("DRAFT", "UNDER_REVIEW"):
        raise _bad(f"Đã có version {latest.status} (v{latest.rule_version}) của rule này — xử lý version đó trước", 409)
    r = RoadmapExecutableRule(
        rule_code=src.rule_code, rule_version=latest.rule_version + 1, title=src.title, adapter_code=src.adapter_code, adapter_version=src.adapter_version, proposal_type=src.proposal_type,
        metadata_rule_id=src.metadata_rule_id, scope_type=src.scope_type, scope_value=src.scope_value, period_type=src.period_type, machine_type_code=src.machine_type_code,
        productivity_value=src.productivity_value, productivity_unit=src.productivity_unit, owner=src.owner, source_kind=src.source_kind, source_ref=src.source_ref,
        effective_from=src.effective_from, effective_to=src.effective_to, assumptions=src.assumptions, sample_input_json=dict(src.sample_input_json or {}),
        sample_expected_json=dict(src.sample_expected_json or {}), status="DRAFT", created_by=user.username)
    db.add(r)
    db.flush()
    rm._hist(db, "EXEC_RULE", r.id, None, "DRAFT", f"new version of v{src.rule_version}", user.username)
    db.commit()
    write_audit("ROADMAP_EXEC_RULE_NEW_VERSION", user=user, object_type="RoadmapExecutableRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=f"from v{src.rule_version}")
    return r


def submit_review(db: Session, user: User, rule_id: int) -> RoadmapExecutableRule:
    """DRAFT -> UNDER_REVIEW. Người thực hiện chuyển này là reviewer (four-eyes so với approver)."""
    r = get_rule(db, rule_id)
    if r.status != "DRAFT":
        raise _bad(f"Chỉ chuyển UNDER_REVIEW từ DRAFT (hiện {r.status})", 409)
    errs = _completeness_errors(r)
    if errs:
        raise _bad("Chưa đủ điều kiện đưa vào review: " + "; ".join(errs))
    r.status, r.reviewed_by, r.reviewed_at = "UNDER_REVIEW", user.username, utcnow()
    rm._hist(db, "EXEC_RULE", r.id, "DRAFT", "UNDER_REVIEW", "", user.username)
    db.commit()
    write_audit("ROADMAP_EXEC_RULE_REVIEW", user=user, object_type="RoadmapExecutableRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=r.adapter_code)
    return r


def _overlap(a: RoadmapExecutableRule, b: RoadmapExecutableRule) -> bool:
    a_to, b_to = a.effective_to or date.max, b.effective_to or date.max
    return a.effective_from <= b_to and b.effective_from <= a_to


def approve_rule(db: Session, user: User, rule_id: int) -> RoadmapExecutableRule:
    """Quyền `roadmap.approve` do API kiểm. Không có rule nào được seed/auto-approve."""
    r = get_rule(db, rule_id)
    if r.status != "UNDER_REVIEW":
        raise _bad(f"Chỉ duyệt được rule UNDER_REVIEW (hiện {r.status})", 409)
    if not r.reviewed_by:
        raise _bad("Rule chưa có reviewer", 409)
    if r.reviewed_by == user.username:
        raise _bad("Four-eyes: người duyệt (approver) phải khác người đã đưa rule vào review (reviewer)", 409)
    if ad.get_adapter(r.adapter_code) is None:
        raise _bad(f"Adapter '{r.adapter_code}' không nằm trong allowlist", 409)
    sk = (r.source_kind or "").upper()
    if sk in EXEC_BLOCKED_SOURCE_KINDS or sk not in EXEC_APPROVABLE_SOURCE_KINDS:
        raise _bad(f"source_kind '{r.source_kind}' không được APPROVE — chỉ chấp nhận {EXEC_APPROVABLE_SOURCE_KINDS} (ESTIMATE/DEFAULT/CLAIMED/BROCHURE/PLACEHOLDER/UNVERIFIED bị chặn)", 409)
    errs = _completeness_errors(r)
    if errs:
        raise _bad("Chưa đủ điều kiện APPROVE: " + "; ".join(errs), 409)
    for o in db.query(RoadmapExecutableRule).filter(RoadmapExecutableRule.rule_code == r.rule_code, RoadmapExecutableRule.status == "APPROVED", RoadmapExecutableRule.id != r.id).all():
        if _overlap(r, o):
            raise _bad(f"Version v{o.rule_version} của rule này đang APPROVED và hiệu lực chồng — retire nó hoặc đặt effective_to trước khi duyệt v{r.rule_version}", 409)
    r.status, r.approved_by, r.approved_at = "APPROVED", user.username, utcnow()
    rm._hist(db, "EXEC_RULE", r.id, "UNDER_REVIEW", "APPROVED", "", user.username)
    db.commit()
    write_audit("ROADMAP_EXEC_RULE_APPROVE", user=user, object_type="RoadmapExecutableRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=r.adapter_code)
    return r


def retire_rule(db: Session, user: User, rule_id: int, reason: str = "") -> RoadmapExecutableRule:
    r = get_rule(db, rule_id)
    if r.status not in ("APPROVED", "UNDER_REVIEW"):
        raise _bad(f"Chỉ retire được rule APPROVED/UNDER_REVIEW (hiện {r.status})", 409)
    if not (reason or "").strip():
        raise _bad("Retire rule bắt buộc có reason")
    frm = r.status
    r.status = "RETIRED"
    rm._hist(db, "EXEC_RULE", r.id, frm, "RETIRED", reason.strip(), user.username)
    db.commit()
    write_audit("ROADMAP_EXEC_RULE_RETIRE", user=user, object_type="RoadmapExecutableRule", object_id=f"{r.rule_code} v{r.rule_version}", detail=reason[:150])
    return r
