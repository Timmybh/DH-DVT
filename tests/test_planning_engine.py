from datetime import date

import pytest

from app.services.calendar import CalendarResolver, Rule
from app.services.planning_engine import (
    OpError,
    apply_ops,
    compare_versions,
    ops_hash,
    parse_line_notation,
    recheck,
    source_key,
)

CAL = CalendarResolver([Rule("COMPANY", "", "WEEKLY_OFF", weekday=6)])
FACTORIES = {"XN1", "XN2", "XN3"}


def row(uid, seq, xn="XN1", line="7", qty=1000, cap=500, begin=None, end=None, **kw):
    return {
        "row_uid": uid, "sequence": seq, "origin": "EXISTING", "source_key": uid, "source_plan_row_id": None,
        "factory_code": xn, "primary_line": line, "line_raw": line, "line_assignments": [line], "transfer": None,
        "po_number": f"PO-{uid}", "style_cc": "S", "model_code": "M", "description": "d", "customer": "C", "sport": "", "season": "",
        "quantity": qty, "capacity": cap, "total_day": qty / cap if cap else None,
        "begin_prod_date": begin, "end_prod_date": end, "warehouse_date": None, "chd": None, "note": "", "extra": {}, **kw,
    }


def unplanned(pid=1, xn="", qty=800, cap=400):
    return {"id": pid, "source_key": source_key("PO9", "S9", "M9", "CUST", qty), "po_number": "PO9", "style_cc": "S9", "model_code": "M9",
            "description": "new", "customer": "CUST", "sport": "", "season": "", "quantity": qty, "capacity": cap, "chd": None,
            "factory_code": xn, "note": ""}


def test_parse_line_notation_multi_line_and_transfer():
    assert parse_line_notation("4 + 5 + 9") == (["4", "5", "9"], None, "4 + 5 + 9")
    assert parse_line_notation("15+10")[0] == ["15", "10"]
    lines, transfer, display = parse_line_notation("2==>1")
    assert lines == ["2"] and display == "2 ==> 1"
    assert transfer["from"] == "2" and transfer["to"] == "1" and transfer["effective_date"] is None and transfer["status"] == "PLANNED"
    assert parse_line_notation("3A")[0] == ["3A"]
    assert parse_line_notation("") == ([], None, "")


def test_case_a_known_xn_inserts_and_autocalculates_from_previous_sequence():
    base = [row("a", 1, begin=date(2026, 9, 14), end=date(2026, 9, 18))]  # Thứ sáu 18/09
    ops = [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t1", "sourceId": 1, "factory": "XN1", "line": "7", "afterRowUid": "a"}]
    rows, changed = apply_ops(base, {1: unplanned()}, ops, CAL, FACTORIES)
    new = next(r for r in rows if r["origin"] == "DRAFT_NEW")
    assert (new["factory_code"], new["primary_line"], new["sequence"]) == ("XN1", "7", 2)
    assert new["begin_prod_date"] == date(2026, 9, 19)  # Thứ bảy = ngày làm việc kế tiếp
    assert new["total_day"] == 2.0 and new["end_prod_date"] == date(2026, 9, 21)  # bỏ Chủ nhật 20/09
    assert changed == {new["row_uid"]}


def test_case_b_unassigned_requires_factory_selection():
    with pytest.raises(OpError, match="Xí nghiệp"):
        apply_ops([], {1: unplanned(xn="")}, [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t", "sourceId": 1, "line": "7"}], CAL, FACTORIES)
    rows, _ = apply_ops([], {1: unplanned(xn="")}, [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t", "sourceId": 1, "factory": "XN2", "line": "3"}], CAL, FACTORIES)
    assert rows[0]["factory_code"] == "XN2" and rows[0]["begin_prod_date"] is None  # lane trống: chưa có dòng trước


def test_known_xn_is_preserved_when_op_has_no_factory():
    rows, _ = apply_ops([], {1: unplanned(xn="XN3")}, [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t", "sourceId": 1, "line": "1"}], CAL, FACTORIES)
    assert rows[0]["factory_code"] == "XN3"


def test_unplanned_already_used_or_line_missing_is_rejected():
    with pytest.raises(OpError, match="Nguồn Unplanned"):
        apply_ops([], {}, [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t", "sourceId": 5, "factory": "XN1", "line": "1"}], CAL, FACTORIES)
    with pytest.raises(OpError, match="Chuyền"):
        apply_ops([], {1: unplanned()}, [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "t", "sourceId": 1, "factory": "XN1", "line": ""}], CAL, FACTORIES)


def test_move_reindexes_and_does_not_silently_change_dates():
    base = [row("a", 1, begin=date(2026, 9, 1), end=date(2026, 9, 2)), row("b", 2, begin=date(2026, 9, 3), end=date(2026, 9, 4)), row("c", 3)]
    rows, _ = apply_ops(base, {}, [{"type": "MOVE", "rowUid": "c", "factory": "XN1", "line": "7", "afterRowUid": None}], CAL, FACTORIES)
    assert [r["row_uid"] for r in rows] == ["c", "a", "b"] and [r["sequence"] for r in rows] == [1, 2, 3]
    assert next(r for r in rows if r["row_uid"] == "b")["begin_prod_date"] == date(2026, 9, 3)
    moved, _ = apply_ops(base, {}, [{"type": "MOVE", "rowUid": "a", "factory": "XN2", "line": "1", "afterRowUid": None}], CAL, FACTORIES)
    a = next(r for r in moved if r["row_uid"] == "a")
    assert (a["factory_code"], a["primary_line"], a["line_assignments"]) == ("XN2", "1", ["1"])


def test_edit_calculated_field_marks_override_and_return_to_auto():
    base = [row("a", 1, begin=date(2026, 9, 14), end=date(2026, 9, 18)), row("b", 2, begin=date(2026, 9, 25), end=date(2026, 9, 26))]
    rows, _ = apply_ops(base, {}, [{"type": "EDIT_FIELD", "rowUid": "b", "field": "begin_prod_date", "value": "2026-09-30"}], CAL, FACTORIES)
    b = next(r for r in rows if r["row_uid"] == "b")
    assert b["begin_prod_date"] == date(2026, 9, 30) and "begin_prod_date" in b["extra"]["overrides"]
    back, _ = apply_ops(rows, {}, [{"type": "RETURN_TO_AUTO_CALC", "rowUid": "b", "field": "begin_prod_date"}], CAL, FACTORIES)
    b2 = next(r for r in back if r["row_uid"] == "b")
    assert b2["begin_prod_date"] == date(2026, 9, 19) and "begin_prod_date" not in b2["extra"].get("overrides", {})


def test_invalid_op_reports_index():
    with pytest.raises(OpError, match="#2"):
        apply_ops([row("a", 1)], {}, [{"type": "EDIT_FIELD", "rowUid": "a", "field": "note", "value": "x"}, {"type": "MOVE", "rowUid": "zzz"}], CAL, FACTORIES)


def test_recheck_levels():
    good = [row("a", 1, begin=date(2026, 9, 14), end=date(2026, 9, 15))]
    assert recheck(good, CAL, FACTORIES)["result"] == "PASS"

    err = recheck([row("a", 1, qty=0)], CAL, FACTORIES)
    assert err["result"] == "ERROR" and "QTY_INVALID" in err["by_rule"]
    assert recheck([row("a", 1, xn="")], CAL, FACTORIES)["by_rule"]["FACTORY_INVALID"] == 1

    warn = recheck([row("a", 1, cap=None, begin=date(2026, 9, 20), end=date(2026, 9, 21))], CAL, FACTORIES)  # 20/09 là Chủ nhật
    assert warn["result"] == "WARNING" and {"CAPACITY_MISSING", "BEGIN_ON_OFF_DAY"} <= set(warn["by_rule"])
    assert all(i["row_uid"] == "a" for i in warn["issues"])


def test_recheck_calc_mismatch_keeps_value_and_warns():
    r = row("a", 1, qty=1000, cap=500, begin=date(2026, 9, 14), end=date(2026, 9, 15))
    r["total_day"] = 3.0  # khác 1000/500 = 2.0
    assert "CALC_MISMATCH" in recheck([r], CAL, FACTORIES)["by_rule"]
    r["extra"] = {"overrides": {"total_day": {"source": "OVERRIDE"}}}
    assert "CALC_MISMATCH" not in recheck([r], CAL, FACTORIES)["by_rule"]


def test_recheck_overlap_and_transfer_rules():
    a = row("a", 1, begin=date(2026, 9, 14), end=date(2026, 9, 18))
    b = row("b", 2, begin=date(2026, 9, 16), end=date(2026, 9, 19))
    assert "LINE_OVERLAP" in recheck([a, b], CAL, FACTORIES)["by_rule"]

    t = row("t", 1, begin=date(2026, 9, 14), end=date(2026, 9, 18), transfer={"from": "7", "to": "8", "effective_date": None})
    assert "TRANSFER_DATE_MISSING" in recheck([t], CAL, FACTORIES)["by_rule"]
    t["transfer"]["effective_date"] = "2026-10-30"
    assert recheck([t], CAL, FACTORIES)["by_rule"]["TRANSFER_OUT_OF_RANGE"] == 1
    t["transfer"]["effective_date"] = "2026-09-20"  # Chủ nhật: chuyền đích không làm việc
    assert "TRANSFER_DEST_UNAVAILABLE" in recheck([t], CAL, FACTORIES)["by_rule"]


def test_compare_versions_categories():
    a = [row("a", 1), row("b", 2), row("c", 3), row("gone", 4, xn="XN2", line="1")]
    b_rows, _ = apply_ops(
        a,
        {1: unplanned(xn="XN1")},
        [
            {"type": "ADD_FROM_UNPLANNED", "tempRowId": "n", "sourceId": 1, "line": "7", "afterRowUid": "a"},
            {"type": "MOVE", "rowUid": "c", "factory": "XN1", "line": "7", "afterRowUid": None},
            {"type": "MOVE", "rowUid": "b", "factory": "XN3", "line": "2", "afterRowUid": None},
            {"type": "EDIT_FIELD", "rowUid": "a", "field": "quantity", "value": 1200},
            {"type": "EDIT_FIELD", "rowUid": "a", "field": "begin_prod_date", "value": "2026-09-30"},
        ],
        CAL,
        FACTORIES,
    )
    b_rows = [r for r in b_rows if r["row_uid"] != "gone"]
    diff = compare_versions(a, b_rows)
    s = diff["summary"]
    assert s["ADDED"] == 1 and s["REMOVED"] == 1 and s["LINE_CHANGE"] == 1  # b sang XN3
    assert s["QUANTITY_CHANGE"] == 1 and s["DATE_CHANGE"] == 1 and s["OVERRIDE_CHANGE"] == 1
    assert s["SEQUENCE_CHANGE"] >= 1  # c lên đầu chuyền
    assert compare_versions(a, a)["total_changes"] == 0


def test_ops_hash_is_stable_and_sensitive():
    o1 = [{"type": "MOVE", "rowUid": "a", "factory": "XN1", "line": "7", "afterRowUid": None}]
    assert ops_hash(o1) == ops_hash([dict(o1[0])])
    assert ops_hash(o1) != ops_hash([{**o1[0], "line": "8"}])
