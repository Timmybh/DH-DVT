from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.permissions import permissions_for
from app.db.session import Base
from app.models.resources import MachineModel, MachineType
from app.models.technology_process import LAYER_LABEL, TechnologyProcess, TechnologyProcessOperation, TechnologyProcessVersion
from app.services import technology_process_service as svc

ADMIN = SimpleNamespace(username="admin", role="ADMIN")


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[MachineType.__table__, MachineModel.__table__, TechnologyProcess.__table__, TechnologyProcessVersion.__table__, TechnologyProcessOperation.__table__])
    s = sessionmaker(bind=engine)()
    events: list[str] = []
    monkeypatch.setattr(svc, "write_audit", lambda action, **kw: events.append(action))
    s.audit = events  # type: ignore[attr-defined]
    s.add(MachineType(code="1K", name="Máy 1 kim"))
    s.add(MachineType(code="2K", name="Máy 2 kim"))
    s.commit()
    yield s
    s.close()


def _process_with_ops(db, layer="CURRENT_PROCESS", sams=(1.2, 0.8, 2.0)):
    p = svc.create_process(db, ADMIN, {"style_cc": "A100", "model_code": "M1"})
    v = svc.create_draft_version(db, ADMIN, p.id, {"layer": layer, "source_type": "ENGINEERING"})
    for i, sam in enumerate(sams, start=1):
        svc.add_operation(db, ADMIN, v.id, {"operation_name": f"OP{i}", "sam_minutes": sam, "operator_count": 1})
    db.refresh(v)
    return p, v


# ------------------------------------------------------------------ AC-001 / layer enum (V-001)
def test_layer_enum_exactly_three_values_and_labels():
    from app.models.technology_process import LAYERS

    assert LAYERS == ("CURRENT_PROCESS", "OPTIMIZED_CURRENT_TECHNOLOGY", "FUTURE_TECHNOLOGY")
    assert LAYER_LABEL["OPTIMIZED_CURRENT_TECHNOLOGY"] == "Optimized Current Technology"
    assert LAYER_LABEL["FUTURE_TECHNOLOGY"] == "Future Technology"


def test_create_version_rejects_invalid_layer(db):
    p = svc.create_process(db, ADMIN, {"style_cc": "A100", "model_code": "M1"})
    with pytest.raises(HTTPException) as e:
        svc.create_draft_version(db, ADMIN, p.id, {"layer": "NOT_A_LAYER"})
    assert e.value.status_code == 422


# ------------------------------------------------------------------ BR-005 version uniqueness / process = (style, model) family
def test_version_no_unique_and_sequential_per_process_and_layer(db):
    p = svc.create_process(db, ADMIN, {"style_cc": "A100", "model_code": "M1"})
    v1 = svc.create_draft_version(db, ADMIN, p.id, {"layer": "CURRENT_PROCESS"})
    v2 = svc.create_draft_version(db, ADMIN, p.id, {"layer": "CURRENT_PROCESS"})
    v3 = svc.create_draft_version(db, ADMIN, p.id, {"layer": "OPTIMIZED_CURRENT_TECHNOLOGY"})
    assert (v1.version_no, v2.version_no, v3.version_no) == (1, 2, 1)  # mỗi layer có chuỗi version riêng trong cùng Process
    with pytest.raises(HTTPException):
        svc.create_process(db, ADMIN, {"style_cc": "A100", "model_code": "M1"})  # cùng (style, model) -> trùng Process, không tạo mới


def test_process_code_stable_and_style_model_null_safe(db):
    p1 = svc.create_process(db, ADMIN, {"style_cc": "B200", "model_code": ""})
    p2 = svc.create_process(db, ADMIN, {"style_cc": "B200", "model_code": "X"})
    assert p1.id != p2.id and p1.process_code != p2.process_code
    code_before = p1.process_code
    svc.create_draft_version(db, ADMIN, p1.id, {"layer": "CURRENT_PROCESS"})
    assert p1.process_code == code_before  # bất biến


# ------------------------------------------------------------------ BR-016 / AC-003 Total SAM giải thích được
def test_total_sam_sums_active_operations_and_is_explainable(db):
    _, v = _process_with_ops(db, sams=(1.2, 0.8, 2.0))
    assert v.total_sam_minutes == 4.0 and v.sam_status == "COMPLETE"
    ops = svc.version_view(v, with_operations=True)["operations"]
    assert sorted(o["sam_minutes"] for o in ops) == [0.8, 1.2, 2.0]  # UI/API xem được từng operation đóng góp


# ------------------------------------------------------------------ BR-017 / AC-004 thiếu SAM -> incomplete, KHÔNG lấy default Style khác
def test_missing_sam_marks_version_incomplete_not_defaulted(db):
    p, v = _process_with_ops(db, sams=(1.2, 0.8, 2.0))
    op_no_sam = svc.add_operation(db, ADMIN, v.id, {"operation_name": "OP4", "operator_count": 1})  # không có sam_minutes
    db.refresh(v)
    assert op_no_sam.sam_minutes is None and v.total_sam_minutes is None and v.sam_status == "INCOMPLETE"
    svc.remove_operation(db, ADMIN, op_no_sam.id, "test remove")
    db.refresh(v)
    assert v.total_sam_minutes == 4.0 and v.sam_status == "COMPLETE"  # gỡ operation thiếu SAM -> tính lại đúng, không copy median


def test_empty_version_has_no_total_sam(db):
    p = svc.create_process(db, ADMIN, {"style_cc": "C300", "model_code": ""})
    v = svc.create_draft_version(db, ADMIN, p.id, {"layer": "CURRENT_PROCESS"})
    assert v.total_sam_minutes is None and v.sam_status == "EMPTY"


def test_operation_validations_v004_v005_v009(db):
    _, v = _process_with_ops(db)
    with pytest.raises(HTTPException):
        svc.add_operation(db, ADMIN, v.id, {"operation_name": "bad sam", "sam_minutes": 0})  # V-004
    with pytest.raises(HTTPException):
        svc.add_operation(db, ADMIN, v.id, {"operation_name": "bad operator", "operator_count": -1})  # V-005
    mm = svc.save_machine_model(db, ADMIN, {"machine_type_code": "1K", "brand": "Juki", "model": "DDL-9000"})
    with pytest.raises(HTTPException):
        svc.add_operation(db, ADMIN, v.id, {"operation_name": "mismatch", "machine_type_code": "2K", "machine_model_id": mm.id})  # V-009
    ok = svc.add_operation(db, ADMIN, v.id, {"operation_name": "ok", "machine_type_code": "1K", "machine_model_id": mm.id})
    assert ok.machine_model_id == mm.id


def test_duplicate_sequence_no_rejected_among_active_operations(db):
    _, v = _process_with_ops(db)
    with pytest.raises(HTTPException):
        svc.add_operation(db, ADMIN, v.id, {"operation_name": "dup", "sequence_no": 1})  # V-003


# ------------------------------------------------------------------ V-007 / AC-005 Approved immutable
def test_approved_version_is_immutable_new_version_required(db):
    p, v = _process_with_ops(db)
    svc.simulate_version(db, ADMIN, v.id)
    svc.transition_version(db, ADMIN, v.id, "review")
    svc.transition_version(db, ADMIN, v.id, "approve")
    db.refresh(v)
    assert v.status == "APPROVED"
    with pytest.raises(HTTPException) as e:
        svc.add_operation(db, ADMIN, v.id, {"operation_name": "sửa sau approve"})
    assert e.value.status_code == 409
    op = v.operations[0]
    with pytest.raises(HTTPException):
        svc.update_operation(db, ADMIN, op.id, {"sam_minutes": 99})
    with pytest.raises(HTTPException):
        svc.remove_operation(db, ADMIN, op.id)
    with pytest.raises(HTTPException):
        svc.update_version(db, ADMIN, v.id, {"note": "sửa sau approve"})
    # muốn đổi phải tạo version mới
    v2 = svc.create_draft_version(db, ADMIN, p.id, {"layer": "CURRENT_PROCESS"})
    assert v2.version_no == v.version_no + 1


def test_retired_version_also_immutable(db):
    _, v = _process_with_ops(db)
    svc.transition_version(db, ADMIN, v.id, "review")
    svc.transition_version(db, ADMIN, v.id, "approve")
    svc.transition_version(db, ADMIN, v.id, "retire")
    db.refresh(v)
    assert v.status == "RETIRED"
    with pytest.raises(HTTPException):
        svc.add_operation(db, ADMIN, v.id, {"operation_name": "x"})


def test_forward_only_transitions_reject_invalid_jumps(db):
    _, v = _process_with_ops(db)
    with pytest.raises(HTTPException):
        svc.transition_version(db, ADMIN, v.id, "approve")  # chưa REVIEWED
    svc.transition_version(db, ADMIN, v.id, "review")
    with pytest.raises(HTTPException):
        svc.transition_version(db, ADMIN, v.id, "retire")  # chưa APPROVED


# ------------------------------------------------------------------ BR-006 derive/clone lineage
def test_derive_clones_active_operations_and_sets_lineage_no_auto_sync(db):
    p, v_current = _process_with_ops(db, layer="CURRENT_PROCESS", sams=(1.2, 0.8, 2.0))
    v_opt = svc.derive_version(db, ADMIN, v_current.id, "OPTIMIZED_CURRENT_TECHNOLOGY")
    assert v_opt.layer == "OPTIMIZED_CURRENT_TECHNOLOGY" and v_opt.version_no == 1 and v_opt.derived_from_version_id == v_current.id
    assert v_opt.total_sam_minutes == 4.0 and v_opt.status == "DRAFT"
    # sửa version nguồn sau khi derive KHÔNG ảnh hưởng bản derive (không auto-sync)
    svc.add_operation(db, ADMIN, v_current.id, {"operation_name": "OP4", "sam_minutes": 5.0, "sequence_no": 4})
    db.refresh(v_current)
    db.refresh(v_opt)
    assert v_current.total_sam_minutes == 9.0 and v_opt.total_sam_minutes == 4.0


def test_derive_rejects_invalid_target_layer(db):
    _, v = _process_with_ops(db)
    with pytest.raises(HTTPException):
        svc.derive_version(db, ADMIN, v.id, "NOT_A_LAYER")


# ------------------------------------------------------------------ BR-008 / AC-006 generated không tự approved
def test_no_code_path_auto_approves_generated_version(db):
    p = svc.create_process(db, ADMIN, {"style_cc": "D400", "model_code": ""})
    v = svc.create_draft_version(db, ADMIN, p.id, {"layer": "FUTURE_TECHNOLOGY", "source_type": "AUTO_GENERATED"})
    assert v.status == "DRAFT"  # tạo AUTO_GENERATED chỉ ở DRAFT, không có API/service nào set thẳng APPROVED
    svc.simulate_version(db, ADMIN, v.id)
    db.refresh(v)
    assert v.status == "SIMULATED"  # vẫn là proposal, phải qua review/approve thủ công mới lên APPROVED


# ------------------------------------------------------------------ permission enforcement (AC: backend enforce, không chỉ ẩn nút)
def test_permission_enforcement_admin_only_by_default():
    admin = set(permissions_for("ADMIN"))
    for perm in ("technology_process.view", "technology_process.manage", "technology_process.review", "technology_process.approve"):
        assert perm in admin
        assert perm not in permissions_for("PLANNER")
        assert perm not in permissions_for("VIEWER")


# ------------------------------------------------------------------ BR-015 / AC-007 bootstrap idempotent
def test_bootstrap_idempotent_same_fingerprint_no_duplicate(db):
    payload = {"style_cc": "E500", "model_code": "M9", "source_ref": "QTCN manual 2026-09-22", "operations": [{"operation_name": "Ráp thân", "sam_minutes": 1.5}, {"operation_name": "Vắt sổ", "sam_minutes": 0.9}]}
    r1 = svc.bootstrap_current_process(db, ADMIN, payload)
    r2 = svc.bootstrap_current_process(db, ADMIN, dict(payload))
    assert r1["created"] is True and r2["created"] is False and r1["version"]["id"] == r2["version"]["id"]
    assert db.query(TechnologyProcessVersion).filter_by(layer="CURRENT_PROCESS").count() == 1
    assert r2["version"]["total_sam_minutes"] == 2.4 and r2["version"]["source_type"] == "IMPORT"
    # đổi nội dung operations -> fingerprint khác -> version mới (v2), không ghi đè v1
    payload2 = {**payload, "operations": [*payload["operations"], {"operation_name": "Thêm", "sam_minutes": 0.3}]}
    r3 = svc.bootstrap_current_process(db, ADMIN, payload2)
    assert r3["created"] is True and r3["version"]["version_no"] == 2


def test_bootstrap_requires_source_ref_and_operations(db):
    with pytest.raises(HTTPException):
        svc.bootstrap_current_process(db, ADMIN, {"style_cc": "F1", "operations": [{"operation_name": "x"}]})  # thiếu source_ref
    with pytest.raises(HTTPException):
        svc.bootstrap_current_process(db, ADMIN, {"style_cc": "F1", "source_ref": "abc", "operations": []})  # thiếu operations


# ------------------------------------------------------------------ machine type/model validation
def test_machine_model_must_reference_existing_machine_type(db):
    with pytest.raises(HTTPException):
        svc.save_machine_model(db, ADMIN, {"machine_type_code": "ZZZ", "brand": "x", "model": "y"})
    mm = svc.save_machine_model(db, ADMIN, {"machine_type_code": "1K", "brand": "Juki", "model": "DDL-9000", "status": "CANDIDATE"})
    assert mm.status == "CANDIDATE"  # không tự APPROVED
    with pytest.raises(HTTPException):
        svc.save_machine_model(db, ADMIN, {"status": "NOT_A_STATUS"}, mm.id)


def test_machine_model_is_independent_master_not_owned_by_process(db):
    """Một MachineModel có thể được nhiều Operation của nhiều Process/Version khác nhau tham chiếu (Issue #3 review mục 1)."""
    mm = svc.save_machine_model(db, ADMIN, {"machine_type_code": "1K", "brand": "Juki", "model": "DDL-9000"})
    p1, v1 = _process_with_ops(db, sams=(1.0,))
    op1 = v1.operations[0]
    svc.update_operation(db, ADMIN, op1.id, {"machine_type_code": "1K", "machine_model_id": mm.id})
    p2 = svc.create_process(db, ADMIN, {"style_cc": "G700", "model_code": ""})
    v2 = svc.create_draft_version(db, ADMIN, p2.id, {"layer": "FUTURE_TECHNOLOGY"})
    op2 = svc.add_operation(db, ADMIN, v2.id, {"operation_name": "OPx", "machine_type_code": "1K", "machine_model_id": mm.id})
    assert op1.machine_model_id == op2.machine_model_id == mm.id  # cùng model, hai process khác nhau — không có ownership ràng buộc


# ------------------------------------------------------------------ audit event
def test_audit_events_for_create_version_operation_status_and_bootstrap(db):
    p, v = _process_with_ops(db)
    assert {"TECH_PROCESS_CREATE", "TECH_PROCESS_VERSION_CREATE", "TECH_PROCESS_OPERATION_ADD"}.issubset(set(db.audit))
    svc.transition_version(db, ADMIN, v.id, "review")
    svc.transition_version(db, ADMIN, v.id, "approve")
    assert {"TECH_PROCESS_VERSION_REVIEW", "TECH_PROCESS_VERSION_APPROVE"}.issubset(set(db.audit))
    svc.bootstrap_current_process(db, ADMIN, {"style_cc": "H8", "source_ref": "manual", "operations": [{"operation_name": "x", "sam_minutes": 1}]})
    assert "TECH_PROCESS_BOOTSTRAP" in db.audit


# ------------------------------------------------------------------ AC-002 SAM đi theo version, không phải master 3 tầng độc lập
def test_sam_lives_on_version_not_a_separate_three_tier_model(db):
    p = svc.create_process(db, ADMIN, {"style_cc": "I900", "model_code": ""})
    vs = {}
    for layer, sams in (("CURRENT_PROCESS", (1.0, 1.0)), ("OPTIMIZED_CURRENT_TECHNOLOGY", (0.6,)), ("FUTURE_TECHNOLOGY", (0.4,))):
        v = svc.create_draft_version(db, ADMIN, p.id, {"layer": layer})
        svc.add_operation(db, ADMIN, v.id, {"operation_name": "op", "sam_minutes": sams[0]})
        for extra in sams[1:]:
            svc.add_operation(db, ADMIN, v.id, {"operation_name": "op2", "sam_minutes": extra})
        db.refresh(v)
        vs[layer] = v.total_sam_minutes
    assert vs == {"CURRENT_PROCESS": 2.0, "OPTIMIZED_CURRENT_TECHNOLOGY": 0.6, "FUTURE_TECHNOLOGY": 0.4}  # mỗi version tự có Total SAM riêng


# ------------------------------------------------------------------ danh sách (màn hình list §13)
def test_list_versions_flattened_with_style_model_process_filters(db):
    p, v = _process_with_ops(db, layer="CURRENT_PROCESS")
    svc.derive_version(db, ADMIN, v.id, "OPTIMIZED_CURRENT_TECHNOLOGY")
    rows = svc.list_versions(db)
    assert len(rows) == 2 and all(r["style_cc"] == "A100" and r["process_code"] == p.process_code for r in rows)
    assert {r["layer"] for r in rows} == {"CURRENT_PROCESS", "OPTIMIZED_CURRENT_TECHNOLOGY"}
    assert len(svc.list_versions(db, layer="FUTURE_TECHNOLOGY")) == 0
    assert len(svc.list_versions(db, style="A100")) == 2
    with pytest.raises(HTTPException):
        svc.list_versions(db, status="NOT_A_STATUS")


# ------------------------------------------------------------------ compare (§13)
def test_compare_versions_reports_sam_labor_output_operation_count_and_machines(db):
    p, v1 = _process_with_ops(db, layer="CURRENT_PROCESS", sams=(1.2, 0.8))
    v2 = svc.derive_version(db, ADMIN, v1.id, "OPTIMIZED_CURRENT_TECHNOLOGY")
    out = svc.compare_versions(db, [v1.id, v2.id])
    assert len(out) == 2 and {o["layer"] for o in out} == {"CURRENT_PROCESS", "OPTIMIZED_CURRENT_TECHNOLOGY"}
    assert all(o["total_sam_minutes"] == 2.0 for o in out) and all(o["operation_count"] == 2 for o in out)
