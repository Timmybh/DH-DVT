"""Task 2 (Issue #5) — Live ERP QTCN Import -> Current Process. Test service layer với nguồn ERP giả lập
(dict rows đúng shape cột thật đã khảo sát trên Issue #5), KHÔNG kết nối SQL Server thật. Live read-only smoke test
riêng (không chạy trong CI) xác nhận kết nối thật + so khớp dữ liệu."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.permissions import permissions_for
from app.db.session import Base
from app.models.data import SyncRun, SyncRunItem
from app.models.erp_sync import MachineCrosswalk, TechProcessSyncException
from app.models.resources import MachineModel, MachineType
from app.models.technology_process import TechnologyProcess, TechnologyProcessOperation, TechnologyProcessVersion
from app.services import erp_qtcn_sync as svc
from app.services import technology_process_service as tps

ADMIN = SimpleNamespace(username="admin", role="ADMIN", id=1)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            MachineType.__table__, MachineModel.__table__, TechnologyProcess.__table__, TechnologyProcessVersion.__table__,
            TechnologyProcessOperation.__table__, MachineCrosswalk.__table__, TechProcessSyncException.__table__,
            SyncRun.__table__, SyncRunItem.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    events: list[str] = []
    monkeypatch.setattr(tps, "write_audit", lambda action, **kw: events.append(action))
    monkeypatch.setattr(svc, "write_audit", lambda action, **kw: events.append(action))
    s.audit = events  # type: ignore[attr-defined]
    s.add(MachineType(code="1", name="1K"))
    s.add(MachineType(code="7", name="KANSAI"))
    s.commit()
    yield s
    s.close()


def _seed_crosswalk(db):
    db.add(MachineCrosswalk(source_system="ERP_QTCN", source_equipment_code="TB0011", source_equipment_name="1K", machine_type_code="1", match_type="EXACT"))
    db.commit()


def _master(id_, mahang, mua="SS27", ten_chung_loai="Áo", sam=0, tgian=100, solaodong=10):
    return {"Id": id_, "MaHang": mahang, "Mua": mua, "TenChungLoai": ten_chung_loai, "SAM": sam, "TongThoiGian": tgian, "SoLaoDong": solaodong}


def _op(id_, idqtcn, stt, congdoan_id, ten="Vắt sổ", idthietbi=11, tenthietbi="1K", phienban=0, trangthai="Đã ban hành", tgtt=10.0):
    return {
        "Id": id_, "IdQTCN": idqtcn, "STT": stt, "IdCongDoan": congdoan_id, "TenCongDoan": ten, "IdThietBi": idthietbi, "TenThietBi": tenthietbi,
        "SoLaoDong": 1.5, "ThoiGianThucTe": tgtt, "ThoiGianThietKe": tgtt + 1, "ThoiGianThietKeHeSo": tgtt + 2, "HeSo": 1.1,
        "PhienBan": phienban, "TrangThai": trangthai,
    }


def _source(master_rows, detail_rows, congdoan_catalog=None, thietbi_catalog=None, out_of_scope=0):
    by_idqtcn: dict = {}
    for d in detail_rows:
        by_idqtcn.setdefault(d["IdQTCN"], []).append(d)
    return {
        "master": master_rows, "detail_by_idqtcn": by_idqtcn, "congdoan_catalog": congdoan_catalog or {100: "CD100"},
        "thietbi_catalog": thietbi_catalog or {11: "TB0011", 48: "TB0048"}, "out_of_scope_source_row_count": out_of_scope,
    }


class _FakeConnCM:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


class _FakeEngine:
    def connect(self):
        return _FakeConnCM()


def _patch_source(monkeypatch, source: dict):
    monkeypatch.setattr(svc, "sqlserver_configured", lambda: True)
    monkeypatch.setattr(svc, "get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(svc, "read_source", lambda conn: source)


# ------------------------------------------------------------------ mục 🆕 — chọn PhienBan đã ban hành, không mù MAX(PhienBan)
def test_select_published_phienban_picks_highest_published_not_max_phienban():
    rows = [
        _op(1, 10, 1, 100, phienban=0, trangthai="Đã ban hành"),
        _op(2, 10, 1, 100, phienban=1, trangthai="MoiTao"),  # bản mới hơn nhưng đang sửa dở
    ]
    pb, cat = svc.select_published_phienban(rows)
    assert pb == 0 and cat is None


def test_select_published_phienban_no_published_at_all():
    rows = [_op(1, 10, 1, 100, phienban=0, trangthai="MoiTao")]
    pb, cat = svc.select_published_phienban(rows)
    assert pb is None and cat == "NO_PUBLISHED_VERSION"


def test_select_published_phienban_mixed_status_same_phienban_is_inconsistent():
    rows = [_op(1, 10, 1, 100, phienban=0, trangthai="Đã ban hành"), _op(2, 10, 2, 100, phienban=0, trangthai="MoiTao")]
    pb, cat = svc.select_published_phienban(rows)
    assert pb is None and cat == "INCONSISTENT_VERSION_STATUS"


# ------------------------------------------------------------------ sequence
def test_validate_sequence_missing_and_duplicate():
    assert svc.validate_sequence([_op(1, 10, None, 100)]) == "MISSING_SEQUENCE"
    assert svc.validate_sequence([_op(1, 10, 1, 100), _op(2, 10, 1, 100)]) == "DUPLICATE_SEQUENCE"
    assert svc.validate_sequence([_op(1, 10, 1, 100), _op(2, 10, 2, 100)]) is None


# ------------------------------------------------------------------ machine resolve (khóa theo MaThietBi — business code, BR-201)
def test_resolve_machine_man_is_not_exception():
    code, cat = svc.resolve_machine({}, "TB0048", "MAN")
    assert code is None and cat is None


def test_resolve_machine_exact_crosswalk_hits():
    code, cat = svc.resolve_machine({"TB0011": "1"}, "TB0011", "1K")
    assert code == "1" and cat is None


def test_resolve_machine_unmapped_is_soft_exception():
    code, cat = svc.resolve_machine({}, "TB0044", "SIGMA")
    assert code is None and cat == "UNMAPPED_MACHINE_TYPE"


# ------------------------------------------------------------------ AC-201/202 — preview & apply đúng luồng chính (NEW)
def test_preview_does_not_write_anything(db, monkeypatch):
    source = _source([_master(1, "A100")], [_op(1, 1, 1, 100)])
    _patch_source(monkeypatch, source)
    out = svc.preview(db, ADMIN)
    assert out["counts"]["NEW"] == 1
    assert db.query(TechnologyProcess).count() == 0  # preview không ghi gì (AC-211)
    assert db.query(TechnologyProcessVersion).count() == 0


def test_apply_creates_process_version_operation_with_null_sam_and_operator_count(db, monkeypatch):
    _seed_crosswalk(db)
    source = _source([_master(1, "a100")], [_op(1, 1, 1, 100, idthietbi=11, tenthietbi="1K")], congdoan_catalog={100: "CD100"})
    _patch_source(monkeypatch, source)
    result = svc.apply(db, ADMIN)
    assert result["created"] == 1 and result["run"].status == "SUCCEEDED"
    p = db.query(TechnologyProcess).one()
    assert p.style_cc == "A100" and p.model_code == ""  # canonical (BR-202), model rỗng (Issue #5 review vòng 1 mục 3)
    v = db.query(TechnologyProcessVersion).one()
    assert v.layer == "CURRENT_PROCESS" and v.status == "DRAFT" and v.source_type == "ERP"  # BR-204/BR-207 — không auto approve
    assert v.total_sam_minutes is None and v.sam_status == "INCOMPLETE"  # BR B.10 — Task 2 không map SAM
    op = db.query(TechnologyProcessOperation).one()
    assert op.sam_minutes is None and op.operator_count is None  # BR B.10/B.11 — không suy đoán, giữ null = "không biết"
    assert op.machine_type_code == "1"  # crosswalk EXACT áp dụng đúng


def test_apply_same_snapshot_twice_is_no_op_no_duplicate_version(db, monkeypatch):
    source = _source([_master(1, "B200")], [_op(1, 1, 1, 100)])
    _patch_source(monkeypatch, source)
    svc.apply(db, ADMIN)
    r2 = svc.apply(db, ADMIN)
    assert r2["created"] == 0 and r2["no_change"] == 1  # V-207 — same fingerprint không tạo duplicate
    assert db.query(TechnologyProcessVersion).count() == 1


def test_apply_changed_source_creates_new_version_keeps_old(db, monkeypatch):
    source1 = _source([_master(1, "C300")], [_op(1, 1, 1, 100, ten="Vắt sổ")])
    _patch_source(monkeypatch, source1)
    svc.apply(db, ADMIN)
    v1_id = db.query(TechnologyProcessVersion).one().id

    source2 = _source([_master(1, "C300")], [_op(1, 1, 1, 100, ten="Vắt sổ ĐÃ SỬA")])  # nội dung đổi -> fingerprint đổi
    _patch_source(monkeypatch, source2)
    r2 = svc.apply(db, ADMIN)
    assert r2["created"] == 1  # V-208 — thay đổi phải tạo version mới
    versions = db.query(TechnologyProcessVersion).order_by(TechnologyProcessVersion.version_no).all()
    assert len(versions) == 2 and versions[0].id == v1_id  # version cũ vẫn còn (AC-207), không overwrite


# ------------------------------------------------------------------ exception categories
def test_ambiguous_process_two_masters_same_style_and_season(db, monkeypatch):
    source = _source([_master(1, "D400", mua="SS27"), _master(2, "D400", mua="SS27")], [_op(1, 1, 1, 100), _op(2, 2, 1, 100)])
    _patch_source(monkeypatch, source)
    out = svc.preview(db, ADMIN)
    assert out["exception_by_category"].get("AMBIGUOUS_PROCESS") == 2
    r = svc.apply(db, ADMIN)
    assert r["created"] == 0
    assert db.query(TechProcessSyncException).filter_by(category="AMBIGUOUS_PROCESS").count() == 2


def test_same_style_different_season_is_not_ambiguous_creates_two_versions(db, monkeypatch):
    """Issue #5 review vòng 1 mục 2 — nhiều mùa của cùng Style = nhiều Version của CÙNG TechnologyProcess, không AMBIGUOUS_PROCESS."""
    source = _source([_master(1, "E500", mua="SS26"), _master(2, "E500", mua="AW26")], [_op(1, 1, 1, 100), _op(2, 2, 1, 100)])
    _patch_source(monkeypatch, source)
    r = svc.apply(db, ADMIN)
    assert r["created"] == 2
    assert db.query(TechnologyProcess).count() == 1  # cùng 1 TechnologyProcess (style_cc="E500")
    assert db.query(TechnologyProcessVersion).count() == 2


def test_missing_style_exception(db, monkeypatch):
    source = _source([_master(1, "")], [])
    _patch_source(monkeypatch, source)
    out = svc.preview(db, ADMIN)
    assert out["exception_by_category"].get("MISSING_STYLE") == 1


def test_duplicate_sequence_and_unmapped_operation_soft_exceptions(db, monkeypatch):
    # duplicate STT -> chặn cả style (exception cứng)
    source = _source([_master(1, "F600")], [_op(1, 1, 1, 100), _op(2, 1, 1, 100)])
    _patch_source(monkeypatch, source)
    out = svc.preview(db, ADMIN)
    assert out["exception_by_category"].get("DUPLICATE_SEQUENCE") == 1

    # IdCongDoan không khớp catalog -> soft exception, vẫn import được operation
    source2 = _source([_master(2, "G700")], [_op(3, 2, 1, 999)], congdoan_catalog={100: "CD100"})
    _patch_source(monkeypatch, source2)
    out2 = svc.preview(db, ADMIN)
    assert out2["counts"]["NEW"] == 1  # vẫn NEW, không bị chặn
    assert out2["soft_exception_by_category"].get("UNMAPPED_OPERATION") == 1
    r2 = svc.apply(db, ADMIN)
    assert r2["created"] == 1
    op = db.query(TechnologyProcessOperation).filter_by(operation_code="").one()
    assert op.operation_name  # vẫn giữ tên thật dù không map được catalog


# ------------------------------------------------------------------ out-of-scope (IdQTCN=-1) không vào exception queue
def test_out_of_scope_source_rows_not_counted_as_exception(db, monkeypatch):
    source = _source([_master(1, "H800")], [_op(1, 1, 1, 100)], out_of_scope=1240)
    _patch_source(monkeypatch, source)
    out = svc.preview(db, ADMIN)
    assert out["out_of_scope_source_row_count"] == 1240
    assert sum(out["exception_by_category"].values()) == 0


# ------------------------------------------------------------------ BR-216/217 — atomic theo từng style, 1 style lỗi không hỏng cả run
def test_one_style_failure_does_not_block_other_styles(db, monkeypatch):
    source = _source([_master(1, "I900"), _master(2, "J000")], [_op(1, 1, 1, 100), _op(2, 2, 1, 100)])
    _patch_source(monkeypatch, source)
    real_apply_one = svc._apply_one
    calls = {"n": 0}

    def flaky(db_, user, run_id, item, congdoan_catalog, thietbi_catalog, snapshot_at):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_apply_one(db_, user, run_id, item, congdoan_catalog, thietbi_catalog, snapshot_at)

    monkeypatch.setattr(svc, "_apply_one", flaky)
    r = svc.apply(db, ADMIN)
    assert r["failed"] == 1 and r["created"] == 1  # style thứ 2 vẫn thành công
    assert r["run"].status == "PARTIAL"
    assert db.query(TechnologyProcess).count() == 1  # style lỗi không để lại process/version dở dang


# ------------------------------------------------------------------ permission (đúng đề xuất Issue #5 mục 9)
def test_permission_mapping_preview_apply_manage():
    assert "sync.view" in permissions_for("ADMIN") and "sync.run" in permissions_for("ADMIN") and "technology_process.manage" in permissions_for("ADMIN")
    assert "sync.run" not in permissions_for("PLANNER") and "sync.view" in permissions_for("PLANNER")
    assert "sync.run" not in permissions_for("VIEWER")


# ------------------------------------------------------------------ crosswalk seed (Issue #5 review vòng 2 mục 4) — chỉ 6 EXACT
def test_seed_machine_crosswalk_is_idempotent_and_exact_only(db):
    svc.seed_machine_crosswalk(db)
    assert db.query(MachineCrosswalk).count() == 6
    assert all(c.match_type == "EXACT" for c in db.query(MachineCrosswalk).all())
    svc.seed_machine_crosswalk(db)  # chạy lại không tạo duplicate
    assert db.query(MachineCrosswalk).count() == 6


# ------------------------------------------------------------------ PR #6 review mục 1 — fingerprint KHÔNG phụ thuộc internal ID, CÓ gồm Master SAM/SOT/Labor
def test_fingerprint_ignores_internal_ids_changing_ma_cong_doan_ma_thiet_bi_only_stays_no_change(db, monkeypatch):
    """Đổi Master.Id/Detail.Id/IdCongDoan/IdThietBi (internal, có thể đổi khi ERP migrate) nhưng giữ nguyên MaCongDoan/
    MaThietBi/nội dung nghiệp vụ -> vẫn phải là NO_CHANGE, không tạo version giả (BR-201)."""
    source1 = _source([_master(1, "K100")], [_op(1, 1, 1, 100, idthietbi=11, tenthietbi="1K")], congdoan_catalog={100: "CD100"}, thietbi_catalog={11: "TB0011"})
    _patch_source(monkeypatch, source1)
    svc.apply(db, ADMIN)

    # Master.Id, Detail.Id, IdCongDoan, IdThietBi đều đổi — nhưng MaCongDoan/MaThietBi (qua catalog) và nội dung giữ nguyên
    source2 = _source(
        [_master(999, "K100")], [_op(888, 999, 1, 777, idthietbi=666, tenthietbi="1K")],
        congdoan_catalog={777: "CD100"}, thietbi_catalog={666: "TB0011"},
    )
    _patch_source(monkeypatch, source2)
    r2 = svc.apply(db, ADMIN)
    assert r2["created"] == 0 and r2["no_change"] == 1
    assert db.query(TechnologyProcessVersion).count() == 1


def test_fingerprint_changes_when_master_sam_sot_labor_changes_even_if_operations_same(db, monkeypatch):
    source1 = _source([_master(1, "K200", sam=10, tgian=100, solaodong=5)], [_op(1, 1, 1, 100)])
    _patch_source(monkeypatch, source1)
    svc.apply(db, ADMIN)

    source2 = _source([_master(1, "K200", sam=99, tgian=100, solaodong=5)], [_op(1, 1, 1, 100)])  # chỉ đổi SAM
    _patch_source(monkeypatch, source2)
    r2 = svc.apply(db, ADMIN)
    assert r2["created"] == 1  # Master.SAM đổi -> fingerprint phải đổi dù operation giữ nguyên
    assert db.query(TechnologyProcessVersion).count() == 2


# ------------------------------------------------------------------ PR #6 review mục 2 — atomic khi TechnologyProcess chưa tồn tại
def test_apply_one_failure_after_process_created_leaves_no_orphan_process(db, monkeypatch):
    source = _source([_master(1, "L300")], [_op(1, 1, 1, 100)])
    _patch_source(monkeypatch, source)
    items = svc.classify_all(db, source)
    item = next(it for it in items if it["status"] == "NEW")

    real_commit = db.commit
    calls = {"n": 0}

    def flaky_commit():
        calls["n"] += 1
        raise RuntimeError("boom-after-process-created")

    monkeypatch.setattr(db, "commit", flaky_commit)
    with pytest.raises(RuntimeError):
        svc._apply_one(db, ADMIN, 0, item, source["congdoan_catalog"], source["thietbi_catalog"], svc.utcnow())
    monkeypatch.setattr(db, "commit", real_commit)
    db.rollback()
    assert db.query(TechnologyProcess).count() == 0  # process vừa add+flush (chưa commit) phải rollback sạch, không mồ côi
    assert db.query(TechnologyProcessVersion).count() == 0


# ------------------------------------------------------------------ PR #6 review mục 3 — orphan Detail khác -1 -> INVALID_SOURCE_RELATION
def test_orphan_detail_not_minus_one_becomes_invalid_source_relation(db, monkeypatch):
    source = _source([_master(1, "M400")], [_op(1, 1, 1, 100), _op(2, 14, 1, 100)])  # IdQTCN=14 không có Master nào
    _patch_source(monkeypatch, source)
    out = svc.preview(db, ADMIN)
    assert out["exception_by_category"].get("INVALID_SOURCE_RELATION") == 1
    assert out["out_of_scope_source_row_count"] == 0  # khác voi IdQTCN=-1 (out-of-scope), đây la exception thật


# ------------------------------------------------------------------ PR #6 review mục 5 — SyncRunItem traceability, kể cả NO_CHANGE
def test_sync_run_item_traces_every_outcome_including_no_change(db, monkeypatch):
    source = _source([_master(1, "N500")], [_op(1, 1, 1, 100)])
    _patch_source(monkeypatch, source)
    r1 = svc.apply(db, ADMIN)
    items_created = db.query(SyncRunItem).filter_by(run_id=r1["run"].id).all()
    assert any(i.kind in ("NEW",) for i in items_created)

    r2 = svc.apply(db, ADMIN)  # lần 2: NO_CHANGE
    items_no_change = db.query(SyncRunItem).filter_by(run_id=r2["run"].id).all()
    assert any(i.kind == "NO_CHANGE" and "N500" in i.source_key for i in items_no_change)


# ------------------------------------------------------------------ PR #6 review mục 6 — source_snapshot_at + audit Preview/Apply
def test_version_has_source_snapshot_at_and_apply_preview_are_audited(db, monkeypatch):
    source = _source([_master(1, "O600")], [_op(1, 1, 1, 100)])
    _patch_source(monkeypatch, source)
    svc.preview(db, ADMIN)
    assert "TECH_PROCESS_ERP_SYNC_PREVIEW" in db.audit  # type: ignore[attr-defined]

    svc.apply(db, ADMIN)
    assert "TECH_PROCESS_ERP_SYNC_APPLY" in db.audit  # type: ignore[attr-defined]
    v = db.query(TechnologyProcessVersion).one()
    assert v.assumptions_json.get("source_snapshot_at")  # BR-203
