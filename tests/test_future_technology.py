"""Task 4 (Issue #9) — Future Technology & Technology Scouting. Test service layer với SQLite in-memory; không cần dữ liệu thật
(production hiện có 0 MachineModel / 0 TechnologyProcess)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import future_technology as ft_api
from app.core.permissions import permissions_for
from app.db.session import Base
from app.models.future_technology import (
    FutureTechnologyCandidate,
    FutureTechnologyCompatibility,
    FutureTechnologyEvidence,
    FutureTechnologyStatusHistory,
)
from app.models.resources import MachineModel, MachineType
from app.models.tech_compatibility import OperationMachineCompatibility
from app.models.technology_process import TechnologyProcess, TechnologyProcessOperation, TechnologyProcessVersion
from app.services import future_technology as ft
from app.services import future_technology_generator as gen
from app.services import technology_process_generator as gen3
from app.services import technology_process_service as tps

ADMIN = SimpleNamespace(username="admin", role="ADMIN", id=1)
FUTURE = "FUTURE_TECHNOLOGY"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        MachineType.__table__, MachineModel.__table__, TechnologyProcess.__table__, TechnologyProcessVersion.__table__,
        TechnologyProcessOperation.__table__, OperationMachineCompatibility.__table__, FutureTechnologyCandidate.__table__,
        FutureTechnologyEvidence.__table__, FutureTechnologyCompatibility.__table__, FutureTechnologyStatusHistory.__table__,
    ])
    s = sessionmaker(bind=engine)()
    events: list[str] = []
    for mod in (tps, gen, ft, gen3):
        monkeypatch.setattr(mod, "write_audit", lambda action, **kw: events.append(action))
    s.audit = events  # type: ignore[attr-defined]
    for code in ("1K", "2K", "3K"):
        s.add(MachineType(code=code, name=code, status="ACTIVE"))
    s.commit()
    yield s
    s.close()


def _current(db, style="F100", ops=None):
    p = tps.create_process(db, ADMIN, {"style_cc": style, "model_code": ""})
    v = tps.create_draft_version(db, ADMIN, p.id, {"layer": "CURRENT_PROCESS"})
    for o in ops or [{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}]:
        tps.add_operation(db, ADMIN, v.id, o)
    db.refresh(v)
    return p, v


def _ev(db, c, source_ref="fixture brochure", **kw):
    return ft.add_evidence(db, ADMIN, c.id, {"source_ref": source_ref, "basis": "CLAIMED", "metric_code": "OTHER", **kw})


def _cand(db, status="APPROVED_FOR_FUTURE", mt="2K", model_id=None, automation="", brand="Acme", model_name="X1", evidence=True):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": mt, "machine_model_id": model_id, "brand": brand, "model_name": model_name, "automation_level": automation})
    if evidence:
        _ev(db, c)  # BR-401/403: candidate hợp lệ có ít nhất 1 evidence
    c.status = status  # đặt trực tiếp trạng thái fixture (transition được test riêng)
    db.commit()
    return c


def _fc(db, cand, op="OP1", src="1K", status="APPROVED"):
    return ft.save_compatibility(db, ADMIN, {"candidate_id": cand.id, "operation_code": op, "source_machine_type_code": src, "compatibility_status": status})


def _model(db, mt="2K", status="APPROVED"):
    m = MachineModel(machine_type_code=mt, brand="B", model="M", status=status, created_by="admin")
    db.add(m)
    db.commit()
    return m


# =================================================================== governance
def test_create_candidate_requires_existing_machine_type(db):
    with pytest.raises(HTTPException) as e:
        ft.create_candidate(db, ADMIN, {"brand": "X"})
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        ft.create_candidate(db, ADMIN, {"machine_type_code": "NOPE", "brand": "X"})
    assert e.value.status_code == 422


def test_create_candidate_model_type_integrity_and_identity(db):
    mm = _model(db, "1K")
    with pytest.raises(HTTPException) as e:
        ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "machine_model_id": mm.id, "brand": "X"})  # model thuộc 1K
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        ft.create_candidate(db, ADMIN, {"machine_type_code": "2K"})  # không có brand/model/technology_name nào
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    assert c.status == "DISCOVERED" and c.candidate_code == f"FTC-{c.id:06d}"
    hist = ft.list_history(db, c.id)
    assert len(hist) == 1 and hist[0].from_status is None and hist[0].to_status == "DISCOVERED"


def test_transition_valid_path_writes_history_and_audit_fields(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    _ev(db, c)
    ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW")
    ft.transition_candidate(db, ADMIN, c.id, "TRIAL")
    ft.transition_candidate(db, ADMIN, c.id, "APPROVED_FOR_FUTURE")
    db.refresh(c)
    assert c.status == "APPROVED_FOR_FUTURE" and c.approved_by == "admin" and c.reviewed_by == "admin"
    assert [h.to_status for h in ft.list_history(db, c.id)] == ["DISCOVERED", "UNDER_REVIEW", "TRIAL", "APPROVED_FOR_FUTURE"]
    assert "FUTURE_CANDIDATE_TRANSITION" in db.audit  # type: ignore[attr-defined]


def test_transition_rejects_invalid_paths(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    with pytest.raises(HTTPException) as e:
        ft.transition_candidate(db, ADMIN, c.id, "TRIAL")  # DISCOVERED -> TRIAL không hợp lệ
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        ft.transition_candidate(db, ADMIN, c.id, "APPROVED_FOR_FUTURE")
    assert e.value.status_code == 409
    _ev(db, c)
    ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW")
    ft.transition_candidate(db, ADMIN, c.id, "REJECTED", "không đạt")
    with pytest.raises(HTTPException) as e:
        ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW", "mở lại")  # REJECTED không tự reactivate trong Task 4
    assert e.value.status_code == 409


def test_transition_reason_required_and_reactivate_from_inactive(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    with pytest.raises(HTTPException) as e:
        ft.transition_candidate(db, ADMIN, c.id, "INACTIVE")  # thiếu reason
    assert e.value.status_code == 422
    ft.transition_candidate(db, ADMIN, c.id, "INACTIVE", "ngưng theo dõi")
    _ev(db, c)
    with pytest.raises(HTTPException):
        ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW")  # reactivate cũng bắt buộc reason
    ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW", "theo dõi lại")
    assert ft.get_candidate(db, c.id).status == "UNDER_REVIEW"
    assert ft.list_history(db, c.id)[-1].reason == "theo dõi lại"


def test_identity_edit_only_in_discovered_or_under_review(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    ft.update_candidate(db, ADMIN, c.id, {"brand": "Y"})
    _ev(db, c)
    ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW")
    ft.update_candidate(db, ADMIN, c.id, {"model_name": "Z"})
    ft.transition_candidate(db, ADMIN, c.id, "TRIAL")
    with pytest.raises(HTTPException) as e:
        ft.update_candidate(db, ADMIN, c.id, {"brand": "W"})
    assert e.value.status_code == 409
    assert ft.get_candidate(db, c.id).candidate_code == f"FTC-{c.id:06d}"  # bất biến


def test_evidence_requires_source_and_unit_and_is_append_only(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    with pytest.raises(HTTPException):
        ft.add_evidence(db, ADMIN, c.id, {"note": "no source"})
    with pytest.raises(HTTPException):
        ft.add_evidence(db, ADMIN, c.id, {"source_ref": "brochure", "value": 5})  # có value thiếu unit
    with pytest.raises(HTTPException):
        ft.add_evidence(db, ADMIN, c.id, {"source_ref": "brochure", "basis": "MAGIC"})
    with pytest.raises(HTTPException):
        ft.add_evidence(db, ADMIN, c.id, {"source_ref": "brochure", "value": -1, "unit": "s"})
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "brochure", "basis": "CLAIMED", "metric_code": "CYCLE_TIME", "value": 12.5, "unit": "s", "evidence_date": "2026-09-01"})
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "trial#1", "basis": "TRIALED", "metric_code": "CYCLE_TIME", "value": 14, "unit": "s"})
    assert len(ft.list_evidence(db, c.id)) == 2  # bổ sung = thêm dòng, không overwrite
    assert not hasattr(ft, "update_evidence") and not hasattr(ft, "delete_evidence")
    assert "FUTURE_EVIDENCE_ADD" in db.audit  # type: ignore[attr-defined]


def test_compatibility_validation_and_final_state(db):
    c = _cand(db)
    with pytest.raises(HTTPException):
        ft.save_compatibility(db, ADMIN, {"candidate_id": c.id})  # thiếu operation_code
    with pytest.raises(HTTPException):
        ft.save_compatibility(db, ADMIN, {"candidate_id": 9999, "operation_code": "OP1"})
    with pytest.raises(HTTPException):
        ft.save_compatibility(db, ADMIN, {"candidate_id": c.id, "operation_code": "OP1", "source_machine_type_code": "NOPE"})
    with pytest.raises(HTTPException):
        ft.save_compatibility(db, ADMIN, {"candidate_id": c.id, "operation_code": "OP1", "compatibility_status": "BOGUS"})
    row = ft.save_compatibility(db, ADMIN, {"candidate_id": c.id, "operation_code": "OP1"})
    assert row.compatibility_status == "PROPOSED"  # không tự APPROVED
    with pytest.raises(HTTPException) as e:
        ft.save_compatibility(db, ADMIN, {"operation_code": None}, row.id)  # explicit null -> 422, không IntegrityError
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        ft.save_compatibility(db, ADMIN, {"candidate_id": 9999}, row.id)
    assert ft.save_compatibility(db, ADMIN, {"compatibility_status": "APPROVED"}, row.id).operation_code == "OP1"
    assert "FUTURE_COMPAT_SAVE" in db.audit  # type: ignore[attr-defined]


# =================================================================== permissions
def test_permission_reuse_and_approve_gate(db):
    assert ft.requires_approve("TRIAL", "APPROVED_FOR_FUTURE") and ft.requires_approve("APPROVED_FOR_FUTURE", "REJECTED")
    assert ft.requires_approve("APPROVED_FOR_FUTURE", "INACTIVE") and not ft.requires_approve("UNDER_REVIEW", "TRIAL")
    assert "technology_process.manage" in permissions_for("ADMIN") and "technology_process.manage" not in permissions_for("PLANNER")
    c = _cand(db, status="TRIAL")
    limited = SimpleNamespace(username="mgr", role="NO_APPROVE_ROLE", id=2)  # role không có quyền nào -> approve bị chặn
    with pytest.raises(HTTPException) as e:
        ft_api.transition_candidate(c.id, ft_api.TransitionBody(to_status="APPROVED_FOR_FUTURE"), db, limited)
    assert e.value.status_code == 403
    assert ft.get_candidate(db, c.id).status == "TRIAL"  # không đổi


def test_new_routes_reachable_and_not_shadowed_by_version_route(db):
    """Bài học Task 3: route cùng router-registration-order có thể bị `/versions/{version_id}` bắt nhầm. Gọi thật qua HTTP."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    _p, v = _current(db)
    fv = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    fake_admin = SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: fake_admin
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        base = "/api/planning/technology-process"
        r = client.get(f"{base}/versions/{v.id}/future-preview")
        assert r.status_code == 200 and r.json()["source_layer"] == "CURRENT_PROCESS"
        r = client.get(f"{base}/versions/{fv['id']}/compare-with-baseline")
        assert r.status_code == 200 and r.json()["version_b"]["id"] == fv["id"]
        assert client.get(f"{base}/future/candidates").status_code == 200
        assert client.get(f"{base}/future/options").status_code == 200
    finally:
        app.dependency_overrides.clear()


# =================================================================== generator — source / target / lineage
def test_source_must_be_current_or_optimized_and_not_retired(db):
    _p, v = _current(db)
    fv = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    with pytest.raises(HTTPException) as e:
        gen.generate_future_proposal(db, ADMIN, fv["id"])  # FUTURE -> FUTURE bị chặn
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        gen.preview_future_proposal(db, fv["id"])
    tps.transition_version(db, ADMIN, v.id, "review")
    tps.transition_version(db, ADMIN, v.id, "approve")
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["layer"] == FUTURE  # APPROVED vẫn được
    tps.transition_version(db, ADMIN, v.id, "retire")
    with pytest.raises(HTTPException) as e:
        gen.generate_future_proposal(db, ADMIN, v.id)
    assert e.value.status_code == 409


def test_target_layer_lineage_draft_source_type_and_evidence(db):
    _p, v = _current(db)
    r = gen.generate_future_proposal(db, ADMIN, v.id)
    ver = r["version"]
    assert ver["layer"] == FUTURE and ver["status"] == "DRAFT" and ver["derived_from_version_id"] == v.id
    assert ver["source_type"] == "TECHNOLOGY_SCOUTING"
    a = ver["assumptions_json"]
    assert a["generator_rule_version"] == "FUT_GEN_V1" and a["source_layer"] == "CURRENT_PROCESS" and a["source_status"] == "DRAFT"
    assert a["root_current_version_id"] == v.id and a["numeric_performance_applied"] is False


def test_future_from_optimized_preserves_lineage_and_root(db):
    _p, v = _current(db)
    opt = gen3.generate_optimized_proposal(db, ADMIN, v.id)["version"]
    fv = gen.generate_future_proposal(db, ADMIN, opt["id"])["version"]
    assert fv["derived_from_version_id"] == opt["id"]
    assert fv["assumptions_json"]["source_layer"] == "OPTIMIZED_CURRENT_TECHNOLOGY"
    assert fv["assumptions_json"]["root_current_version_id"] == v.id


def test_generic_derive_to_future_is_blocked_other_layers_still_work(db):
    _p, v = _current(db)
    with pytest.raises(HTTPException) as e:
        tps.derive_version(db, ADMIN, v.id, "FUTURE_TECHNOLOGY")
    assert e.value.status_code == 422
    assert db.query(TechnologyProcessVersion).filter_by(layer=FUTURE).count() == 0
    assert tps.derive_version(db, ADMIN, v.id, "OPTIMIZED_CURRENT_TECHNOLOGY").layer == "OPTIMIZED_CURRENT_TECHNOLOGY"  # Task 1 vẫn chạy


def test_approved_future_version_immutable(db):
    _p, v = _current(db)
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    tps.transition_version(db, ADMIN, r["id"], "review")
    tps.transition_version(db, ADMIN, r["id"], "approve")
    with pytest.raises(HTTPException) as e:
        tps.update_operation(db, ADMIN, r["operations"][0]["id"], {"operation_name": "sửa sau approve"})
    assert e.value.status_code == 409


# =================================================================== generator — decisions
def test_no_candidate_keeps_unchanged(db):
    _p, v = _current(db)
    op = gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]
    assert op["change_type"] == "UNCHANGED" and op["machine_type_code"] == "1K"


def test_valid_future_substitution_auto_applies_only_machine(db):
    mm = _model(db, "2K")
    c = _cand(db, mt="2K", model_id=mm.id)
    _fc(db, c)
    _p, v = _current(db, ops=[{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K", "sam_minutes": 1.5, "cycle_time_seconds": 30, "operator_count": 2}])
    op = gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]
    assert op["change_type"] == "MACHINE_SUBSTITUTION" and op["machine_type_code"] == "2K" and op["machine_model_id"] == mm.id
    assert op["sam_minutes"] == 1.5 and op["cycle_time_seconds"] == 30 and op["operator_count"] == 2  # BR-409 giữ nguyên baseline
    assert c.candidate_code in op["evidence_note"] and op["evidence_ref"] == f"FutureTechnologyCandidate#{c.candidate_code}"


def test_no_invented_numeric_even_with_numeric_evidence(db):
    c = _cand(db, evidence=False)
    _fc(db, c)
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "spec", "basis": "CLAIMED", "metric_code": "CYCLE_TIME", "value": 5, "unit": "s"})
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "spec", "basis": "CLAIMED", "metric_code": "OUTPUT", "value": 9999, "unit": "pcs/day"})
    _p, v = _current(db)  # baseline không có SAM/cycle/output
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    op = r["operations"][0]
    assert op["sam_minutes"] is None and op["cycle_time_seconds"] is None and op["expected_output_per_day"] is None and op["operator_count"] in (None, 0)
    assert r["total_sam_minutes"] is None and r["sam_status"] == "INCOMPLETE"
    assert r["expected_output_per_day"] is None and r["required_labor"] is None
    mc = r["assumptions_json"]["metric_completeness"]
    assert mc["expected_output_per_day"] == "N/A" and mc["required_labor"] == "N/A" and mc["machine_quantity"] == "N/A"
    assert mc["bottleneck"] == "N/A" and mc["utilization"] == "N/A"
    ev = r["assumptions_json"]["decisions"][0]["candidates_considered"][0]["evidence"]
    assert {e["metric_code"] for e in ev} == {"CYCLE_TIME", "OUTPUT"}  # evidence được lưu để trace nhưng không áp


@pytest.mark.parametrize("status", ["DISCOVERED", "UNDER_REVIEW"])
def test_discovered_and_under_review_are_preview_only(db, status):
    c = _cand(db, status=status)
    row = _fc(db, c)
    _p, v = _current(db)
    pv = gen.preview_future_proposal(db, v.id)["operations"][0]
    assert pv["decision"] == "UNCHANGED" and len(pv["candidates"]) == 1 and pv["candidates"][0]["selectable"] is False
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]["change_type"] == "UNCHANGED"
    with pytest.raises(HTTPException) as e:
        gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": row.id})
    assert e.value.status_code == 422


def test_trial_not_auto_but_user_selectable_marked_unverified(db):
    c = _cand(db, status="TRIAL")
    row = _fc(db, c)
    _p, v = _current(db)
    assert gen.preview_future_proposal(db, v.id)["operations"][0]["decision"] == "UNVERIFIED_CANDIDATE_AVAILABLE"
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]["change_type"] == "UNCHANGED"  # không auto
    r = gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": row.id})["version"]
    op = r["operations"][0]
    assert op["change_type"] == "MACHINE_SUBSTITUTION" and "USER_SELECTED_UNVERIFIED_CANDIDATE" in op["evidence_note"] and r["status"] == "DRAFT"


def test_approved_candidate_with_non_approved_compat_not_auto(db):
    c = _cand(db)
    row = _fc(db, c, status="PROPOSED")
    _p, v = _current(db)
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]["change_type"] == "UNCHANGED"
    r = gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": row.id})["version"]["operations"][0]
    assert r["change_type"] == "MACHINE_SUBSTITUTION" and "UNVERIFIED" in r["evidence_note"]


@pytest.mark.parametrize("status", ["REJECTED", "INACTIVE"])
def test_rejected_or_inactive_candidate_blocked(db, status):
    c = _cand(db, status=status)
    row = _fc(db, c)
    _p, v = _current(db)
    assert gen.preview_future_proposal(db, v.id)["operations"][0]["candidates"] == []
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]["change_type"] == "UNCHANGED"
    with pytest.raises(HTTPException) as e:
        gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": row.id})
    assert e.value.status_code == 422


def test_incompatible_mapping_rejected(db):
    c = _cand(db)
    other_op = _fc(db, c, op="OTHER")  # mapping cho operation khác
    other_src = _fc(db, c, op="OP1", src="3K")  # nguồn máy khác máy hiện tại (1K)
    rejected = _fc(db, c, op="OP1", src="1K", status="REJECTED")
    _p, v = _current(db)
    assert gen.preview_future_proposal(db, v.id)["operations"][0]["candidates"] == []
    for row in (other_op, other_src, rejected):
        with pytest.raises(HTTPException) as e:
            gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": row.id})
        assert e.value.status_code == 422


def test_structure_integrity_blocks_bad_model_and_inactive_type(db):
    rejected_model = _model(db, "2K", "REJECTED")
    c1 = _cand(db, mt="2K", model_id=rejected_model.id, model_name="A")
    _fc(db, c1)
    db.add(MachineType(code="9K", name="9K", status="INACTIVE"))
    db.commit()
    c2 = _cand(db, mt="9K", model_name="B")
    _fc(db, c2)
    ok_model = _model(db, "2K", "APPROVED")
    c3 = _cand(db, mt="2K", model_id=ok_model.id, model_name="C")
    _fc(db, c3)
    ok_model.machine_type_code = "3K"  # đổi loại máy của model -> mismatch với candidate 2K (dữ liệu hỏng)
    db.commit()
    _p, v = _current(db)
    assert gen.preview_future_proposal(db, v.id)["operations"][0]["candidates"] == []


def test_multiple_approved_candidates_not_auto_selected(db):
    c1, c2 = _cand(db, mt="2K", model_name="A"), _cand(db, mt="3K", model_name="B")
    _fc(db, c1)
    r2 = _fc(db, c2)
    _p, v = _current(db)
    assert gen.preview_future_proposal(db, v.id)["operations"][0]["decision"] == "MULTIPLE_CANDIDATES"
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]["change_type"] == "UNCHANGED"  # không tie-break
    r = gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": r2.id})["version"]["operations"][0]
    assert r["machine_type_code"] == "3K"


def test_mixed_approved_and_trial_auto_applies_only_the_single_eligible(db):
    ok, trial = _cand(db, mt="2K", model_name="A"), _cand(db, mt="3K", status="TRIAL", model_name="B")
    _fc(db, ok)
    _fc(db, trial)
    _p, v = _current(db)
    op = gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]
    assert op["machine_type_code"] == "2K"  # TRIAL không tham gia auto


def test_operation_without_machine_or_code_always_unchanged(db):
    c = _cand(db)
    _fc(db, c, op="OPX", src=None)
    _p, v = _current(db, ops=[{"operation_name": "tay", "operation_code": "", "machine_type_code": None}, {"operation_name": "tay2", "operation_code": "OPX", "machine_type_code": None}])
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    assert all(o["change_type"] == "UNCHANGED" for o in r["operations"])


# =================================================================== automation_level
def test_automation_copied_change_type_stays_substitution_delta_in_evidence(db):
    c = _cand(db, automation="Auto-Sewing")
    _fc(db, c)
    _p, v = _current(db, ops=[{"operation_name": "May", "operation_code": "OP1", "machine_type_code": "1K", "automation_level": "Manual"}])
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    op = r["operations"][0]
    assert op["automation_level"] == "Auto-Sewing" and op["change_type"] == "MACHINE_SUBSTITUTION"  # không thành AUTOMATION_UPGRADE
    assert r["assumptions_json"]["automation_deltas"] == [{"sequence_no": 1, "before": "Manual", "after": "Auto-Sewing"}]
    cmp = gen.compare_with_baseline(db, r["id"])
    assert cmp["automation_change_count"] == 1  # đếm theo field-delta


def test_empty_candidate_automation_does_not_overwrite(db):
    c = _cand(db, automation="")
    _fc(db, c)
    _p, v = _current(db, ops=[{"operation_name": "May", "operation_code": "OP1", "machine_type_code": "1K", "automation_level": "Manual"}])
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    assert r["operations"][0]["automation_level"] == "Manual" and r["assumptions_json"]["automation_deltas"] == []


# =================================================================== selections validation
@pytest.mark.parametrize("sel", [{"999": 1}, {"abc": 1}])
def test_bad_selection_keys_rejected_no_version_created(db, sel):
    _p, v = _current(db)
    with pytest.raises(HTTPException) as e:
        gen.generate_future_proposal(db, ADMIN, v.id, selections=sel)
    assert e.value.status_code == 422
    assert db.query(TechnologyProcessVersion).filter_by(layer=FUTURE).count() == 0


def test_duplicate_semantic_selection_keys_rejected(db):
    c1, c2 = _cand(db, mt="2K", model_name="A"), _cand(db, mt="3K", model_name="B")
    a, b = _fc(db, c1), _fc(db, c2)
    _p, v = _current(db)
    with pytest.raises(HTTPException) as e:
        gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": a.id, "01": b.id})
    assert e.value.status_code == 422
    assert db.query(TechnologyProcessVersion).filter_by(layer=FUTURE).count() == 0


def test_unknown_compat_id_selection_rejected(db):
    _p, v = _current(db)
    with pytest.raises(HTTPException) as e:
        gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": 9999})
    assert e.value.status_code == 422


# =================================================================== fingerprint / idempotency
def test_same_inputs_twice_is_no_op(db):
    c = _cand(db)
    _fc(db, c)
    _p, v = _current(db)
    r1, r2 = gen.generate_future_proposal(db, ADMIN, v.id), gen.generate_future_proposal(db, ADMIN, v.id)
    assert r1["created"] is True and r2["created"] is False and r1["version"]["id"] == r2["version"]["id"]
    assert db.query(TechnologyProcessVersion).filter_by(layer=FUTURE).count() == 1


def test_source_change_creates_new_proposal_keeps_old(db):
    _p, v = _current(db)
    r1 = gen.generate_future_proposal(db, ADMIN, v.id)
    tps.add_operation(db, ADMIN, v.id, {"operation_name": "Thêm", "operation_code": "OP2"})
    db.refresh(v)
    r2 = gen.generate_future_proposal(db, ADMIN, v.id)
    assert r2["created"] is True and r2["version"]["id"] != r1["version"]["id"]
    assert db.query(TechnologyProcessVersion).filter_by(layer=FUTURE).count() == 2


def test_candidate_change_creates_new_proposal(db):
    c = _cand(db)
    _fc(db, c)
    _p, v = _current(db)
    r1 = gen.generate_future_proposal(db, ADMIN, v.id)
    c.machine_type_code = "3K"  # đổi target machine trên CÙNG candidate
    db.commit()
    r2 = gen.generate_future_proposal(db, ADMIN, v.id)
    assert r2["created"] is True and r2["version"]["operations"][0]["machine_type_code"] == "3K"
    assert r1["version"]["operations"][0]["machine_type_code"] == "2K"  # bản cũ giữ nguyên lịch sử


def test_candidate_status_change_creates_new_proposal(db):
    c = _cand(db, status="TRIAL")
    _fc(db, c)
    _p, v = _current(db)
    r1 = gen.generate_future_proposal(db, ADMIN, v.id)
    ft.transition_candidate(db, ADMIN, c.id, "APPROVED_FOR_FUTURE")
    r2 = gen.generate_future_proposal(db, ADMIN, v.id)
    assert r2["created"] is True and r2["version"]["id"] != r1["version"]["id"]


def test_evidence_change_creates_new_proposal(db):
    c = _cand(db)
    _fc(db, c)
    _p, v = _current(db)
    r1 = gen.generate_future_proposal(db, ADMIN, v.id)
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "trial#7", "basis": "TRIALED", "metric_code": "OUTPUT", "value": 800, "unit": "pcs/day"})
    r2 = gen.generate_future_proposal(db, ADMIN, v.id)
    assert r2["created"] is True and r2["version"]["id"] != r1["version"]["id"]
    assert r2["version"]["assumptions_json"]["evidence_snapshot_hash"] != r1["version"]["assumptions_json"]["evidence_snapshot_hash"]


def test_compat_change_creates_new_proposal_but_unrelated_mapping_does_not(db):
    c = _cand(db)
    row = _fc(db, c, src="1K")
    unrelated = _fc(db, c, op="OP1", src="3K")  # nguồn máy 3K — không liên quan máy hiện tại 1K
    _p, v = _current(db)
    r1 = gen.generate_future_proposal(db, ADMIN, v.id)
    ft.save_compatibility(db, ADMIN, {"evidence_note": "unrelated edit"}, unrelated.id)
    assert gen.generate_future_proposal(db, ADMIN, v.id)["created"] is False  # không nhiễu bởi mapping không liên quan
    ft.save_compatibility(db, ADMIN, {"evidence_note": "relevant edit"}, row.id)
    assert gen.generate_future_proposal(db, ADMIN, v.id)["created"] is True
    assert r1["created"] is True


def test_future_fingerprint_independent_from_task3_generator(db):
    _p, v = _current(db)
    opt = gen3.generate_optimized_proposal(db, ADMIN, v.id)
    fut = gen.generate_future_proposal(db, ADMIN, v.id)
    assert opt["version"]["generation_fingerprint"] != fut["version"]["generation_fingerprint"]
    assert fut["created"] is True  # Task 3 proposal không làm Future bị coi là duplicate


def test_task3_generator_unaffected_by_future_catalog(db):
    c = _cand(db)
    _fc(db, c)
    _p, v = _current(db)
    op = gen3.generate_optimized_proposal(db, ADMIN, v.id)["version"]["operations"][0]
    assert op["change_type"] == "UNCHANGED" and op["machine_type_code"] == "1K"  # Layer 2 không nhặt dòng Future


# =================================================================== evidence lịch sử
def test_generation_evidence_survives_later_candidate_edit(db):
    c = _cand(db, automation="Auto", evidence=False)
    _fc(db, c)
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "spec", "basis": "CLAIMED", "metric_code": "OUTPUT", "value": 500, "unit": "pcs/day"})
    _p, v = _current(db)
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    d0 = r["assumptions_json"]["decisions"][0]
    assert d0["chosen_candidate_code"] == c.candidate_code and d0["chosen_candidate_status"] == "APPROVED_FOR_FUTURE"
    assert d0["candidates_considered"][0]["evidence_count"] == 1 and d0["candidates_considered"][0]["candidate_status"] == "APPROVED_FOR_FUTURE"
    for h in ("source_snapshot_hash", "candidate_snapshot_hash", "evidence_snapshot_hash", "compatibility_snapshot_hash"):
        assert r["assumptions_json"][h]
    ft.transition_candidate(db, ADMIN, c.id, "INACTIVE", "ngưng")
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "later", "basis": "OBSERVED", "metric_code": "OTHER"})
    stored = tps.get_version(db, r["id"]).assumptions_json["decisions"][0]
    assert stored["chosen_candidate_status"] == "APPROVED_FOR_FUTURE" and stored["candidates_considered"][0]["evidence_count"] == 1


# =================================================================== compare
def test_compare_counts_na_and_evidence_completeness(db):
    c = _cand(db, evidence=False)
    _fc(db, c)
    ft.add_evidence(db, ADMIN, c.id, {"source_ref": "trial#1", "basis": "TRIALED", "metric_code": "CYCLE_TIME", "value": 10, "unit": "s"})
    _p, v = _current(db, ops=[{"operation_name": "Vắt sổ", "operation_code": "OP1", "machine_type_code": "1K"}, {"operation_name": "Ủi", "operation_code": "OP2"}])
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    cmp = gen.compare_with_baseline(db, r["id"])
    assert cmp["machine_substitution_count"] == 1 and cmp["operation_changed_count"] == 1
    assert cmp["machine_config_changes"][0]["before"]["machine_type_code"] == "1K" and cmp["machine_config_changes"][0]["after"]["machine_type_code"] == "2K"
    assert cmp["total_sam_minutes"] == {"a": None, "b": None} and cmp["required_labor"] == {"a": None, "b": None}
    assert cmp["machine_count"] == "NOT_AVAILABLE" and cmp["bottleneck"] == "N/A" and cmp["utilization"] == "N/A"
    assert "expected_output_per_day" in cmp["unknown_or_incomplete_metrics"]
    row = cmp["evidence_completeness"]["substituted_operations"][0]
    assert row["evidence_count"] == 1 and row["bases"] == ["TRIALED"] and row["has_observed_or_trialed"] and row["approved_for_future"]
    assert cmp["evidence_completeness"]["all_substitutions_have_evidence"] is True


def test_compare_against_optimized_baseline(db):
    _p, v = _current(db)
    opt = gen3.generate_optimized_proposal(db, ADMIN, v.id)["version"]
    fv = gen.generate_future_proposal(db, ADMIN, opt["id"])["version"]
    cmp = gen.compare_with_baseline(db, fv["id"])
    assert cmp["baseline_layer"] == "OPTIMIZED_CURRENT_TECHNOLOGY" and cmp["version_a"]["id"] == opt["id"]


def test_compare_guards(db):
    _p, v = _current(db)
    fv = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    with pytest.raises(HTTPException):
        gen.compare_with_baseline(db, v.id)  # Current gốc không có lineage
    with pytest.raises(HTTPException):
        gen.compare_baseline_vs_future(db, fv["id"], v.id)  # đảo a/b: baseline là FUTURE, target không phải FUTURE
    v2 = tps.create_draft_version(db, ADMIN, _p.id, {"layer": "CURRENT_PROCESS"})
    with pytest.raises(HTTPException) as e:
        gen.compare_baseline_vs_future(db, v2.id, fv["id"])  # cùng process, đúng layer nhưng KHÔNG phải nguồn trực tiếp
    assert e.value.status_code == 422
    _p2, w = _current(db, "F200")
    with pytest.raises(HTTPException):
        gen.compare_baseline_vs_future(db, w.id, fv["id"])  # khác process
    opt = gen3.generate_optimized_proposal(db, ADMIN, v.id)["version"]
    with pytest.raises(HTTPException):
        gen3.compare_current_vs_optimized(db, v.id, fv["id"])  # guard Task 3 không bị nới: Future không đi qua endpoint Task 3
    assert gen3.compare_current_vs_optimized(db, v.id, opt["id"])["version_b"]["id"] == opt["id"]


def test_generate_is_audited(db):
    _p, v = _current(db)
    gen.generate_future_proposal(db, ADMIN, v.id)
    assert "FUTURE_PROPOSAL_GENERATE" in db.audit  # type: ignore[attr-defined]


# =================================================================== PR #10 review round 1 — mục 1: evidence bắt buộc
def test_cannot_enter_review_or_approval_without_evidence(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    with pytest.raises(HTTPException) as e:
        ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW")  # rời DISCOVERED phải có provenance
    assert e.value.status_code == 422
    assert ft.get_candidate(db, c.id).status == "DISCOVERED" and len(ft.list_history(db, c.id)) == 1  # không đổi, không ghi history
    c.status = "TRIAL"  # fixture dữ liệu lỗi: TRIAL mà 0 evidence
    db.commit()
    with pytest.raises(HTTPException) as e:
        ft.transition_candidate(db, ADMIN, c.id, "APPROVED_FOR_FUTURE")  # defense-in-depth ở bước duyệt
    assert e.value.status_code == 422 and ft.get_candidate(db, c.id).status == "TRIAL"


def test_adding_evidence_unblocks_transitions(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    _ev(db, c)
    for to in ("UNDER_REVIEW", "TRIAL", "APPROVED_FOR_FUTURE"):
        ft.transition_candidate(db, ADMIN, c.id, to)
    assert ft.get_candidate(db, c.id).status == "APPROVED_FOR_FUTURE"


def test_reactivate_from_inactive_also_requires_evidence(db):
    c = ft.create_candidate(db, ADMIN, {"machine_type_code": "2K", "brand": "X"})
    ft.transition_candidate(db, ADMIN, c.id, "INACTIVE", "ngưng")  # INACTIVE không cần evidence
    with pytest.raises(HTTPException) as e:
        ft.transition_candidate(db, ADMIN, c.id, "UNDER_REVIEW", "mở lại")
    assert e.value.status_code == 422


def test_approved_candidate_without_evidence_never_auto_applies(db):
    c = _cand(db, evidence=False)  # APPROVED_FOR_FUTURE nhưng 0 evidence (dữ liệu lỗi/legacy)
    row = _fc(db, c)
    _p, v = _current(db)
    entry = gen.preview_future_proposal(db, v.id)["operations"][0]
    assert entry["decision"] == "UNVERIFIED_CANDIDATE_AVAILABLE" and entry["candidates"][0]["auto_eligible"] is False and entry["candidates"][0]["evidence_count"] == 0
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["operations"][0]["change_type"] == "UNCHANGED"  # không auto
    r = gen.generate_future_proposal(db, ADMIN, v.id, selections={"1": row.id})["version"]["operations"][0]
    assert r["change_type"] == "MACHINE_SUBSTITUTION" and "UNVERIFIED" in r["evidence_note"]  # chỉ user chọn tay, đánh dấu unverified
    _ev(db, c)  # thêm evidence hợp lệ -> auto đúng
    auto = gen.generate_future_proposal(db, ADMIN, v.id)
    assert auto["created"] is True and auto["version"]["operations"][0]["change_type"] == "MACHINE_SUBSTITUTION"
    assert "UNVERIFIED" not in auto["version"]["operations"][0]["evidence_note"]


def test_evidence_snapshot_and_history_behaviour_unchanged(db):
    c = _cand(db, evidence=False)
    _ev(db, c, "spec-1", metric_code="OUTPUT", value=100, unit="pcs/day")
    _fc(db, c)
    _p, v = _current(db)
    r = gen.generate_future_proposal(db, ADMIN, v.id)["version"]
    assert r["assumptions_json"]["decisions"][0]["candidates_considered"][0]["evidence_count"] == 1
    _ev(db, c, "spec-2")
    assert tps.get_version(db, r["id"]).assumptions_json["decisions"][0]["candidates_considered"][0]["evidence_count"] == 1  # snapshot lịch sử không đổi


# =================================================================== PR #10 review round 1 — mục 2: không bypass bằng create Draft
def test_direct_create_draft_future_rejected_no_row_created(db):
    p = tps.create_process(db, ADMIN, {"style_cc": "NOFUT", "model_code": ""})
    with pytest.raises(HTTPException) as e:
        tps.create_draft_version(db, ADMIN, p.id, {"layer": "FUTURE_TECHNOLOGY"})
    assert e.value.status_code == 422
    assert db.query(TechnologyProcessVersion).filter_by(technology_process_id=p.id).count() == 0


def test_generic_derive_future_still_rejected_and_generator_and_other_layers_still_work(db):
    p, v = _current(db)
    with pytest.raises(HTTPException) as e:
        tps.derive_version(db, ADMIN, v.id, "FUTURE_TECHNOLOGY")
    assert e.value.status_code == 422
    assert gen.generate_future_proposal(db, ADMIN, v.id)["version"]["status"] == "DRAFT"  # generator vẫn tạo Future bình thường
    for layer in ("CURRENT_PROCESS", "OPTIMIZED_CURRENT_TECHNOLOGY"):  # Task 1–3 không regression
        assert tps.create_draft_version(db, ADMIN, p.id, {"layer": layer}).layer == layer
    assert db.query(TechnologyProcessVersion).filter_by(layer=FUTURE).count() == 1


def test_create_draft_future_rejected_via_http_api(db):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    p, _v = _current(db)
    fake_admin = SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_current_user] = lambda: fake_admin
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        r = client.post(f"/api/planning/technology-process/processes/{p.id}/versions", json={"layer": "FUTURE_TECHNOLOGY"})
        assert r.status_code == 422
        assert client.post(f"/api/planning/technology-process/processes/{p.id}/versions", json={"layer": "OPTIMIZED_CURRENT_TECHNOLOGY"}).status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert db.query(TechnologyProcessVersion).filter_by(layer=FUTURE).count() == 0
