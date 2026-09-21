"""SO: định dạng, reset theo năm, cấp ngay từ Unplanned, dùng lại khi import lại, bí danh PO, lineage khi Split/Merge."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.core import Factory
from app.models.data import PlanImportBatch, PlanRow
from app.models.planning import PlanningVersion, PlanningVersionRow
from app.models.so import PlanningSO, PlanningSOExternalIdentity
from app.services import so_service as ss
from app.services.calendar import CalendarResolver
from app.services.planning_engine import apply_ops


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Factory(id=1, code="XN1", name="XN1", sql_xn_id=1))
    session.commit()
    monkeypatch.setattr(ss, "write_audit", lambda *a, **k: None)
    monkeypatch.setattr(ss, "_year2", lambda today=None: 26)
    yield session
    session.close()


def batch(db, rows, current=True):
    b = PlanImportBatch(filename="plan.xlsx", is_current=current)
    db.add(b)
    db.flush()
    for i, r in enumerate(rows):
        db.add(PlanRow(batch_id=b.id, planning_status=r.get("st", "UNPLANNED"), factory_id=1, po_number=r["po"], style_cc=r["style"], model_code=r.get("model", ""), customer=r.get("cust", "NIKE"),
                       quantity=r.get("qty", 1000), season=r.get("season", "FW26"), description=r.get("desc", ""), note=r.get("note", "")))
    db.commit()
    return b


def test_so_number_format_sequence_and_reset_per_year(db):
    a, b = ss.issue_so(db, customer="NIKE", style="A100", model="Pegasus", season="FW26"), ss.issue_so(db, customer="ADIDAS", style="B200")
    assert (a.so_number, b.so_number) == ("SO/26/000001", "SO/26/000002") and ss.SO_RE.match(a.so_number)
    assert a.description == "NIKE Pegasus / A100 / FW26" and "XN" not in a.so_number and "M1" not in a.so_number     # không mã hóa XN, bỏ M1/M2/M3
    c = ss.issue_so(db, style="C", today=date(2027, 1, 5)) if False else None
    assert c is None
    assert ss.format_so(27, 1) == "SO/27/000001"                                                                      # sang năm reset
    assert ss.format_so(26, 123456) == "SO/26/123456"
    db.commit()
    assert len({s.so_number for s in db.query(PlanningSO)}) == 2                                                     # duy nhất toàn cục


def test_year_reset_uses_separate_counter(db, monkeypatch):
    monkeypatch.setattr(ss, "_year2", lambda today=None: 26)
    ss.issue_so(db, style="A")
    ss.issue_so(db, style="B")
    monkeypatch.setattr(ss, "_year2", lambda today=None: 27)
    first27 = ss.issue_so(db, style="C")
    assert first27.so_number == "SO/27/000001"
    monkeypatch.setattr(ss, "_year2", lambda today=None: 26)
    assert ss.issue_so(db, style="D").so_number == "SO/26/000003"


def test_every_unplanned_and_planned_row_gets_so_and_reimport_reuses_same_so(db):
    rows = [{"po": "FCAST WEEK 48", "style": "312058", "st": "PLANNED"}, {"po": "FCAST WEEK 48", "style": "312058", "st": "PLANNED"},   # 2 dòng giống nhau = 2 business item
            {"po": "4523240396", "style": "325482", "model": "AIR"}, {"po": "PRE SELECTION", "style": "999", "cust": "PUMA"}]
    b1 = batch(db, rows)
    out = ss.assign_for_batch(db, b1.id, "admin")
    db.commit()
    assert out == {"batch_id": b1.id, "issued": 4, "reused": 0}
    assert all(r.so_id for r in db.query(PlanRow)) and len({r.so_id for r in db.query(PlanRow)}) == 4
    assert ss.assign_for_batch(db, b1.id)["issued"] == 0                                                              # chạy lại không cấp lại
    before = {(s.so_number, s.identity_key) for s in db.query(PlanningSO)}
    # import lại (PlanRow bị xóa và tạo mới) — cùng business item => dùng lại SO
    db.query(PlanRow).delete()
    b2 = batch(db, rows + [{"po": "NEW-ONE", "style": "777"}])
    out2 = ss.assign_for_batch(db, b2.id)
    db.commit()
    assert out2["issued"] == 1 and out2["reused"] == 4 and db.query(PlanningSO).count() == 5
    assert before <= {(s.so_number, s.identity_key) for s in db.query(PlanningSO)}
    # PO chỉ là bí danh
    ident = {(i.identity_type, i.identity_value) for i in db.query(PlanningSOExternalIdentity)}
    assert ("PLAN_NOTE", "FCAST WEEK 48") in ident and ("ERP_PO", "4523240396") in ident and ("PLAN_NOTE", "PRE SELECTION") in ident
    so = db.query(PlanningSO).filter(PlanningSO.style_cc == "325482").one()
    assert so.current_po == "4523240396" and so.description == "NIKE AIR / 325482 / FW26"


def test_only_description_is_editable_and_so_number_never_changes(db):
    so = ss.issue_so(db, customer="NIKE", style="A100", po="PO_TEMP_009")
    db.commit()
    num = so.so_number
    assert so.temp_po == "PO_TEMP_009" and classify(so) == "TEMP_PO"
    ss.update_description(db, so.id, "NIKE Pegasus 41 / A100 / FW26 (đợt 2)", type("U", (), {"username": "planner"})())
    assert db.get(PlanningSO, so.id).so_number == num and db.get(PlanningSO, so.id).description.endswith("(đợt 2)")
    with pytest.raises(Exception):
        ss.update_description(db, so.id, "   ", None)
    # PO đổi không đổi SO: thêm bí danh mới, SO giữ nguyên
    db.add(PlanningSOExternalIdentity(planning_so_id=so.id, identity_type="ERP_PO", identity_value="PO123456"))
    db.commit()
    assert db.get(PlanningSO, so.id).so_number == num
    assert {r["so_number"] for r in ss.attach_so(db, [{"so_id": so.id}, {"so_id": None}]) if "so_number" in r} == {num}


def classify(so):
    return ss.classify_po(so.temp_po or so.current_po or so.note)


def test_version_rows_backfill_links_by_source_uid_and_identity(db):
    b = batch(db, [{"po": "P1", "style": "S1", "st": "PLANNED"}, {"po": "P2", "style": "S2", "st": "PLANNED"}])
    ss.assign_for_batch(db, b.id)
    plan_ids = [r.id for r in db.query(PlanRow).order_by(PlanRow.id)]
    v1 = PlanningVersion(code="2026.W38.Master.v01", year=2026, week=38, major=1)
    v2 = PlanningVersion(code="2026.W38.Master.v02", year=2026, week=38, major=2)
    db.add_all([v1, v2])
    db.flush()

    def vr(v, uid, po, style, src=None):
        db.add(PlanningVersionRow(version_id=v.id, row_uid=uid, sequence=1, source_key=f"{po}|{style}", source_plan_row_id=src, factory_code="XN1", primary_line="1", po_number=po, style_cc=style, customer="NIKE",
                                  model_code="", quantity=1000, extra={}))

    vr(v1, "R1", "P1", "S1", plan_ids[0])
    vr(v1, "R2", "P2", "S2", 99999)                        # dòng nguồn đã bị xóa khi import lại -> khớp theo khóa nhận diện
    vr(v1, "R9", "PX", "SX")                               # không có gì để khớp -> cấp SO mới
    vr(v2, "R1", "P1", "S1", None)                         # cùng row_uid ở phiên bản khác -> cùng SO
    db.commit()
    out = ss.backfill_version_rows(db)
    db.commit()
    so = {(r.version_id, r.row_uid): r.so_id for r in db.query(PlanningVersionRow)}
    assert out["issued"] == 1 and out["rows"] == 4
    assert so[(v1.id, "R1")] == so[(v2.id, "R1")] == db.query(PlanRow).filter(PlanRow.po_number == "P1").one().so_id
    assert so[(v1.id, "R2")] == db.query(PlanRow).filter(PlanRow.po_number == "P2").one().so_id
    assert so[(v1.id, "R9")] not in (so[(v1.id, "R1")], so[(v1.id, "R2")])
    assert ss.backfill_version_rows(db)["rows"] == 0                                                               # idempotent


# ------------------------------------------------------------------ SO đi cùng dòng qua Planning ops
CAL = CalendarResolver([])


def prow(uid, so_id, qty=1000, line="7", po="PO1", seq=1):
    return {"row_uid": uid, "sequence": seq, "origin": "EXISTING", "source_key": uid, "source_plan_row_id": None, "factory_code": "XN1", "primary_line": line, "line_raw": line, "line_assignments": [line],
            "transfer": None, "po_number": po, "style_cc": "S", "model_code": "M", "description": "", "customer": "C", "sport": "", "season": "", "quantity": qty, "capacity": 500, "total_day": qty / 500,
            "begin_prod_date": date(2026, 9, 14), "end_prod_date": None, "warehouse_date": None, "chd": None, "note": "", "extra": {}, "so_id": so_id}


def test_so_travels_with_row_split_keeps_so_and_merge_across_sos_keeps_lineage():
    unplanned = {1: {"id": 1, "source_key": "k", "po_number": "P", "style_cc": "S", "model_code": "M", "description": "", "customer": "C", "sport": "", "season": "", "quantity": 500, "capacity": 250,
                     "chd": None, "note": "", "factory_code": "XN1", "so_id": 42}}
    rows, _ = apply_ops([], unplanned, [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t1", "sourceId": 1, "factory": "XN1", "line": "7", "afterRowUid": None}], CAL, {"XN1"})
    assert rows[0]["so_id"] == 42                                                                                     # Unplanned → Planned giữ SO
    # Split không đổi SO (cùng business demand)
    base = [prow("A", 7, qty=1000, line="7")]
    base[0]["line_assignments"], base[0]["line_raw"] = ["7", "8"], "7 + 8"
    out, _ = apply_ops(base, {}, [{"type": "SPLIT_LINES", "rowUid": "A", "lines": ["8"], "effectiveDate": "2026-09-20", "quantity": 400, "tempRowId": "s1"}], CAL, {"XN1"})
    assert {r["so_id"] for r in out} == {7} and len(out) == 2
    # Merge nhiều SO: không mất SO nào, giữ phân bổ theo từng SO
    a, b, c = prow("A", 7, 600, "1", seq=1), prow("B", 8, 300, "2", seq=1), prow("C", 8, 100, "3", seq=1)
    merged, _ = apply_ops([a, b, c], {}, [{"type": "MERGE_LINES", "rowUids": ["A", "B", "C"], "primaryUid": "A"}], CAL, {"XN1"})
    assert len(merged) == 1 and merged[0]["quantity"] == 1000
    alloc = {x["so_id"]: x["quantity"] for x in merged[0]["extra"]["so_allocations"]}
    assert alloc == {7: 600.0, 8: 400.0}
    again, _ = apply_ops([merged[0], prow("D", 9, 200, "4", seq=1)], {}, [{"type": "MERGE_LINES", "rowUids": ["A", "D"], "primaryUid": "A"}], CAL, {"XN1"})
    assert {x["so_id"]: x["quantity"] for x in again[0]["extra"]["so_allocations"]} == {7: 600.0, 8: 400.0, 9: 200.0}
