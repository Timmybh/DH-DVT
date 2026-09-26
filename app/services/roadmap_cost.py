"""Cost evidence + asset refs (Task 8 — Issue #17, GPT COST/EVIDENCE CONTRACT).

- Cost evidence là EVIDENCE versioned/effective-dated (BR-801), không phải field giá sống: DRAFT -> UNDER_REVIEW -> APPROVED -> RETIRED, four-eyes reviewer != approver,
  APPROVED bất biến (sửa = version mới), RETIRED chỉ từ APPROVED + reason. KHÔNG seed evidence. Nhiều evidence APPROVED cùng subject/window là hợp lệ (không supersede, không overlap-block).
- MACHINE_UNIT_PRICE approvable: SUPPLIER_QUOTATION / APPROVED_CONTRACT_PRICE / APPROVED_BUDGET_STANDARD / CONTROLLED_PURCHASE_HISTORY;
  LABOR_COST_PER_WORKER_PERIOD approvable: HR_APPROVED_COST_STANDARD / APPROVED_BUDGET_STANDARD. BROCHURE/CLAIMED/ESTIMATE/DEFAULT/PLACEHOLDER/UNVERIFIED_WEB_PRICE lưu được ở DRAFT/UNDER_REVIEW, không APPROVE.
- Amount = Decimal (scale 6, không round khi cộng), currency `^[A-Z]{3}$` (không FX). Machine: price_basis enum bắt buộc, chỉ mô tả phạm vi thương mại — KHÔNG cộng thuế/vận chuyển/lắp đặt.
- Asset ref: chỉ tham chiếu (https:// hoặc opaque asset_ref), không upload/download/generate/render, không phải evidence tài chính.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.future_technology import FutureTechnologyCandidate
from app.models.resources import MachineModel, MachineType
from app.models.roadmap import (
    ASSET_KINDS,
    ASSET_SUBJECT_TYPES,
    COST_APPROVABLE_SOURCE_KINDS,
    COST_BLOCKED_SOURCE_KINDS,
    COST_FAMILIES,
    MACHINE_PRICE_BASES,
    PERIOD_TYPES,
    RoadmapAssetRef,
    RoadmapCostEvidence,
)
from app.services import roadmap as rm
from app.services.audit import write_audit

_bad = rm._bad
_iso = rm._iso
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
HTTPS_RE = re.compile(r"^https://[^\s<>\"']+$")
OPAQUE_RE = re.compile(r"^[A-Za-z0-9_./:#-]{1,200}$")
BAD_SCHEMES = ("javascript:", "data:", "file:", "vbscript:", "http:")


def to_decimal(v, name: str) -> Decimal:
    if isinstance(v, bool) or v is None:
        raise _bad(f"{name} phải là số")
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        raise _bad(f"{name} phải là số") from None
    if not d.is_finite():
        raise _bad(f"{name} phải là số hữu hạn")
    if d.as_tuple().exponent < -6:
        raise _bad(f"{name} tối đa 6 chữ số thập phân")
    return d


def dstr(d: Decimal) -> str:
    """Biểu diễn Decimal chính xác dạng chuỗi (scale 6) cho JSON/snapshot."""
    return f"{Decimal(d):.6f}"


# ------------------------------------------------------------------ evidence view / snapshot
def evidence_view(e: RoadmapCostEvidence) -> dict:
    return {
        "id": e.id, "evidence_code": e.evidence_code, "evidence_version": e.evidence_version, "cost_family": e.cost_family, "machine_type_code": e.machine_type_code,
        "machine_model_id": e.machine_model_id, "future_candidate_id": e.future_candidate_id, "scope_type": e.scope_type, "scope_value": e.scope_value, "cost_period": e.cost_period,
        "amount": dstr(e.amount), "currency": e.currency, "price_basis": e.price_basis, "vendor": e.vendor, "source_kind": e.source_kind, "source_ref": e.source_ref,
        "evidence_date": _iso(e.evidence_date), "quote_valid_until": _iso(e.quote_valid_until), "effective_from": _iso(e.effective_from), "effective_to": _iso(e.effective_to),
        "note": e.note, "status": e.status, "reviewed_by": e.reviewed_by, "approved_by": e.approved_by, "approved_at": _iso(e.approved_at), "retire_reason": e.retire_reason,
        "created_by": e.created_by, "created_at": _iso(e.created_at),
    }


def evidence_snapshot(e: RoadmapCostEvidence) -> dict:
    """Snapshot business-value của evidence (vào binding/package). Không timestamp hệ thống."""
    v = evidence_view(e)
    for k in ("created_by", "created_at", "approved_at", "note"):
        v.pop(k, None)
    return v


def get_evidence(db: Session, evidence_id: int) -> RoadmapCostEvidence:
    e = db.get(RoadmapCostEvidence, evidence_id)
    if e is None:
        raise HTTPException(404, "Không tìm thấy cost evidence")
    return e


def list_evidence(db: Session, cost_family: str = "", status: str = "") -> list[RoadmapCostEvidence]:
    q = db.query(RoadmapCostEvidence)
    if cost_family:
        q = q.filter(RoadmapCostEvidence.cost_family == cost_family)
    if status:
        q = q.filter(RoadmapCostEvidence.status == status)
    return q.order_by(RoadmapCostEvidence.evidence_code, RoadmapCostEvidence.evidence_version).all()


# ------------------------------------------------------------------ validate cấu trúc
def check_model_candidate(db: Session, machine_type_code: str, model_id: int | None, candidate_id: int | None) -> None:
    """model/candidate (nếu có) phải cùng machine_type và nhất quán với nhau."""
    m = c = None
    if model_id is not None:
        m = db.get(MachineModel, model_id)
        if m is None or m.machine_type_code != machine_type_code:
            raise _bad("machine_model_id không tồn tại hoặc khác machine_type_code", 422)
    if candidate_id is not None:
        c = db.get(FutureTechnologyCandidate, candidate_id)
        if c is None or c.machine_type_code != machine_type_code:
            raise _bad("future_candidate_id không tồn tại hoặc khác machine_type_code", 422)
    if m is not None and c is not None and c.machine_model_id is not None and c.machine_model_id != m.id:
        raise _bad("machine_model_id và future_candidate_id không nhất quán (candidate gắn model khác)", 422)


def _validate(db: Session, d: dict, existing: RoadmapCostEvidence | None) -> dict:
    def pick(k, default=None):
        return d[k] if k in d else (getattr(existing, k) if existing is not None else default)

    fam = pick("cost_family")
    if fam not in COST_FAMILIES:
        raise _bad(f"cost_family phải là một trong {COST_FAMILIES} (TECHNOLOGY/CAPACITY cost chưa hỗ trợ, không có OTHER_COST)")
    amount = to_decimal(pick("amount"), "amount")
    if amount <= 0:
        raise _bad("amount phải > 0")
    cur = (pick("currency") or "").strip().upper()
    if not CURRENCY_RE.match(cur):
        raise _bad("currency phải là mã 3 chữ in hoa (^[A-Z]{3}$) — không FX")
    out = {"cost_family": fam, "amount": amount, "currency": cur, "machine_type_code": None, "machine_model_id": None, "future_candidate_id": None, "scope_type": "", "scope_value": "",
           "cost_period": "", "price_basis": "", "vendor": (pick("vendor", "") or "").strip()[:150], "source_kind": (pick("source_kind", "") or "").strip().upper()[:30],
           "source_ref": (pick("source_ref", "") or "").strip()[:300], "note": (pick("note", "") or "").strip()[:300]}
    if fam == "MACHINE_UNIT_PRICE":
        mt = (pick("machine_type_code") or "").strip()
        if not mt or db.get(MachineType, mt) is None:
            raise _bad("Machine evidence bắt buộc machine_type_code hợp lệ")
        mid, cid = pick("machine_model_id"), pick("future_candidate_id")
        check_model_candidate(db, mt, mid, cid)
        pb = (pick("price_basis") or "").strip().upper()
        if pb and pb not in MACHINE_PRICE_BASES:
            raise _bad(f"price_basis phải là một trong {MACHINE_PRICE_BASES}")
        if pick("scope_type") or pick("cost_period"):
            raise _bad("Machine evidence không dùng scope/cost_period")
        out.update(machine_type_code=mt, machine_model_id=mid, future_candidate_id=cid, price_basis=pb)
    else:
        if pick("machine_type_code") or pick("machine_model_id") or pick("future_candidate_id") or pick("price_basis"):
            raise _bad("Labor evidence không dùng machine_type/model/candidate/price_basis")
        st, sv = rm._validate_scope(db, pick("scope_type"), pick("scope_value"))
        per = pick("cost_period")
        if per not in PERIOD_TYPES:
            raise _bad(f"cost_period phải là một trong {PERIOD_TYPES} (bắt buộc; không quy đổi MONTH↔YEAR)")
        out.update(scope_type=st, scope_value=sv, cost_period=per)
    for k in ("evidence_date", "quote_valid_until", "effective_from", "effective_to"):
        v = pick(k)
        out[k] = rm._date(v, k) if v else None
    if out["effective_to"] is not None and (out["effective_from"] is None or out["effective_to"] < out["effective_from"]):
        raise _bad("effective_to phải >= effective_from (và cần effective_from)")
    return out


def _completeness_errors(e: RoadmapCostEvidence) -> list[str]:
    errs = []
    if not e.source_ref:
        errs.append("source_ref")
    if e.evidence_date is None:
        errs.append("evidence_date")
    if e.effective_from is None:
        errs.append("effective_from")
    if not e.source_kind:
        errs.append("source_kind")
    if e.cost_family == "MACHINE_UNIT_PRICE":
        if not e.machine_type_code:
            errs.append("machine_type_code")
        if not e.price_basis:
            errs.append("price_basis")
    else:
        if not e.scope_type:
            errs.append("scope")
        if not e.cost_period:
            errs.append("cost_period")
    if e.source_kind == "SUPPLIER_QUOTATION":
        if not e.vendor:
            errs.append("vendor (SUPPLIER_QUOTATION)")
        if e.quote_valid_until is None:
            errs.append("quote_valid_until (SUPPLIER_QUOTATION)")
    return errs


# ------------------------------------------------------------------ CRUD / workflow
def create_evidence(db: Session, user: User, d: dict) -> RoadmapCostEvidence:
    code = (d.get("evidence_code") or "").strip().upper()
    if not code:
        raise _bad("Cần evidence_code")
    if db.query(RoadmapCostEvidence.id).filter_by(evidence_code=code).first():
        raise _bad(f"evidence_code '{code}' đã tồn tại — dùng 'new-version'", 409)
    e = RoadmapCostEvidence(evidence_code=code[:40], evidence_version=1, status="DRAFT", created_by=user.username, **_validate(db, d, None))
    db.add(e)
    db.flush()
    rm._hist(db, "COST_EVID", e.id, None, "DRAFT", "created", user.username)
    db.commit()
    write_audit("ROADMAP_COST_EVIDENCE_CREATE", user=user, object_type="RoadmapCostEvidence", object_id=f"{e.evidence_code} v{e.evidence_version}", detail=e.cost_family)
    return e


def update_evidence(db: Session, user: User, evidence_id: int, d: dict) -> RoadmapCostEvidence:
    e = get_evidence(db, evidence_id)
    if e.status != "DRAFT":
        raise _bad(f"Evidence {e.status} bất biến — chỉ sửa DRAFT; sửa = version mới", 409)
    if any(k in d for k in ("evidence_code", "evidence_version", "status", "reviewed_by", "approved_by")):
        raise _bad("evidence_code/version/status/reviewer/approver không sửa trực tiếp")
    for k, v in _validate(db, d, e).items():
        setattr(e, k, v)
    db.commit()
    return e


def new_version(db: Session, user: User, evidence_id: int) -> RoadmapCostEvidence:
    src = get_evidence(db, evidence_id)
    latest = db.query(RoadmapCostEvidence).filter_by(evidence_code=src.evidence_code).order_by(RoadmapCostEvidence.evidence_version.desc()).first()
    if latest.status in ("DRAFT", "UNDER_REVIEW"):
        raise _bad(f"Đã có version {latest.status} (v{latest.evidence_version}) — xử lý version đó trước", 409)
    e = RoadmapCostEvidence(
        evidence_code=src.evidence_code, evidence_version=latest.evidence_version + 1, cost_family=src.cost_family, machine_type_code=src.machine_type_code, machine_model_id=src.machine_model_id,
        future_candidate_id=src.future_candidate_id, scope_type=src.scope_type, scope_value=src.scope_value, cost_period=src.cost_period, amount=src.amount, currency=src.currency,
        price_basis=src.price_basis, vendor=src.vendor, source_kind=src.source_kind, source_ref=src.source_ref, evidence_date=src.evidence_date, quote_valid_until=src.quote_valid_until,
        effective_from=src.effective_from, effective_to=src.effective_to, note=src.note, status="DRAFT", created_by=user.username)
    db.add(e)
    db.flush()
    rm._hist(db, "COST_EVID", e.id, None, "DRAFT", f"new version of v{src.evidence_version}", user.username)
    db.commit()
    return e


def submit_review(db: Session, user: User, evidence_id: int) -> RoadmapCostEvidence:
    e = get_evidence(db, evidence_id)
    if e.status != "DRAFT":
        raise _bad(f"Chỉ chuyển UNDER_REVIEW từ DRAFT (hiện {e.status})", 409)
    errs = _completeness_errors(e)
    if errs:
        raise _bad("Chưa đủ điều kiện đưa vào review — thiếu: " + ", ".join(errs))
    e.status, e.reviewed_by, e.reviewed_at = "UNDER_REVIEW", user.username, utcnow()
    rm._hist(db, "COST_EVID", e.id, "DRAFT", "UNDER_REVIEW", "", user.username)
    db.commit()
    write_audit("ROADMAP_COST_EVIDENCE_REVIEW", user=user, object_type="RoadmapCostEvidence", object_id=f"{e.evidence_code} v{e.evidence_version}", detail=e.cost_family)
    return e


def approve_evidence(db: Session, user: User, evidence_id: int) -> RoadmapCostEvidence:
    """Quyền `roadmap.approve` do API kiểm."""
    e = get_evidence(db, evidence_id)
    if e.status != "UNDER_REVIEW":
        raise _bad(f"Chỉ duyệt được evidence UNDER_REVIEW (hiện {e.status})", 409)
    if not e.reviewed_by or e.reviewed_by == user.username:
        raise _bad("Four-eyes: người duyệt (approver) phải khác người đã đưa vào review (reviewer)", 409)
    kind = (e.source_kind or "").upper()
    if kind in COST_BLOCKED_SOURCE_KINDS or kind not in COST_APPROVABLE_SOURCE_KINDS[e.cost_family]:
        raise _bad(f"source_kind '{e.source_kind}' không được APPROVE cho {e.cost_family} — chỉ chấp nhận {COST_APPROVABLE_SOURCE_KINDS[e.cost_family]}", 409)
    errs = _completeness_errors(e)
    if errs:
        raise _bad("Chưa đủ điều kiện APPROVE — thiếu: " + ", ".join(errs), 409)
    e.status, e.approved_by, e.approved_at = "APPROVED", user.username, utcnow()
    rm._hist(db, "COST_EVID", e.id, "UNDER_REVIEW", "APPROVED", "", user.username)
    db.commit()
    write_audit("ROADMAP_COST_EVIDENCE_APPROVE", user=user, object_type="RoadmapCostEvidence", object_id=f"{e.evidence_code} v{e.evidence_version}", detail=e.cost_family)
    return e


def retire_evidence(db: Session, user: User, evidence_id: int, reason: str = "") -> RoadmapCostEvidence:
    e = get_evidence(db, evidence_id)
    if e.status != "APPROVED":
        raise _bad(f"Chỉ retire được evidence APPROVED (hiện {e.status})", 409)
    if not (reason or "").strip():
        raise _bad("Retire evidence bắt buộc có reason")
    e.status, e.retire_reason = "RETIRED", reason.strip()[:300]
    rm._hist(db, "COST_EVID", e.id, "APPROVED", "RETIRED", reason.strip(), user.username)
    db.commit()
    write_audit("ROADMAP_COST_EVIDENCE_RETIRE", user=user, object_type="RoadmapCostEvidence", object_id=f"{e.evidence_code} v{e.evidence_version}", detail=reason[:150])
    return e


# ------------------------------------------------------------------ asset refs (chỉ tham chiếu)
def asset_view(a: RoadmapAssetRef) -> dict:
    return {"id": a.id, "subject_type": a.subject_type, "subject_ref": a.subject_ref, "asset_kind": a.asset_kind, "uri": a.uri, "asset_ref": a.asset_ref, "source_ref": a.source_ref,
            "note": a.note, "active": a.active, "created_by": a.created_by, "created_at": _iso(a.created_at)}


def list_assets(db: Session, subject_type: str = "", subject_ref: str = "", active_only: bool = False) -> list[RoadmapAssetRef]:
    q = db.query(RoadmapAssetRef)
    if subject_type:
        q = q.filter(RoadmapAssetRef.subject_type == subject_type)
    if subject_ref:
        q = q.filter(RoadmapAssetRef.subject_ref == subject_ref)
    if active_only:
        q = q.filter(RoadmapAssetRef.active.is_(True))
    return q.order_by(RoadmapAssetRef.id).all()


def create_asset(db: Session, user: User, d: dict) -> RoadmapAssetRef:
    st, kind = d.get("subject_type"), d.get("asset_kind")
    if st not in ASSET_SUBJECT_TYPES:
        raise _bad(f"subject_type phải là một trong {ASSET_SUBJECT_TYPES}")
    if kind not in ASSET_KINDS:
        raise _bad(f"asset_kind phải là một trong {ASSET_KINDS}")
    ref = str(d.get("subject_ref") or "").strip()
    ok = (st == "MACHINE_TYPE" and db.get(MachineType, ref) is not None) or (st == "MACHINE_MODEL" and ref.isdigit() and db.get(MachineModel, int(ref)) is not None) or (
        st == "FUTURE_CANDIDATE" and ref.isdigit() and db.get(FutureTechnologyCandidate, int(ref)) is not None)
    if not ok:
        raise _bad("subject_ref không tồn tại")
    uri, aref = (d.get("uri") or "").strip(), (d.get("asset_ref") or "").strip()
    if bool(uri) == bool(aref):
        raise _bad("Cần đúng một trong uri (https://) hoặc asset_ref (opaque/internal)")
    if uri and not HTTPS_RE.match(uri):
        raise _bad("uri chỉ chấp nhận https:// (không javascript:/data:/file:/http:)")
    if aref and (aref.lower().startswith(BAD_SCHEMES) or not OPAQUE_RE.match(aref)):
        raise _bad("asset_ref không hợp lệ (opaque/internal, không scheme nguy hiểm)")
    a = RoadmapAssetRef(subject_type=st, subject_ref=ref, asset_kind=kind, uri=uri, asset_ref=aref, source_ref=(d.get("source_ref") or "").strip()[:300],
                        note=(d.get("note") or "").strip()[:300], active=True, created_by=user.username)
    db.add(a)
    db.commit()
    write_audit("ROADMAP_ASSET_REF_CREATE", user=user, object_type="RoadmapAssetRef", object_id=str(a.id), detail=f"{st}:{ref} {kind}")
    return a


def set_asset_active(db: Session, user: User, asset_id: int, active: bool) -> RoadmapAssetRef:
    a = db.get(RoadmapAssetRef, asset_id)
    if a is None:
        raise HTTPException(404, "Không tìm thấy asset ref")
    a.active = bool(active)
    db.commit()
    return a


def today() -> date:
    return utcnow().date()
