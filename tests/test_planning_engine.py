from datetime import date

import pytest

from app.services import formula_runtime as fx
from app.services.formula import to_serial
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


def calc_row(uid, seq, begin, **kw):
    """Dòng nhất quán với công thức workbook: END = BEGIN + TOTAL_DAY + OFF_DAYS (giữ số lẻ ngày, không qua lịch)."""
    r = row(uid, seq, begin=begin, **kw)
    fs = fx.active()
    fs.set_stored(r, "BEGIN_PROD_DATE", to_serial(begin))
    fs.apply(r, None, "TOTAL_DAY")
    fs.apply(r, None, "END_BEGIN_DATE")
    return r


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
    # đúng workbook: BEGIN = END BE. dòng trước + 1/9 (dòng trước TOTAL_DAY = 2 ≥ 1), không qua lịch làm việc
    assert new["begin_prod_date"] == date(2026, 9, 18)
    assert abs(new["extra"]["serial"]["begin_prod_date"] - (to_serial(date(2026, 9, 18)) + 1 / 9)) < 1e-9
    assert new["total_day"] == 2.0
    assert abs(new["extra"]["serial"]["end_prod_date"] - (new["extra"]["serial"]["begin_prod_date"] + 2 + 2 / 7)) < 1e-9
    assert new["end_prod_date"] == date(2026, 9, 20)
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
    assert b2["begin_prod_date"] == date(2026, 9, 18) and "begin_prod_date" not in b2["extra"].get("overrides", {})


def test_invalid_op_reports_index():
    with pytest.raises(OpError, match="#2"):
        apply_ops([row("a", 1)], {}, [{"type": "EDIT_FIELD", "rowUid": "a", "field": "note", "value": "x"}, {"type": "MOVE", "rowUid": "zzz"}], CAL, FACTORIES)


def test_recheck_levels():
    good = [calc_row("a", 1, date(2026, 9, 14))]
    assert recheck(good, CAL, FACTORIES)["result"] == "PASS"

    err = recheck([row("a", 1, qty=0)], CAL, FACTORIES)
    assert err["result"] == "ERROR" and "QTY_INVALID" in err["by_rule"]
    assert recheck([row("a", 1, xn="")], CAL, FACTORIES)["by_rule"]["FACTORY_INVALID"] == 1

    warn = recheck([row("a", 1, cap=None, begin=date(2026, 9, 20), end=date(2026, 9, 21))], CAL, FACTORIES)  # 20/09 là Chủ nhật
    assert warn["result"] == "WARNING" and {"CAPACITY_MISSING", "BEGIN_ON_OFF_DAY"} <= set(warn["by_rule"])
    assert all(i["row_uid"] == "a" for i in warn["issues"])


def test_recheck_calc_mismatch_keeps_value_and_warns():
    r = calc_row("a", 1, date(2026, 9, 14), qty=1000, cap=500)
    r["total_day"] = 3.0  # khác 1000/500 = 2.0
    assert "CALC_MISMATCH" in recheck([r], CAL, FACTORIES)["by_rule"]
    r["extra"]["overrides"] = {"total_day": {"source": "OVERRIDE"}}
    fx.active().apply(r, None, "END_BEGIN_DATE")  # END tính lại từ TOTAL_DAY đang override
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


def test_unplan_then_add_returned_roundtrip():
    base = [row("a", 1, begin=date(2026, 9, 1), end=date(2026, 9, 2)), row("b", 2, begin=date(2026, 9, 3), end=date(2026, 9, 4))]
    returned: list = []
    rows, _ = apply_ops(base, {}, [{"type": "UNPLAN", "rowUid": "a"}], CAL, FACTORIES, returned)
    assert [r["row_uid"] for r in rows] == ["b"] and [r["row_uid"] for r in returned] == ["a"]
    returned2 = [dict(r) for r in returned]  # phiên bản sau lưu ảnh chụp JSON, ngày dạng chuỗi
    returned2[0]["end_prod_date"] = "2026-09-02"
    rows, changed = apply_ops(
        [r for r in base if r["row_uid"] == "b"], {}, [{"type": "ADD_RETURNED", "rowUid": "a", "factory": "XN2", "line": "3", "afterRowUid": None}], CAL, FACTORIES, returned2
    )
    a = next(r for r in rows if r["row_uid"] == "a")
    assert (a["factory_code"], a["primary_line"]) == ("XN2", "3") and returned2 == [] and "a" in changed
    with pytest.raises(OpError):
        apply_ops(base, {}, [{"type": "ADD_RETURNED", "rowUid": "zzz", "factory": "XN1", "line": "7", "afterRowUid": None}], CAL, FACTORIES, [])


def test_recalc_lane_cascades_downstream_and_keeps_overrides():
    a = calc_row("a", 1, date(2026, 9, 14))
    fs = fx.active()
    b, c = row("b", 2, qty=1000, cap=500), row("c", 3, qty=1000, cap=500)
    for prev, cur in ((a, b), (b, c)):
        fs.apply(cur, prev, "TOTAL_DAY"); fs.apply(cur, prev, "BEGIN_PROD_DATE"); fs.apply(cur, prev, "END_BEGIN_DATE")
    old_c_begin = c["extra"]["serial"]["begin_prod_date"]
    ops = [
        {"type": "EDIT_FIELD", "rowUid": "a", "field": "quantity", "value": 5000},  # a kéo dài: 5000/500 = 10 ngày
        {"type": "RECALC_LANE", "factory": "XN1", "line": "7"},
    ]
    rows, changed = apply_ops([a, b, c], {}, ops, CAL, FACTORIES)
    by = {r["row_uid"]: r for r in rows}
    assert by["a"]["total_day"] == 10.0 and {"a", "b", "c"} <= changed
    assert by["c"]["extra"]["serial"]["begin_prod_date"] > old_c_begin + 5  # dòng sau đẩy lùi theo a
    assert by["b"]["extra"]["serial"]["begin_prod_date"] == pytest.approx(by["a"]["extra"]["serial"]["end_prod_date"] + 1 / 9)

    # ô đang OVERRIDE giữ nguyên khi tính lại
    b["extra"]["overrides"] = {"begin_prod_date": {"source": "OVERRIDE", "calculated": None}}
    fs.set_stored(b, "BEGIN_PROD_DATE", to_serial(date(2026, 12, 1)))
    rows, _ = apply_ops([a, b, c], {}, [{"type": "RECALC_LANE", "factory": "XN1", "line": "7", "fromRowUid": "b"}], CAL, FACTORIES)
    assert next(r for r in rows if r["row_uid"] == "b")["begin_prod_date"] == date(2026, 12, 1)
    with pytest.raises(OpError):
        apply_ops([a], {}, [{"type": "RECALC_LANE", "factory": "XN9", "line": "1"}], CAL, FACTORIES)


def test_set_lines_multi_line_moves_to_new_primary_lane_and_sums_capacity():
    a, b = row("a", 1, line="7"), row("b", 2, line="7")
    other = row("z", 1, line="4", qty=500, cap=250)
    caps = {"4": {"capacity_per_day": 300, "id": 1, "version": 1, "source": "IE"}, "5": {"capacity_per_day": 200, "id": 2, "version": 1, "source": "IE"}}
    rows, changed = apply_ops([a, b, other], {}, [{"type": "SET_LINES", "rowUid": "b", "lines": ["4", " 5", "4"]}], CAL, FACTORIES, None, lambda r: caps.get(r["primary_line"]))
    nb = next(r for r in rows if r["row_uid"] == "b")
    assert nb["line_assignments"] == ["4", "5"] and nb["line_raw"] == "4 + 5" and nb["primary_line"] == "4" and nb["transfer"] is None
    assert nb["capacity"] == 500 and nb["extra"]["capacity_source"]["source"].startswith("SUM(2")
    assert nb["total_day"] == pytest.approx(1000 / 500)
    assert [r["row_uid"] for r in rows if r["primary_line"] == "4"] == ["z", "b"]      # xếp cuối chuyền chính mới
    assert [r["row_uid"] for r in rows if r["primary_line"] == "7"] == ["a"] and "b" in changed
    with pytest.raises(OpError, match="ít nhất"):
        apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": [" ", ""]}], CAL, FACTORIES)
    with pytest.raises(OpError, match="tối đa 4"):
        apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": list("12345")}], CAL, FACTORIES)


def test_set_lines_keeps_manual_capacity_when_definitions_incomplete():
    a = row("a", 1, line="7", cap=500)
    resolver = lambda r: {"capacity_per_day": 100, "id": 1, "version": 1, "source": "IE"} if r["primary_line"] == "7" else None  # noqa: E731
    rows, _ = apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": ["7", "8"]}], CAL, FACTORIES, None, resolver)
    assert rows[0]["capacity"] == 500  # chuyền 8 chưa có định nghĩa -> không tự cộng
    rows, _ = apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": ["7", "8"], "capacity": 800}], CAL, FACTORIES)
    assert rows[0]["capacity"] == 800


def test_set_transfer_and_clear_with_validation():
    a = row("a", 1, line="2", qty=1000)
    rows, _ = apply_ops([a], {}, [{"type": "SET_TRANSFER", "rowUid": "a", "toLines": ["1"], "effectiveDate": "2099-01-05", "plannedRemainingQty": 400}], CAL, FACTORIES)
    t = rows[0]["transfer"]
    assert t == {"from": "2", "to": "1", "effective_date": "2099-01-05", "planned_remaining_qty": 400.0, "status": "PLANNED"} and rows[0]["line_raw"] == "2 ==> 1"
    assert apply_ops(rows, {}, [{"type": "SET_TRANSFER", "rowUid": "a", "toLines": ["1"], "effectiveDate": "2000-01-05"}], CAL, FACTORIES)[0][0]["transfer"]["status"] == "EFFECTIVE"
    cleared, _ = apply_ops(rows, {}, [{"type": "SET_TRANSFER", "rowUid": "a", "clear": True}], CAL, FACTORIES)
    assert cleared[0]["transfer"] is None and cleared[0]["line_raw"] == "2"
    for bad, msg in (({"toLines": ["2"]}, "khác"), ({"toLines": ["1"], "plannedRemainingQty": 5000}, "trong khoảng"), ({"toLines": []}, "ít nhất")):
        with pytest.raises(OpError, match=msg):
            apply_ops([a], {}, [{"type": "SET_TRANSFER", "rowUid": "a", **bad}], CAL, FACTORIES)
    r2 = apply_ops([a], {}, [{"type": "SET_TRANSFER", "rowUid": "a", "toLines": ["1"]}], CAL, FACTORIES)[0]
    assert "TRANSFER_DATE_MISSING" in recheck(r2, CAL, FACTORIES)["by_rule"]  # Recheck vẫn bắt thiếu ngày hiệu lực


def test_merge_lines_combines_selected_rows_into_one_multi_line_row():
    a = row("a", 1, line="4", qty=1000, cap=500)
    b = row("b", 1, line="5", qty=600, cap=300)
    c = row("c", 1, line="9", qty=400, cap=200)
    for r in (a, b, c):
        r["po_number"], r["extra"]["ref"] = "PO-1", {"worker": 30.0}
    tail = row("t", 2, line="4", qty=200, cap=100)
    rows, changed = apply_ops([a, b, c, tail], {}, [{"type": "MERGE_LINES", "rowUids": ["b", "a", "c"], "primaryUid": "a"}], CAL, FACTORIES)
    by = {r["row_uid"]: r for r in rows}
    assert set(by) == {"a", "t"} and changed == {"a"}                          # b, c gộp vào a
    k = by["a"]
    assert k["line_assignments"] == ["4", "5", "9"] and k["line_raw"] == "4 + 5 + 9" and k["primary_line"] == "4"
    assert k["quantity"] == 2000 and k["capacity"] == 1000 and k["extra"]["ref"]["worker"] == 90.0
    assert k["total_day"] == pytest.approx(2.0)                                # 2000 / 1000
    assert [m["row_uid"] for m in k["extra"]["merged_from"]] == ["b", "c"]
    assert [r["row_uid"] for r in rows if r["primary_line"] == "4"] == ["a", "t"]  # thứ tự chuyền chính giữ nguyên


def test_merge_lines_validation():
    a, b = row("a", 1, line="4"), row("b", 1, line="5")
    a["po_number"] = b["po_number"] = "PO-1"
    other_po = row("x", 1, line="6")
    same_po_other_style = row("s", 1, line="7", style="OTHER")
    same_po_other_style["po_number"] = "PO-1"
    for ops, msg in (
        ([{"type": "MERGE_LINES", "rowUids": ["a"], "primaryUid": "a"}], "ít nhất 2"),
        ([{"type": "MERGE_LINES", "rowUids": ["a", "zzz"], "primaryUid": "a"}], "Không tìm thấy"),
        ([{"type": "MERGE_LINES", "rowUids": ["a", "b"], "primaryUid": "x"}], "giữ lại"),
        ([{"type": "MERGE_LINES", "rowUids": ["a", "x"], "primaryUid": "a"}], "cùng 1 PO"),
    ):
        with pytest.raises(OpError, match=msg):
            apply_ops([a, b, other_po], {}, ops, CAL, FACTORIES)
    b["transfer"] = {"from": "5", "to": "6", "effective_date": None, "planned_remaining_qty": None, "status": "PLANNED"}
    with pytest.raises(OpError, match="chuyển chuyền"):
        apply_ops([a, b], {}, [{"type": "MERGE_LINES", "rowUids": ["a", "b"], "primaryUid": "a"}], CAL, FACTORIES)
    # cùng PO nhưng khác style vẫn dồn được (quy tắc chỉ xét 1 PO); PO khác xí nghiệp thì không
    rows, _ = apply_ops([a, same_po_other_style], {}, [{"type": "MERGE_LINES", "rowUids": ["a", "s"], "primaryUid": "a"}], CAL, FACTORIES)
    assert len(rows) == 1 and rows[0]["line_raw"] == "4 + 7" and rows[0]["style_cc"] == "S"
    other_xn = row("y", 1, xn="XN2", line="4")
    other_xn["po_number"] = "PO-1"
    with pytest.raises(OpError, match="cùng 1 PO"):
        apply_ops([a, other_xn], {}, [{"type": "MERGE_LINES", "rowUids": ["a", "y"], "primaryUid": "a"}], CAL, FACTORIES)
    blank = row("q", 1, line="8")
    blank["po_number"] = ""
    with pytest.raises(OpError, match="chưa có số PO"):
        apply_ops([a, blank], {}, [{"type": "MERGE_LINES", "rowUids": ["a", "q"], "primaryUid": "a"}], CAL, FACTORIES)
    # thiếu năng suất ở một dòng -> giữ năng suất của dòng giữ lại
    b["transfer"], b["capacity"] = None, None
    rows, _ = apply_ops([a, b], {}, [{"type": "MERGE_LINES", "rowUids": ["a", "b"], "primaryUid": "a"}], CAL, FACTORIES)
    assert rows[0]["capacity"] == 500


def test_add_lines_to_one_big_plan_via_set_lines_keeps_current_lines_first():
    a = row("a", 1, line="4", qty=3000, cap=500)
    rows, _ = apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": ["4", "5", "6"], "capacity": 1500}], CAL, FACTORIES)
    assert rows[0]["line_raw"] == "4 + 5 + 6" and rows[0]["primary_line"] == "4" and rows[0]["total_day"] == pytest.approx(2.0)


def test_split_lines_creates_new_row_from_selected_lines_and_conserves_quantity():
    a = row("a", 1, line="4", qty=3000, cap=1500)
    a["po_number"], a["extra"]["ref"] = "PO-1", {"worker": 90.0}
    a["line_assignments"], a["line_raw"] = ["4", "5", "9"], "4 + 5 + 9"
    tail = row("t", 2, line="4", qty=200, cap=100)
    op = {"type": "SPLIT_LINES", "rowUid": "a", "lines": ["9"], "effectiveDate": "2026-09-21", "quantity": 1000, "tempRowId": "n1"}
    rows, changed = apply_ops([a, tail], {}, [op], CAL, FACTORIES)
    old = next(r for r in rows if r["row_uid"] == "a")
    new = next(r for r in rows if r["origin"] == "DRAFT_NEW")
    assert old["line_assignments"] == ["4", "5"] and old["line_raw"] == "4 + 5" and old["quantity"] == 2000
    assert new["line_assignments"] == ["9"] and new["primary_line"] == "9" and new["po_number"] == "PO-1" and new["quantity"] == 1000
    assert old["quantity"] + new["quantity"] == 3000                                   # bảo toàn số lượng
    assert old["capacity"] == pytest.approx(1000) and new["capacity"] == pytest.approx(500)  # chia đều theo số chuyền (1/3, 2/3)
    assert old["extra"]["ref"]["worker"] == pytest.approx(60.0) and new["extra"]["ref"]["worker"] == pytest.approx(30.0)
    assert new["begin_prod_date"] == date(2026, 9, 21) and "begin_prod_date" in new["extra"]["overrides"] and new["extra"]["split_from"] == "a"
    assert new["total_day"] == pytest.approx(2.0) and new["end_prod_date"] is not None
    assert {"a", new["row_uid"]} <= changed and len(rows) == 3


def test_split_moves_original_to_new_primary_lane_when_primary_line_is_split_off():
    a = row("a", 1, line="4", qty=2000, cap=1000)
    a["line_assignments"], a["line_raw"] = ["4", "5"], "4 + 5"
    rows, _ = apply_ops([a], {}, [{"type": "SPLIT_LINES", "rowUid": "a", "lines": ["4"], "effectiveDate": "2026-09-21", "quantity": 500, "tempRowId": "n2"}], CAL, FACTORIES)
    old = next(r for r in rows if r["row_uid"] == "a")
    new = next(r for r in rows if r["origin"] == "DRAFT_NEW")
    assert old["primary_line"] == "5" and new["primary_line"] == "4" and old["line_raw"] == "5" and new["line_raw"] == "4"


def test_split_uses_capacity_definitions_when_all_lines_defined():
    a = row("a", 1, line="4", qty=3000, cap=1500)
    a["line_assignments"], a["line_raw"] = ["4", "5"], "4 + 5"
    defs = {"4": {"capacity_per_day": 1000, "id": 1, "version": 1, "source": "IE"}, "5": {"capacity_per_day": 500, "id": 2, "version": 1, "source": "IE"}}
    rows, _ = apply_ops([a], {}, [{"type": "SPLIT_LINES", "rowUid": "a", "lines": ["5"], "effectiveDate": "2026-09-21", "quantity": 900, "tempRowId": "n3"}], CAL, FACTORIES, None, lambda r: defs.get(r["primary_line"]))
    new = next(r for r in rows if r["origin"] == "DRAFT_NEW")
    old = next(r for r in rows if r["row_uid"] == "a")
    assert new["capacity"] == 500 and old["capacity"] == 1000


def test_split_validation_and_merge_roundtrip():
    single = row("s", 1, line="4")
    multi = row("m", 1, line="4", qty=1000, cap=500)
    multi["line_assignments"], multi["line_raw"] = ["4", "5"], "4 + 5"
    ok = {"type": "SPLIT_LINES", "rowUid": "m", "lines": ["5"], "effectiveDate": "2026-09-21", "quantity": 400, "tempRowId": "n4"}
    for patch, msg in (({"rowUid": "s", "lines": ["4"]}, "ít nhất 1 chuyền"), ({"lines": ["9"]}, "đang có trong dòng"), ({"lines": ["4", "5"]}, "ít nhất 1 chuyền"), ({"effectiveDate": None}, "ngày tách"),
                       ({"quantity": 1000}, "nhỏ hơn"), ({"quantity": 0}, "lớn hơn 0")):
        with pytest.raises(OpError, match=msg):
            apply_ops([single, multi], {}, [{**ok, **patch}], CAL, FACTORIES)
    multi["po_number"] = "PO-1"
    rows, _ = apply_ops([multi], {}, [ok], CAL, FACTORIES)
    new_uid = next(r["row_uid"] for r in rows if r["origin"] == "DRAFT_NEW")
    merged, _ = apply_ops(rows, {}, [{"type": "MERGE_LINES", "rowUids": ["m", new_uid], "primaryUid": "m"}], CAL, FACTORIES)
    assert len(merged) == 1 and merged[0]["quantity"] == 1000 and merged[0]["line_raw"] == "4 + 5"  # tách rồi dồn lại: số lượng và chuyền được khôi phục


def test_loose_merge_max_four_lines_but_all_lines_allowed_and_shown_as_range():
    from app.services.planning_engine import format_lines

    assert format_lines(["4", "5", "9"]) == "4 + 5 + 9" and format_lines(["7", "4", "5", "6", "9"]) == "4:7 + 9"
    assert format_lines([str(i) for i in range(1, 19)]) == "1:18" and format_lines(["1", "2", "3", "4", "5", "A"]) == "1:5 + A"
    a = row("a", 1, line="1", qty=1800, cap=900)
    fl = {"XN1": {str(i) for i in range(1, 19)}}                       # xí nghiệp có 18 chuyền
    with pytest.raises(OpError, match="tối đa 4"):
        apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": ["1", "2", "3", "4", "5"]}], CAL, FACTORIES, None, None, fl)
    ok, _ = apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": ["1", "2", "3", "4"]}], CAL, FACTORIES, None, None, fl)
    assert ok[0]["line_raw"] == "1 + 2 + 3 + 4"
    everything, _ = apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": ["1"], "all": True}], CAL, FACTORIES, None, None, fl)
    assert everything[0]["line_raw"] == "1:18" and everything[0]["line_assignments"][0] == "1" and len(everything[0]["line_assignments"]) == 18
    # chuyền chính giữ nguyên là chuyền đứng đầu khi dồn tất cả từ một chuyền khác
    b = row("b", 1, line="7")
    other, _ = apply_ops([b], {}, [{"type": "SET_LINES", "rowUid": "b", "lines": ["7"], "all": True}], CAL, FACTORIES, None, None, fl)
    assert other[0]["primary_line"] == "7" and other[0]["line_raw"] == "1:18"
    # liệt kê đủ mọi chuyền (không cờ all) cũng được nhận biết là "tất cả"
    listed, _ = apply_ops([a], {}, [{"type": "SET_LINES", "rowUid": "a", "lines": [str(i) for i in range(1, 19)]}], CAL, FACTORIES, None, None, fl)
    assert listed[0]["line_raw"] == "1:18"


def test_merge_all_lines_of_factory_over_four_rows():
    rows = [row(f"r{i}", 1, line=str(i), qty=100, cap=50) for i in range(1, 7)]
    for r in rows:
        r["po_number"] = "PO-9"
    uids = [r["row_uid"] for r in rows]
    fl = {"XN1": {str(i) for i in range(1, 7)}}                        # xí nghiệp chỉ có 6 chuyền -> dồn 6 dòng = tất cả chuyền
    with pytest.raises(OpError, match="tối đa 4"):
        apply_ops(rows[:5], {}, [{"type": "MERGE_LINES", "rowUids": uids[:5], "primaryUid": uids[0]}], CAL, FACTORIES, None, None, fl)
    merged, _ = apply_ops(rows, {}, [{"type": "MERGE_LINES", "rowUids": uids, "primaryUid": uids[0]}], CAL, FACTORIES, None, None, fl)
    assert len(merged) == 1 and merged[0]["line_raw"] == "1:6" and merged[0]["quantity"] == 600


def test_split_single_line_row_to_other_lines_keeps_original_line():
    a = row("a", 1, line="4", qty=1000, cap=500)
    a["po_number"], a["extra"]["ref"] = "PO-1", {"worker": 30.0}
    fl = {"XN1": {"4", "5", "6", "7", "8"}}
    op = {"type": "SPLIT_LINES", "rowUid": "a", "newLines": ["5", "6"], "effectiveDate": "2026-09-21", "quantity": 400, "tempRowId": "s1"}
    rows, changed = apply_ops([a], {}, [op], CAL, FACTORIES, None, None, fl)
    old = next(r for r in rows if r["row_uid"] == "a")
    new = next(r for r in rows if r["origin"] == "DRAFT_NEW")
    assert old["line_raw"] == "4" and old["quantity"] == 600 and old["capacity"] == 500          # dòng gốc giữ chuyền + năng suất
    assert new["line_raw"] == "5 + 6" and new["primary_line"] == "5" and new["quantity"] == 400 and new["po_number"] == "PO-1"
    assert new["capacity"] == pytest.approx(1000) and new["extra"]["ref"]["worker"] == pytest.approx(60.0)   # ước theo bình quân mỗi chuyền x 2 chuyền
    assert new["begin_prod_date"] == date(2026, 9, 21) and new["extra"]["split_from"] == "a" and old["quantity"] + new["quantity"] == 1000
    assert "a" in changed and len(rows) == 2


def test_split_to_other_lines_rules():
    a = row("a", 1, line="4", qty=1000, cap=500)
    fl = {"XN1": {str(i) for i in range(1, 9)}}
    base = {"type": "SPLIT_LINES", "rowUid": "a", "effectiveDate": "2026-09-21", "quantity": 400, "tempRowId": "s2"}
    for patch, msg in (({"newLines": ["4"]}, "khác các chuyền"), ({"newLines": ["1", "2", "3", "5", "6"]}, "tối đa 4"), ({"newLines": ["5"], "quantity": 1000}, "nhỏ hơn"), ({"newLines": ["5"], "effectiveDate": None}, "ngày tách")):
        with pytest.raises(OpError, match=msg):
            apply_ops([a], {}, [{**base, **patch}], CAL, FACTORIES, None, None, fl)
    everything, _ = apply_ops([a], {}, [{**base, "newAll": True}], CAL, FACTORIES, None, None, fl)
    new = next(r for r in everything if r["origin"] == "DRAFT_NEW")
    assert new["line_assignments"] == [l for l in new["line_assignments"] if l != "4"] and len(new["line_assignments"]) == 7 and new["line_raw"] == "1:3 + 5:8"


# --------------------------------------------------------------------------- Virtual lane theo toàn bộ line_assignments
def multi(uid, seq, lines, **kw):
    r = row(uid, seq, line=lines[0], **kw)
    r["line_assignments"], r["line_raw"] = list(lines), " + ".join(lines)
    return r


def test_virtual_lane_multi_line_row_belongs_to_every_lane_and_previous_sequence():
    from app.services.lanes import build_lanes, prev_in_lane, previous_sequence

    a, b, c = multi("A", 1, ["4", "5"]), row("B", 1, line="5"), row("C", 2, line="4")
    rows = [a, b, c]
    lanes = build_lanes(rows)
    assert [r["row_uid"] for r in lanes[("XN1", "4")]] == ["A", "C"]
    assert [r["row_uid"] for r in lanes[("XN1", "5")]] == ["A", "B"]           # A xuất hiện trong cả lane 4 và lane 5
    assert prev_in_lane(rows, b, "5")["row_uid"] == "A"                        # prev(B@5) = A
    assert prev_in_lane(rows, c, "4")["row_uid"] == "A"                        # prev(C@4) = A
    assert previous_sequence(rows, b)["row_uid"] == "A" and previous_sequence(rows, c)["row_uid"] == "A"
    assert previous_sequence(rows, a) is None                                  # dòng đầu của cả hai lane


def test_previous_sequence_of_multi_line_row_takes_latest_ending_predecessor():
    from app.services.lanes import previous_sequence

    x = row("X", 1, line="4", begin=date(2026, 9, 1), end=date(2026, 9, 5))
    y = row("Y", 1, line="5", begin=date(2026, 9, 1), end=date(2026, 9, 9))    # chuyền 5 rảnh muộn hơn
    m = multi("M", 2, ["4", "5"], begin=date(2026, 9, 10))
    m2 = multi("M2", 2, ["4", "5"])
    from app.services.lanes import lane_of

    assert [r["row_uid"] for r in lane_of([x, y, m], "XN1", "5")] == ["Y", "M"]
    assert previous_sequence([x, y, m2], m2)["row_uid"] == "Y"                  # phải chờ chuyền rảnh muộn nhất


def test_apply_ops_reindex_builds_virtual_sequence_and_keeps_anchor_stable():
    a, b, c = multi("A", 1, ["4", "5"], begin=date(2026, 9, 14), end=date(2026, 9, 15)), row("B", 1, line="5", begin=date(2026, 9, 16), end=date(2026, 9, 17)), row("C", 2, line="4")
    rows, _ = apply_ops([a, b, c], {}, [], CAL, FACTORIES)
    by = {r["row_uid"]: r for r in rows}
    assert by["A"]["extra"]["virtual_sequence"] == {"4": 1, "5": 1} and by["B"]["extra"]["virtual_sequence"] == {"5": 2} and by["C"]["extra"]["virtual_sequence"] == {"4": 2}
    assert by["A"]["extra"]["vanchor"] == {"5": None}                           # neo: A đứng đầu lane 5
    # thêm dòng vào đầu chuyền 5 (dòng sở hữu mới) -> A giữ vị trí đầu lane 5 nhờ neo, không bị suy ra lại theo ngày
    ops = [{"type": "ADD_FROM_UNPLANNED", "tempRowId": "n1", "sourceId": 1, "factory": "XN1", "line": "5", "afterRowUid": None}]
    rows2, _ = apply_ops(rows, {1: unplanned()}, ops, CAL, FACTORIES)
    order5 = [r["row_uid"] for r in sorted((r for r in rows2 if "5" in r["line_assignments"]), key=lambda r: r["extra"]["virtual_sequence"]["5"])]
    assert order5 == ["A", "Dn1", "B"]


def test_recheck_overlap_and_calc_use_virtual_lane_not_primary_line():
    a = calc_row("A", 1, date(2026, 9, 14), line="4", qty=1000, cap=500)
    a["line_assignments"], a["line_raw"] = ["4", "5"], "4 + 5"
    a["extra"]["ref"] = {}
    b = row("B", 1, line="5", begin=date(2026, 9, 15), end=date(2026, 9, 17))   # bắt đầu 15/09 trong khi A (lane 5) kết thúc muộn hơn
    assert a["end_prod_date"] and b["begin_prod_date"] < a["end_prod_date"]
    out = recheck([a, b], CAL, FACTORIES)
    overlap = [i for i in out["issues"] if i["rule_code"] == "LINE_OVERLAP"]
    assert len(overlap) == 1 and overlap[0]["row_uid"] == "B" and "XN1/5" in overlap[0]["message"]   # chỉ thấy được khi so theo lane ảo 5
    # B đặt sau A (theo lane ảo) nên PREVIOUS_SEQUENCE để tính lại BEGIN là A
    c = row("C", 2, line="4", begin=date(2026, 9, 14))
    out2 = recheck([a, b, c], CAL, FACTORIES)
    assert sum(1 for i in out2["issues"] if i["rule_code"] == "LINE_OVERLAP" and i["row_uid"] == "C") == 1


def test_recalc_lane_walks_virtual_lane_including_secondary_members():
    a = calc_row("A", 1, date(2026, 9, 14), line="4", qty=1000, cap=500)
    a["line_assignments"], a["line_raw"] = ["4", "5"], "4 + 5"
    b = row("B", 1, line="5", qty=500, cap=500, begin=date(2026, 9, 20), end=date(2026, 9, 21))   # bắt đầu sau A -> B đứng sau A trong lane 5
    rows, changed = apply_ops([a, b], {}, [{"type": "RECALC_LANE", "factory": "XN1", "line": "5"}], CAL, FACTORIES)
    by = {r["row_uid"]: r for r in rows}
    assert {"A", "B"} <= changed                                                # lane 5 gồm cả A (thành viên phụ) và B
    assert by["B"]["begin_prod_date"] <= date(2026, 9, 20) and by["B"]["begin_prod_date"] >= by["A"]["end_prod_date"]   # B tính lại từ A (PREVIOUS_SEQUENCE theo lane ảo)


def test_resource_checks_and_release_use_every_line_of_the_row():
    from app.services import resource_service as rs

    r = multi("M", 1, ["4", "5"], begin=date(2026, 9, 14), end=date(2026, 9, 18), cap=1000)
    r["extra"] = {"ref": {"worker": 60.0}}
    res = rs.Resources(
        cap_defs=[{"id": 1, "capacity_per_day": 600, "factory_code": "XN1", "line": "4", "style_cc": "", "model_code": "", "version": 1, "status": "ACTIVE", "source": "IE"},
                  {"id": 2, "capacity_per_day": 400, "factory_code": "XN1", "line": "5", "style_cc": "", "model_code": "", "version": 1, "status": "ACTIVE", "source": "IE"}],
        labor={("XN1", "4"): 20, ("XN1", "5"): 20},                             # tổng 40 < 60 cần
        requirements={"S": [("MAN", 2)]}, machines={("XN1", "4", "MAN"): 5, ("XN1", "5", "MAN"): 1},   # chuyền 5 thiếu máy (không phải chuyền chính)
        as_of=date(2026, 9, 1),
    )
    out = {code: msg for _s, _c, msg, code in rs.check_row_resources(res, r)}
    assert "CAPACITY_DEFINITION_MISMATCH" not in out                            # 600 + 400 = 1000
    assert "LABOR_SHORTAGE" in out and "40" in out["LABOR_SHORTAGE"] and "4 + 5" in out["LABOR_SHORTAGE"]
    assert "MACHINE_SHORTAGE" in out and "XN1/5" in out["MACHINE_SHORTAGE"]
    sched = rs.release_schedule([r], date(2026, 9, 14))
    lines = {l["line"]: l["days"][0]["reserved_labor"] for f in sched["factories"] for l in f["lines"]}
    assert lines == {"4": 30.0, "5": 30.0}                                      # giữ nguồn lực trên cả hai chuyền
