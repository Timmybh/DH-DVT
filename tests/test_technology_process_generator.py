"""Task 3 (Issue #7) — Optimized Current Technology Proposal Generator. Test service layer với SQLite in-memory,
không cần dữ liệu ERP/production thật (production hiện có 0 Current Process — xem khảo sát Issue #7)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.permissions import permissions_for
from app.db.session import Base
from app.models.resources import MachineModel, MachineType
from app.models.tech_compatibility import OperationMachineCompatibility
from app.models.technology_process import TechnologyProcess, TechnologyProcessOperation, TechnologyProcessVersion
from app.services import technology_process_generator as gen
from app.services import technology_process_service as tps

ADMIN = SimpleNamespace(username="admin", role="ADMIN", id=1)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            MachineType.__table__, MachineModel.__table__, TechnologyProcess.__table__, TechnologyProcessVersion.__table__,
            TechnologyProcessOperation.__table__, OperationMachineCompatibility.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    events: list[str] = []
    monkeypatch.setattr(tps, "write_audit", lambda action, **kw: events.append(action))
    monkeypatch.setattr(gen, "write_audit", lambda action, **kw: events.append(action))
    s.audit = events  # type: ignore[attr-defined]
    s.add(MachineType(code="1K", name="1 kim", status="ACTIVE"))
    s.add(MachineType(code="2K", name="2 kim", status="ACTIVE"))
    s.commit()
    yield s
    s.close()


def _current_process(db, style="TEST100", ops=None):
    """Tạo 1 TechnologyProcess + 1 CURRENT_PROCESS version DRAFT với các operation cho trước."""
    p = tps.create_process(db, ADMIN, {"style_cc": style, "model_code": ""})
    v = tps.create_draft_version(db, ADMIN, p.id, {"layer": "CURRENT_PROCESS"})
    for o in ops or []:
        tps.add_operation(db, ADMIN, v.id, o)
    db.refresh(v)
    return p, v


def _compat(db, operation_code="OP1", candidate_type="2K", model_id=None, status="APPROVED", source_type="1K"):
    row = OperationMachineCompatibility(
        operation_code=operation_code, source_machine_type_code=source_type, candidate_machine_type_code=candidate_type,
        candidate_machine_model_id=model_id, compatibility_status=status, created_by="admin",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ------------------------------------------------------------------ V-301/V-302 — source phải CURRENT_PROCESS, target đúng layer
def test_generate_rejects_non_current_process_source(db):
    p, v = _current_process(db, "S1")
    v_opt = tps.derive_version(db, ADMIN, v.id, "OPTIMIZED_CURRENT_TECHNOLOGY")
    with pytest.raises(HTTPException) as e:
        gen.generate_optimized_proposal(db, ADMIN, v_opt.id)  # nguồn không phải CURRENT_PROCESS
    assert e.value.status_code == 422


def test_generate_target_layer_is_optimized_current_technology(db):
    p, v = _current_process(db, "S2", [{"operation_name": "Vắt sổ", "operation_code": "OP1"}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r["version"]["layer"] == "OPTIMIZED_CURRENT_TECHNOLOGY"


# ------------------------------------------------------------------ BR-301 — lineage
def test_generated_version_has_lineage_to_source(db):
    p, v = _current_process(db, "S3", [{"operation_name": "May cổ", "operation_code": "OP1"}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r["version"]["derived_from_version_id"] == v.id


# ------------------------------------------------------------------ V-303/BR-302 — chỉ DRAFT, không auto REVIEWED/APPROVED
def test_generated_version_status_is_draft_only(db):
    p, v = _current_process(db, "S4", [{"operation_name": "May cổ", "operation_code": "OP1"}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r["version"]["status"] == "DRAFT"


# ------------------------------------------------------------------ AC-302/303 — không candidate thì giữ nguyên (UNCHANGED)
def test_no_candidate_keeps_operation_unchanged(db):
    p, v = _current_process(db, "S5", [{"operation_name": "May cổ", "operation_code": "OP-NOMATCH"}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    op = r["version"]["operations"][0]
    assert op["change_type"] == "UNCHANGED"
    assert op["machine_type_code"] is None  # không suy đoán/tự set


# ------------------------------------------------------------------ AC-302 — substitution hợp lệ khi đúng 1 candidate đủ điều kiện
def test_single_eligible_candidate_auto_substitutes(db):
    _compat(db, "OP1", candidate_type="2K", status="APPROVED")
    p, v = _current_process(db, "S6", [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K", "sam_minutes": 1.5}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    op = r["version"]["operations"][0]
    assert op["change_type"] == "MACHINE_SUBSTITUTION"
    assert op["machine_type_code"] == "2K"
    assert op["sam_minutes"] == 1.5  # BR-312 — KHÔNG tự đổi SAM chỉ vì thay máy, giữ nguyên copy từ source


# ------------------------------------------------------------------ AC-304/BR-312 — substitution không tự giảm SAM/output/labor
def test_substitution_does_not_invent_sam_when_source_missing(db):
    _compat(db, "OP1", candidate_type="2K", status="APPROVED")
    p, v = _current_process(db, "S7", [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}])  # không có sam_minutes
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    op = r["version"]["operations"][0]
    assert op["sam_minutes"] is None
    assert r["version"]["sam_status"] == "INCOMPLETE"  # AC-305 — thiếu SAM nguồn, KHÔNG tự bịa Total SAM


# ------------------------------------------------------------------ GPT review khảo sát mục 2 — nhiều candidate ngang nhau -> không tự chọn
def test_multiple_eligible_candidates_not_auto_selected_unless_user_chooses(db):
    c1 = _compat(db, "OP1", candidate_type="2K", status="APPROVED")
    _compat(db, "OP1", candidate_type="1K", status="APPROVED", source_type="1K")  # 2K + 1K đều APPROVED, cùng khớp OP1/nguồn 1K
    # thêm 1 loại máy thứ 3 để phân biệt rõ 2 candidate khác nhau
    db.add(MachineType(code="3K", name="3 kim", status="ACTIVE"))
    db.commit()
    c1.candidate_machine_type_code = "2K"
    row3 = _compat(db, "OP1", candidate_type="3K", status="APPROVED", source_type="1K")
    p, v = _current_process(db, "S8", [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}])

    preview = gen.preview_optimized_proposal(db, v.id)
    assert preview["operations"][0]["decision"] == "MULTIPLE_CANDIDATES"

    r_auto = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r_auto["version"]["operations"][0]["change_type"] == "UNCHANGED"  # không tự chọn

    r_chosen = gen.generate_optimized_proposal(db, ADMIN, v.id, selections={"1": row3.id})
    assert r_chosen["version"]["operations"][0]["machine_type_code"] == "3K"  # user chọn tường minh mới áp dụng


# ------------------------------------------------------------------ GPT review mục 3 — CANDIDATE status không auto-apply, user chọn thì đánh dấu unverified
def test_candidate_status_model_not_auto_applied_but_user_can_select_with_unverified_note(db):
    mm = MachineModel(machine_type_code="2K", brand="X", model="Y", status="CANDIDATE", created_by="admin")
    db.add(mm)
    db.commit()
    db.refresh(mm)
    row = _compat(db, "OP1", candidate_type="2K", model_id=mm.id, status="APPROVED")  # compatibility APPROVED nhưng MachineModel còn CANDIDATE
    p, v = _current_process(db, "S9", [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}])

    preview = gen.preview_optimized_proposal(db, v.id)
    assert preview["operations"][0]["decision"] == "UNVERIFIED_CANDIDATE_AVAILABLE"

    r_auto = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r_auto["version"]["operations"][0]["change_type"] == "UNCHANGED"  # không tự áp MachineModel CANDIDATE

    r_chosen = gen.generate_optimized_proposal(db, ADMIN, v.id, selections={"1": row.id})
    op = r_chosen["version"]["operations"][0]
    assert op["change_type"] == "MACHINE_SUBSTITUTION" and "USER_SELECTED_UNVERIFIED_CANDIDATE" in op["evidence_note"]
    assert r_chosen["version"]["status"] == "DRAFT"  # vẫn chỉ DRAFT, không tự SIMULATED


# ------------------------------------------------------------------ mục 9 — MAN/unmapped operation_code luôn UNCHANGED, không tra cứu
def test_operation_without_machine_or_operation_code_always_unchanged(db):
    _compat(db, "", candidate_type="2K", status="APPROVED")  # mapping rỗng operation_code (không hợp lệ, phòng hờ)
    p, v = _current_process(db, "S10", [
        {"operation_name": "Thao tác tay", "operation_code": "", "machine_type_code": None},
        {"operation_name": "May", "operation_code": "OP-X", "machine_type_code": None},  # có operation_code nhưng không có máy (MAN)
    ])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert all(o["change_type"] == "UNCHANGED" for o in r["version"]["operations"])


# ------------------------------------------------------------------ AC-309/V-308 — idempotent theo generation_fingerprint
def test_same_snapshot_twice_is_no_op_no_duplicate_version(db):
    p, v = _current_process(db, "S11", [{"operation_name": "May cổ", "operation_code": "OP1"}])
    r1 = gen.generate_optimized_proposal(db, ADMIN, v.id)
    r2 = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r1["created"] is True and r2["created"] is False
    assert r1["version"]["id"] == r2["version"]["id"]
    assert db.query(TechnologyProcessVersion).filter_by(layer="OPTIMIZED_CURRENT_TECHNOLOGY").count() == 1


# ------------------------------------------------------------------ BR-317 — source đổi hoặc mapping đổi -> proposal mới, giữ bản cũ
def test_source_change_creates_new_proposal_keeps_old(db):
    p, v = _current_process(db, "S12", [{"operation_name": "May cổ", "operation_code": "OP1"}])
    r1 = gen.generate_optimized_proposal(db, ADMIN, v.id)
    tps.add_operation(db, ADMIN, v.id, {"operation_name": "Thêm công đoạn", "operation_code": "OP2"})
    db.refresh(v)
    r2 = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r2["created"] is True and r2["version"]["id"] != r1["version"]["id"]
    assert db.query(TechnologyProcessVersion).filter_by(layer="OPTIMIZED_CURRENT_TECHNOLOGY").count() == 2  # AC-310 — nhiều proposal


def test_compatibility_mapping_change_creates_new_proposal(db):
    p, v = _current_process(db, "S13", [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}])
    r1 = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r1["version"]["operations"][0]["change_type"] == "UNCHANGED"
    _compat(db, "OP1", candidate_type="2K", status="APPROVED")  # mapping mới xuất hiện sau
    r2 = gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert r2["created"] is True and r2["version"]["operations"][0]["change_type"] == "MACHINE_SUBSTITUTION"


# ------------------------------------------------------------------ V-304/V-305 — candidate id không hợp lệ bị từ chối
def test_invalid_candidate_selection_rejected(db):
    p, v = _current_process(db, "S14", [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}])
    with pytest.raises(HTTPException) as e:
        gen.generate_optimized_proposal(db, ADMIN, v.id, selections={"1": 9999})
    assert e.value.status_code == 422


# ------------------------------------------------------------------ Compare (AC-307)
def test_compare_current_vs_optimized_shows_counts_and_na_for_missing_metrics(db):
    _compat(db, "OP1", candidate_type="2K", status="APPROVED")
    p, v = _current_process(db, "S15", [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}, {"operation_name": "Ủi", "operation_code": "OP2"}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    cmp = gen.compare_current_vs_optimized(db, v.id, r["version"]["id"])
    assert cmp["machine_substitution_count"] == 1
    assert cmp["operation_changed_count"] == 1
    assert cmp["total_sam_minutes"]["a"] is None and cmp["total_sam_minutes"]["b"] is None  # N/A — không tự bịa


def test_compare_rejects_versions_from_different_process(db):
    p1, v1 = _current_process(db, "S16A", [{"operation_name": "X", "operation_code": "OP1"}])
    p2, v2 = _current_process(db, "S16B", [{"operation_name": "Y", "operation_code": "OP1"}])
    with pytest.raises(HTTPException) as e:
        gen.compare_current_vs_optimized(db, v1.id, v2.id)
    assert e.value.status_code == 422


def test_compare_with_source_resolves_lineage_automatically(db):
    """Bug thật phát hiện lúc live smoke test UI: endpoint bare /versions/compare-... bị route /versions/{id} của
    router khác bắt trước (422). compare_with_source() chỉ cần id của bản Optimized, tự suy ra Current qua lineage."""
    p, v = _current_process(db, "S16C", [{"operation_name": "X", "operation_code": "OP1"}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    cmp = gen.compare_with_source(db, r["version"]["id"])
    assert cmp["version_a"]["id"] == v.id and cmp["version_b"]["id"] == r["version"]["id"]


def test_compare_with_source_rejects_version_without_lineage(db):
    p, v = _current_process(db, "S16D", [{"operation_name": "X", "operation_code": "OP1"}])
    with pytest.raises(HTTPException) as e:
        gen.compare_with_source(db, v.id)  # CURRENT_PROCESS gốc không có derived_from_version_id
    assert e.value.status_code == 422


# ------------------------------------------------------------------ Approved immutable (V-307, kế thừa workflow Task 1)
def test_approved_optimized_version_immutable(db):
    p, v = _current_process(db, "S17", [{"operation_name": "May cổ", "operation_code": "OP1"}])
    r = gen.generate_optimized_proposal(db, ADMIN, v.id)
    v_opt_id = r["version"]["id"]
    tps.transition_version(db, ADMIN, v_opt_id, "review")
    tps.transition_version(db, ADMIN, v_opt_id, "approve")
    with pytest.raises(HTTPException) as e:
        tps.update_operation(db, ADMIN, r["version"]["operations"][0]["id"], {"operation_name": "sửa sau approve"})
    assert e.value.status_code == 409


# ------------------------------------------------------------------ Compatibility CRUD quản trị (BR-309)
def test_save_compatibility_requires_operation_code_and_valid_machine_type(db):
    with pytest.raises(HTTPException):
        gen.save_compatibility(db, ADMIN, {"candidate_machine_type_code": "2K"})  # thiếu operation_code
    with pytest.raises(HTTPException):
        gen.save_compatibility(db, ADMIN, {"operation_code": "OP1", "candidate_machine_type_code": "NOPE"})
    row = gen.save_compatibility(db, ADMIN, {"operation_code": "OP1", "candidate_machine_type_code": "2K"})
    assert row.compatibility_status == "PROPOSED"  # mặc định, không tự APPROVED


# ------------------------------------------------------------------ Audit
def test_generate_and_compatibility_save_are_audited(db):
    p, v = _current_process(db, "S18", [{"operation_name": "May cổ", "operation_code": "OP1"}])
    gen.generate_optimized_proposal(db, ADMIN, v.id)
    assert "TECH_PROCESS_OPTIMIZED_GENERATE" in db.audit  # type: ignore[attr-defined]
    gen.save_compatibility(db, ADMIN, {"operation_code": "OP1", "candidate_machine_type_code": "2K"})
    assert "TECH_PROCESS_COMPATIBILITY_SAVE" in db.audit  # type: ignore[attr-defined]


# ------------------------------------------------------------------ Permission (mục 13 Issue #7 — reuse, không permission mới)
def test_permission_mapping_reuses_technology_process_permissions():
    assert "technology_process.manage" in permissions_for("ADMIN") and "technology_process.view" in permissions_for("ADMIN")
    assert "technology_process.manage" not in permissions_for("PLANNER")
    assert "technology_process.manage" not in permissions_for("VIEWER")
