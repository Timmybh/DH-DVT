"""CEO Roadmap Phase 1 (ROADMAP_APPROVED_WIREFRAME_SPEC.md, GPT APPROVED_TO_IMPLEMENT 2026-09-28).

Lớp trình bày business-facing, dùng chung khung RoadmapScenario/Version/Milestone (Task 5) làm timeline. KHÔNG đụng vào
Run/Proposal/ActionPlan/CostEvidence immutable — các bảng đó tiếp tục phục vụ mô phỏng đầu tư kỹ thuật như trước.
Thêm ở đây: RoadmapCategory (Admin CRUD), enrich milestone (category/progress/baseline/gap/proposal/status/warning),
RoadmapMilestoneAction (checklist ACTION | MILESTONE_LINK). Đúng 3 layout (Horizontal/3D/Vertical) dùng chung 1 data
contract (đọc từ `ceo_view`) — không tách data model theo layout.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import AuditLog
from app.models.roadmap import (
    CEO_CATEGORY_SEED,
    MILESTONE_ACTION_STATUSES,
    MILESTONE_ACTION_TYPES,
    MILESTONE_ACTION_VALUE_TYPES,
    MILESTONE_MANUAL_STATUSES,
    RoadmapCategory,
    RoadmapMilestone,
    RoadmapMilestoneAction,
    RoadmapScenarioVersion,
)
from app.services.audit import write_audit


def _bad(msg: str, code: int = 422) -> HTTPException:
    return HTTPException(code, msg)


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


# ================================================================== Category (Admin CRUD)
def ensure_default_categories(db: Session, actor: str = "system") -> None:
    """Seed 5 category mặc định nếu bảng rỗng — idempotent, không seed lại nếu Admin đã tự sửa/xoá."""
    if db.query(RoadmapCategory.id).first() is not None:
        return
    for i, name in enumerate(CEO_CATEGORY_SEED):
        db.add(RoadmapCategory(code=name, name=name, sort_order=i, created_by=actor))
    db.commit()


def category_view(c: RoadmapCategory) -> dict:
    return {
        "id": c.id, "code": c.code, "name": c.name, "color": c.color, "sort_order": c.sort_order, "active": c.active,
        "created_by": c.created_by, "created_at": _iso(c.created_at), "updated_by": c.updated_by, "updated_at": _iso(c.updated_at),
    }


def list_categories(db: Session, include_inactive: bool = True) -> list[dict]:
    q = db.query(RoadmapCategory)
    if not include_inactive:
        q = q.filter(RoadmapCategory.active.is_(True))
    return [category_view(c) for c in q.order_by(RoadmapCategory.sort_order, RoadmapCategory.id).all()]


def create_category(db: Session, code: str, name: str, color: str, sort_order: int, actor: str) -> dict:
    code = (code or "").strip()
    name = (name or "").strip() or code
    if not code:
        raise _bad("code không được rỗng")
    if db.query(RoadmapCategory.id).filter(RoadmapCategory.code == code).first() is not None:
        raise _bad(f"Category '{code}' đã tồn tại")
    c = RoadmapCategory(code=code, name=name, color=color or "#2563eb", sort_order=sort_order or 0, created_by=actor)
    db.add(c)
    db.commit()
    db.refresh(c)
    return category_view(c)


def update_category(db: Session, category_id: int, name: str | None, color: str | None, sort_order: int | None, active: bool | None, actor: str) -> dict:
    c = db.get(RoadmapCategory, category_id)
    if c is None:
        raise HTTPException(404, "Không tìm thấy category")
    if name is not None:
        c.name = name.strip() or c.name
    if color is not None:
        c.color = color
    if sort_order is not None:
        c.sort_order = sort_order
    if active is not None:
        c.active = active
    c.updated_by = actor
    c.updated_at = utcnow()
    db.commit()
    db.refresh(c)
    return category_view(c)


# ================================================================== Milestone enrich (category/progress/status/warning)
def _derived_status(m: RoadmapMilestone) -> str:
    if m.manual_status in MILESTONE_MANUAL_STATUSES:
        return m.manual_status
    if m.progress_percent is None:
        return "AT_RISK"
    if m.progress_percent >= 90:
        return "ON_TRACK"
    if m.progress_percent >= 50:
        return "AT_RISK"
    return "BEHIND"


def update_milestone_ceo_fields(
    db: Session, milestone_id: int, *, category_code: str | None = None, progress_percent: float | None = None,
    baseline_label: str | None = None, gap_label: str | None = None, proposal_summary: str | None = None,
    manual_status: str | None = None, warning_note: str | None = None, actor: str = "",
) -> RoadmapMilestone:
    m = db.get(RoadmapMilestone, milestone_id)
    if m is None:
        raise HTTPException(404, "Không tìm thấy milestone")
    if category_code is not None:
        if category_code and db.query(RoadmapCategory.id).filter(RoadmapCategory.code == category_code).first() is None:
            raise _bad(f"Category '{category_code}' không tồn tại")
        m.category_code = category_code or None
    if progress_percent is not None:
        if not (0 <= progress_percent <= 100):
            raise _bad("progress_percent phải trong khoảng 0..100")
        m.progress_percent = progress_percent
    if baseline_label is not None:
        m.baseline_label = baseline_label
    if gap_label is not None:
        m.gap_label = gap_label
    if proposal_summary is not None:
        m.proposal_summary = proposal_summary
    if manual_status is not None:
        if manual_status and manual_status not in MILESTONE_MANUAL_STATUSES:
            raise _bad(f"manual_status phải là một trong {MILESTONE_MANUAL_STATUSES}")
        m.manual_status = manual_status or None
    if warning_note is not None:
        m.warning_note = warning_note
    db.commit()
    db.refresh(m)
    write_audit("ROADMAP_CEO_MILESTONE_UPDATE", username=actor, object_type="RoadmapMilestone", object_id=str(m.id), detail=f"{m.code}")
    return m


def milestone_ceo_card(m: RoadmapMilestone, category_by_code: dict[str, RoadmapCategory]) -> dict:
    cat = category_by_code.get(m.category_code) if m.category_code else None
    return {
        "id": m.id, "code": m.code, "name": m.name, "target_date": _iso(m.target_date), "sequence": m.sequence,
        "category_code": m.category_code, "category_name": cat.name if cat else "", "category_color": cat.color if cat else "#94a3b8",
        "progress_percent": m.progress_percent, "status": _derived_status(m),
        "baseline_label": m.baseline_label, "gap_label": m.gap_label, "proposal_summary": m.proposal_summary,
        "has_warning": bool(m.warning_note), "warning_note": m.warning_note,
    }


def ceo_view(db: Session, version_id: int) -> dict:
    """Data contract dùng chung cho cả 3 layout (Horizontal/3D/Vertical) — WF-01/01B/01C."""
    v = db.get(RoadmapScenarioVersion, version_id)
    if v is None:
        raise HTTPException(404, "Không tìm thấy version")
    milestones = db.query(RoadmapMilestone).filter(RoadmapMilestone.version_id == version_id).order_by(RoadmapMilestone.sequence).all()
    categories = {c.code: c for c in db.query(RoadmapCategory).all()}
    cards = [milestone_ceo_card(m, categories) for m in milestones]

    # "Mục tiêu tổng" cuối trình: gộp category trùng nhau (đã chốt review trước khi code) — trung bình progress theo category
    by_cat: dict[str, list[dict]] = {}
    for card in cards:
        if card["category_code"]:
            by_cat.setdefault(card["category_code"], []).append(card)
    summary = []
    for code, items in by_cat.items():
        vals = [it["progress_percent"] for it in items if it["progress_percent"] is not None]
        avg = sum(vals) / len(vals) if vals else None
        summary.append({
            "category_code": code, "category_name": items[0]["category_name"], "category_color": items[0]["category_color"],
            "milestone_count": len(items), "avg_progress_percent": avg,
        })
    summary.sort(key=lambda s: categories[s["category_code"]].sort_order if s["category_code"] in categories else 0)

    return {
        "version_id": v.id, "scenario_id": v.scenario_id, "version_no": v.version_no, "version_status": v.status,
        "milestones": cards, "summary": summary,
    }


def delete_milestone_ceo_ref_check(db: Session, milestone_id: int) -> None:
    """Chặn xoá milestone đang được MILESTONE_LINK của milestone khác tham chiếu tới (tránh đứt link âm thầm — WF-02)."""
    refs = db.query(RoadmapMilestoneAction.id).filter(RoadmapMilestoneAction.ref_milestone_id == milestone_id).first()
    if refs is not None:
        raise _bad("Milestone đang được dùng làm điều kiện (MILESTONE_LINK) ở milestone khác — gỡ liên kết trước khi xoá", 409)


def list_dependents(db: Session, milestone_id: int) -> list[dict]:
    """WF-03 tab "Phụ thuộc/liên kết" chiều đi: milestone nào đang dùng milestone này làm điều kiện (MILESTONE_LINK)."""
    rows = (
        db.query(RoadmapMilestoneAction, RoadmapMilestone)
        .join(RoadmapMilestone, RoadmapMilestoneAction.milestone_id == RoadmapMilestone.id)
        .filter(RoadmapMilestoneAction.ref_milestone_id == milestone_id)
        .order_by(RoadmapMilestone.target_date)
        .all()
    )
    return [{"action_id": a.id, "milestone_id": m.id, "milestone_code": m.code, "milestone_name": m.name, "milestone_date": _iso(m.target_date), "status": a.status} for a, m in rows]


# ================================================================== Data Sources (WF-06) — nối THẬT vào sync hiện có, không bịa nguồn
def list_data_sources(db: Session) -> list[dict]:
    """Business-facing sync/mapping status — chỉ hiển thị nguồn THẬT sự tồn tại trong hệ thống (EGMF_REVENUE, ERP_QTCN,
    PLAN_EXCEL). Máy móc hiện nhập thủ công (MACHINE_SYNC_ENABLED=False — ERP chưa có dữ liệu chuẩn). Finance/OPEX và HR
    CHƯA có pipeline đồng bộ nào trong hệ thống — báo trung thực "Chưa tích hợp", không dựng số liệu giả."""
    from app.services import egmf_ops as eo
    from app.services import roadmap_baseline as rb

    def row(name: str, data: str, cycle: str, source_job: str | None) -> dict:
        if source_job is None:
            return {"source": name, "data": data, "cycle": cycle, "last_sync": None, "status": "NOT_INTEGRATED", "status_label": "Chưa tích hợp"}
        fresh = rb.source_freshness(db, source_job)
        last = fresh["last_attempt"]
        status = "STALE" if fresh["stale_or_last_sync_failed"] else "HEALTHY"
        return {
            "source": name, "data": data, "cycle": cycle, "last_sync": last["started_at"] if last else None,
            "last_status": last["status"] if last else None, "status": status, "status_label": "Cần chú ý (stale/failed)" if status == "STALE" else "Healthy",
        }

    return [
        row("eGMF / ERP", "Doanh thu / Sản lượng / QA (defect)", "Scheduled", rb.SOURCE_SYNC_JOB),
        row("ERP QTCN", "Yêu cầu máy theo mã hàng (Kế hoạch công nghệ)", "Manual/Scheduled", "ERP_QTCN"),
        row("Kế hoạch (Excel)", "Plan doanh thu nhập tay", "Manual", "PLAN_EXCEL"),
        {"source": "Machine/Equipment", "data": "Registry / trạng thái / số lượng", "cycle": "Thủ công",
         "last_sync": None, "status": "MANUAL" if not eo.MACHINE_SYNC_ENABLED else "HEALTHY",
         "status_label": "Nhập thủ công (ERP chưa có dữ liệu chuẩn)" if not eo.MACHINE_SYNC_ENABLED else "Healthy"},
        row("Finance/OPEX", "Chi phí vận hành", "—", None),
        row("HR", "Nhân sự", "—", None),
    ]


def list_milestone_history(db: Session, milestone_id: int) -> list[dict]:
    """WF-03 tab "Lịch sử" — đọc trực tiếp AuditLog chung của hệ thống (object_type=RoadmapMilestone), không tạo bảng audit riêng."""
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.object_type == "RoadmapMilestone", AuditLog.object_id == str(milestone_id))
        .order_by(AuditLog.at.desc())
        .limit(100)
        .all()
    )
    return [{"id": r.id, "action": r.action, "username": r.username, "detail": r.detail, "result": r.result, "at": _iso(r.at)} for r in rows]


# ================================================================== Milestone Action checklist (WF-03)
def action_view(a: RoadmapMilestoneAction, ref_by_id: dict[int, RoadmapMilestone]) -> dict:
    ref = ref_by_id.get(a.ref_milestone_id) if a.ref_milestone_id else None
    return {
        "id": a.id, "milestone_id": a.milestone_id, "action_type": a.action_type, "title": a.title,
        "ref_milestone_id": a.ref_milestone_id, "ref_milestone_code": ref.code if ref else "", "ref_milestone_date": _iso(ref.target_date) if ref else None,
        "value_type": a.value_type, "status": a.status, "note": a.note, "sort_order": a.sort_order,
    }


def list_actions(db: Session, milestone_id: int) -> list[dict]:
    rows = db.query(RoadmapMilestoneAction).filter(RoadmapMilestoneAction.milestone_id == milestone_id).order_by(RoadmapMilestoneAction.sort_order, RoadmapMilestoneAction.id).all()
    ref_ids = {r.ref_milestone_id for r in rows if r.ref_milestone_id}
    ref_by_id = {m.id: m for m in db.query(RoadmapMilestone).filter(RoadmapMilestone.id.in_(ref_ids)).all()} if ref_ids else {}
    return [action_view(a, ref_by_id) for a in rows]


def add_action(
    db: Session, milestone_id: int, *, action_type: str, title: str, ref_milestone_id: int | None, value_type: str,
    status: str, note: str, sort_order: int, actor: str,
) -> dict:
    m = db.get(RoadmapMilestone, milestone_id)
    if m is None:
        raise HTTPException(404, "Không tìm thấy milestone")
    if action_type not in MILESTONE_ACTION_TYPES:
        raise _bad(f"action_type phải là một trong {MILESTONE_ACTION_TYPES}")
    if value_type not in MILESTONE_ACTION_VALUE_TYPES:
        raise _bad(f"value_type phải là một trong {MILESTONE_ACTION_VALUE_TYPES}")
    if status not in MILESTONE_ACTION_STATUSES:
        raise _bad(f"status phải là một trong {MILESTONE_ACTION_STATUSES}")
    ref = None
    if action_type == "MILESTONE_LINK":
        if not ref_milestone_id:
            raise _bad("MILESTONE_LINK cần ref_milestone_id")
        ref = db.get(RoadmapMilestone, ref_milestone_id)
        if ref is None:
            raise HTTPException(404, "Không tìm thấy milestone tham chiếu")
        if ref.id == m.id:
            raise _bad("Không thể tự tham chiếu chính milestone này")
        # Ràng buộc thời gian đã chốt: chỉ ref milestone TRƯỚC ĐÓ, không cho ref milestone tương lai
        if ref.target_date >= m.target_date:
            raise _bad("Chỉ được tham chiếu tới milestone TRƯỚC ĐÓ (target_date sớm hơn), không cho ref milestone tương lai")
    else:
        ref_milestone_id = None
    a = RoadmapMilestoneAction(
        milestone_id=milestone_id, action_type=action_type, title=title or (ref.name if ref else ""), ref_milestone_id=ref_milestone_id,
        value_type=value_type, status=status, note=note or "", sort_order=sort_order or 0, created_by=actor,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    write_audit("ROADMAP_CEO_ACTION_ADD", username=actor, object_type="RoadmapMilestone", object_id=str(milestone_id), detail=f"{action_type} · {a.title}")
    ref_by_id = {ref.id: ref} if ref else {}
    return action_view(a, ref_by_id)


def update_action(
    db: Session, action_id: int, *, title: str | None, status: str | None, note: str | None, sort_order: int | None, actor: str,
) -> dict:
    a = db.get(RoadmapMilestoneAction, action_id)
    if a is None:
        raise HTTPException(404, "Không tìm thấy action")
    if title is not None:
        a.title = title
    if status is not None:
        if status not in MILESTONE_ACTION_STATUSES:
            raise _bad(f"status phải là một trong {MILESTONE_ACTION_STATUSES}")
        a.status = status
    if note is not None:
        a.note = note
    if sort_order is not None:
        a.sort_order = sort_order
    a.updated_by = actor
    a.updated_at = utcnow()
    db.commit()
    db.refresh(a)
    write_audit("ROADMAP_CEO_ACTION_UPDATE", username=actor, object_type="RoadmapMilestone", object_id=str(a.milestone_id), detail=f"#{a.id} {a.title}")
    ref_by_id = {}
    if a.ref_milestone_id:
        ref = db.get(RoadmapMilestone, a.ref_milestone_id)
        if ref:
            ref_by_id[ref.id] = ref
    return action_view(a, ref_by_id)


def remove_action(db: Session, action_id: int, actor: str = "") -> None:
    a = db.get(RoadmapMilestoneAction, action_id)
    if a is None:
        raise HTTPException(404, "Không tìm thấy action")
    milestone_id, title = a.milestone_id, a.title
    db.delete(a)
    db.commit()
    write_audit("ROADMAP_CEO_ACTION_REMOVE", username=actor, object_type="RoadmapMilestone", object_id=str(milestone_id), detail=title)
