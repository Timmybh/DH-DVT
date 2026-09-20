from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.resources import CapacityDefinition, MachineCapacity
from app.services import resource_service as rs
from app.services.calendar import CalendarResolver, Rule
from app.services.formula import to_serial
from app.services.planning_engine import apply_ops, recheck

ADMIN = SimpleNamespace(username="admin", role="ADMIN")
CAL = CalendarResolver([Rule("COMPANY", "", "WEEKLY_OFF", weekday=6)])


def d(id, cap, factory="", line="", style="", model="", version=1, status="ACTIVE", frm=None, to=None, source="IE"):
    return {"id": id, "capacity_per_day": cap, "factory_code": factory, "line": line, "style_cc": style, "model_code": model, "version": version, "status": status,
            "effective_from": frm, "effective_to": to, "source": source}


def test_most_specific_definition_wins():
    defs = [d(1, 1000, factory="XN1"), d(2, 1100, factory="XN1", style="S1"), d(3, 1200, factory="XN1", line="7", style="S1"), d(4, 900)]
    pick = lambda **kw: rs.resolve_capacity(defs, kw.get("f", "XN1"), kw.get("l", "7"), kw.get("s", "S1"), kw.get("m", ""), None)["id"]  # noqa: E731
    assert pick() == 3                          # XN + chuyền + style
    assert pick(l="8") == 2                     # chuyền khác -> XN + style
    assert pick(s="S9") == 1                    # style khác -> chỉ XN
    assert pick(f="XN2", s="S9") == 4           # mặc định toàn công ty
    assert rs.resolve_capacity([d(1, 5, line="7")], "XN1", "8", "S", "", None) is None  # khai báo chuyền 7 thì không áp cho chuyền 8


def test_effective_dates_status_and_version_tiebreak():
    defs = [d(1, 100, style="S", frm=date(2026, 9, 1), to=date(2026, 9, 30)), d(2, 200, style="S", frm=date(2026, 10, 1)), d(3, 999, style="S", status="RETIRED")]
    at = lambda day: rs.resolve_capacity(defs, "XN1", "1", "S", "", day)  # noqa: E731
    assert at(date(2026, 9, 15))["id"] == 1 and at(date(2026, 10, 5))["id"] == 2 and at(date(2026, 8, 1)) is None
    same = [d(1, 100, style="S", version=1), d(2, 150, style="S", version=2)]
    assert rs.resolve_capacity(same, "XN1", "1", "S", "", None)["id"] == 2  # cùng độ đặc thù -> phiên bản cao hơn


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[CapacityDefinition.__table__, MachineCapacity.__table__])
    s = sessionmaker(bind=engine)()
    events = []
    monkeypatch.setattr(rs, "write_audit", lambda action, **kw: events.append(action))
    s.audit = events  # type: ignore[attr-defined]
    yield s
    s.close()


def test_revise_creates_new_version_and_retires_old(db):
    c = rs.create_capacity(db, ADMIN, {"factory_code": "XN1", "line": "7", "style_cc": "S1", "capacity_per_day": 1000, "source": "IE"})
    new = rs.revise_capacity(db, ADMIN, c.id, {"capacity_per_day": 1250})
    db.refresh(c)
    assert (c.status, c.effective_to is not None) == ("RETIRED", True) and (new.status, new.version, new.capacity_per_day) == ("ACTIVE", 2, 1250)
    assert [x["id"] for x in rs.load_capacity_defs(db)] == [new.id]
    with pytest.raises(HTTPException) as e:
        rs.revise_capacity(db, ADMIN, c.id, {"capacity_per_day": 1})  # bản đã RETIRED không sửa được
    assert e.value.status_code == 409
    assert {"CAPACITY_CREATE", "CAPACITY_REVISE"} <= set(db.audit)


@pytest.mark.parametrize("bad", [{"capacity_per_day": 0}, {"capacity_per_day": 10, "source": "GUESS"}, {"capacity_per_day": 10, "effective_from": date(2026, 2, 1), "effective_to": date(2026, 1, 1)}])
def test_invalid_capacity_rejected(db, bad):
    with pytest.raises(HTTPException) as e:
        rs.create_capacity(db, ADMIN, bad)
    assert e.value.status_code == 422


def test_machine_capacity_validation(db):
    with pytest.raises(HTTPException):
        rs.save_machine_capacity(db, ADMIN, {"factory_code": "XN1", "line": "7", "machine_type": "MAN", "efficiency": 1.5})
    with pytest.raises(HTTPException):
        rs.save_machine_capacity(db, ADMIN, {"factory_code": "XN1", "line": "7", "machine_type": "MAN", "maintenance_status": "BROKEN"})
    m = rs.save_machine_capacity(db, ADMIN, {"factory_code": "XN1", "line": "7", "machine_type": "MAN", "quantity": 3, "efficiency": 0.8, "nominal_output_per_day": 1000})
    assert m.quantity == 3


def row(uid="a", xn="XN1", line="7", style="S1", cap=1000, worker=36, seq=1, begin=None, end=None, qty=1000):
    b = {"row_uid": uid, "sequence": seq, "origin": "EXISTING", "source_key": uid, "source_plan_row_id": None, "factory_code": xn, "primary_line": line, "line_raw": line,
         "line_assignments": [line], "transfer": None, "po_number": f"PO-{uid}", "style_cc": style, "model_code": "", "description": "", "customer": "C", "sport": "", "season": "",
         "quantity": qty, "capacity": cap, "total_day": qty / cap, "begin_prod_date": begin, "end_prod_date": end, "warehouse_date": None, "chd": None, "note": "",
         "extra": {"ref": {"worker": worker}}}
    if begin:
        b["extra"]["serial"] = {"begin_prod_date": to_serial(begin), "end_prod_date": to_serial(end)}
    return b


def test_recheck_flags_capacity_labor_and_machine_problems():
    res = rs.Resources(
        cap_defs=[d(1, 1200, factory="XN1", line="7", style="S1", source="IE", version=3)],
        labor={("XN1", "7"): 30},
        requirements={"S1": [("MAN", 2)]},
        machines={("XN1", "7", "MAN"): 1}, machine_output={("XN1", "7", "MAN"): 800}, as_of=date(2026, 9, 1),
    )
    r = row(cap=1000, worker=36, begin=date(2026, 9, 14), end=date(2026, 9, 15))
    out = recheck([r], CAL, {"XN1"}, res.check)
    assert {"CAPACITY_DEFINITION_MISMATCH", "LABOR_SHORTAGE", "MACHINE_SHORTAGE"} <= set(out["by_rule"])
    assert any("IE v3" in i["message"] for i in out["issues"] if i["rule_code"] == "CAPACITY_DEFINITION_MISMATCH")
    ok = rs.Resources(cap_defs=[d(1, 1000, factory="XN1", line="7", style="S1")], labor={("XN1", "7"): 40}, requirements={"S1": [("MAN", 1)]}, machines={("XN1", "7", "MAN"): 2},
                      machine_output={("XN1", "7", "MAN"): 1500})
    out2 = recheck([row(cap=1000, worker=36, begin=date(2026, 9, 14), end=date(2026, 9, 14))], CAL, {"XN1"}, ok.check)
    assert not ({"CAPACITY_DEFINITION_MISMATCH", "LABOR_SHORTAGE", "MACHINE_SHORTAGE", "MACHINE_BOTTLENECK"} & set(out2["by_rule"]))


def test_machine_bottleneck_and_down_status():
    res = rs.Resources(requirements={"S1": [("MAN", 1)]}, machines={("XN1", "7", "MAN"): 2}, machine_output={("XN1", "7", "MAN"): 600})
    assert "MACHINE_BOTTLENECK" in [c for *_x, c in rs.check_row_resources(res, row(cap=1000))]
    res.machine_status[("XN1", "7", "MAN")] = "DOWN"
    assert "MACHINE_UNAVAILABLE" in [c for *_x, c in rs.check_row_resources(res, row(cap=1000))]


def test_unplanned_without_capacity_gets_it_from_definition():
    src = {"id": 1, "source_key": "k", "po_number": "P", "style_cc": "S1", "model_code": "", "description": "", "customer": "C", "sport": "", "season": "", "quantity": 900,
           "capacity": None, "chd": None, "factory_code": "XN1", "note": "", "ref": {}}
    res = rs.Resources(cap_defs=[d(7, 450, factory="XN1", style="S1", source="LEAN", version=2)])
    ops = [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t1", "sourceId": 1, "factory": "XN1", "line": "3", "afterRowUid": None}]
    rows, _ = apply_ops([], {1: src}, ops, CAL, {"XN1"}, None, res.capacity_for)
    new = rows[0]
    assert new["capacity"] == 450 and new["total_day"] == pytest.approx(2.0)
    assert new["extra"]["capacity_source"] == {"definition_id": 7, "version": 2, "source": "LEAN"}


def test_release_schedule_returns_capacity_when_line_work_ends():
    mon = date(2026, 9, 14)
    rows = [
        row("a", line="1", worker=30, seq=1, begin=date(2026, 9, 14), end=date(2026, 9, 16)),  # giữ 30 người T2–T4 -> rảnh thứ Năm
        row("b", line="1", worker=20, seq=2, begin=date(2026, 9, 17), end=date(2026, 9, 17)),  # nối tiếp ngay -> chỉ rảnh phần chênh 10
        row("c", xn="XN2", line="5", worker=12, seq=1, begin=date(2026, 9, 14), end=date(2026, 9, 14)),
    ]
    out = rs.release_schedule(rows, mon, {"S1": [("MAN", 3)]})
    by = {f["factory"]: f for f in out["factories"]}
    l1 = {c["date"]: c for c in by["XN1"]["lines"][0]["days"]}
    assert l1["2026-09-17"]["labor"] == 10.0 and l1["2026-09-18"]["labor"] == 20.0  # T5: 30→20; T6: 20→0
    assert l1["2026-09-17"]["machine"] == 0.0 and l1["2026-09-18"]["machine"] == 3.0  # máy: 3 giữ đến T5, trả T6
    assert {c["date"]: c["labor"] for c in by["XN2"]["lines"][0]["days"]}["2026-09-15"] == 12.0
    assert by["XN1"]["totals"][4]["labor"] == 20.0  # tổng XN ngày T6
    assert out["days"][0] == "2026-09-14" and len(out["days"]) == 7


def test_labor_check_ignores_rows_that_already_finished():
    res = rs.Resources(labor={("XN1", "7"): 20}, as_of=date(2026, 9, 20))
    past = row(worker=36, begin=date(2026, 8, 1), end=date(2026, 8, 5))
    live = row(worker=36, begin=date(2026, 9, 18), end=date(2026, 9, 25))
    assert "LABOR_SHORTAGE" not in [c for *_x, c in rs.check_row_resources(res, past)]
    assert "LABOR_SHORTAGE" in [c for *_x, c in rs.check_row_resources(res, live)]
