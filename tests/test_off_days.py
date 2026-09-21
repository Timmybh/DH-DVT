"""OFF DAYS (spec §31–33): tính theo Lịch làm việc trong khoảng may; Excel import giữ nguyên; ghi đè tay có lý do; Reset."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import formula_runtime as fx
from app.services.calendar import CalendarResolver, Rule
from app.services.formula import to_serial
from app.services.planning_engine import OpError, apply_ops

SUN = Rule("COMPANY", "", "WEEKLY_OFF", weekday=6, day_type="WEEKLY_OFF")
FACTORIES = {"XN1", "XN2"}
FRI = date(2026, 9, 18)  # Thứ sáu


def prow(uid="a", seq=1, xn="XN1", line="7", qty=3000, cap=1000, begin=FRI, **kw):
    r = {
        "row_uid": uid, "sequence": seq, "origin": "EXISTING", "source_key": uid, "source_plan_row_id": None, "factory_code": xn, "primary_line": line, "line_raw": line, "line_assignments": [line],
        "transfer": None, "po_number": "PO", "style_cc": "S", "model_code": "M", "description": "", "customer": "C", "sport": "", "season": "", "quantity": qty, "capacity": cap,
        "total_day": (qty / cap) if cap else None, "begin_prod_date": begin, "end_prod_date": None, "warehouse_date": None, "chd": None, "note": "", "extra": {"serial": {"begin_prod_date": to_serial(begin)}}, **kw,
    }
    return r


def off_days(rows_or_row, cal):
    fx.set_calendar(cal)
    return fx.active().display(rows_or_row)["off_days_detail"]


def test_off_days_counts_calendar_off_days_inside_the_sewing_span():
    cal = CalendarResolver([SUN])
    # Thứ sáu, Thứ bảy làm việc; Chủ nhật nghỉ (1); Thứ hai làm việc => cần 3 ngày làm việc trải qua 1 ngày nghỉ
    d = off_days(prow(qty=3000), cal)
    assert d["calculated"] == 1 and d["effective"] == 1 and not d["overridden"]
    assert off_days(prow(qty=2000), cal)["calculated"] == 0                      # 2 ngày làm việc: Chủ nhật nằm SAU ngày làm việc cuối -> không tính
    assert off_days(prow(qty=2500), cal)["calculated"] == 1                      # 2,5 ngày: ngày làm việc lẻ cuối vẫn chiếm trọn một ngày lịch
    assert off_days(prow(qty=9000), cal)["calculated"] == 1 + 1                   # 9 ngày làm việc: T6,T7 | CN nghỉ | T2..T7 (6) | CN nghỉ sau ngày cuối? -> đếm tới hết ngày làm việc thứ 9
    assert off_days(prow(qty=3000, begin=date(2026, 9, 20)), cal)["calculated"] == 1   # bắt đầu đúng ngày nghỉ: ngày đó là 1 ngày nghỉ
    assert off_days(prow(qty=1000, cap=0), cal)["calculated"] is None    # thiếu năng suất -> không tính được, không bịa số


def test_off_days_uses_line_xn_company_hierarchy_and_all_off_types():
    tet = Rule("COMPANY", "", "DATE_OFF", rule_date=date(2026, 9, 19), end_date=date(2026, 9, 21), day_type="TET")            # Thứ bảy → Thứ hai nghỉ (kể cả Chủ nhật)
    cal = CalendarResolver([SUN, tet])
    assert off_days(prow(qty=3000), cal)["calculated"] == 3                       # T6 làm | T7,CN,T2 nghỉ (3) | T3 làm | T4 làm => 3 ngày làm việc + 3 nghỉ
    # Ngoại lệ = WORKING và Tăng ca KHÔNG tính là ngày nghỉ
    work = Rule("XN", "XN2", "DATE_WORK", rule_date=date(2026, 9, 20), day_type="EXCEPTION")
    ot = Rule("XN", "XN2", "OVERTIME", rule_date=date(2026, 9, 19), day_type="OVERTIME")
    cal2 = CalendarResolver([SUN, tet, work, ot])
    assert off_days(prow(qty=3000, xn="XN2"), cal2)["calculated"] == 0            # XN2: T6 làm, T7 tăng ca (làm), CN ngoại lệ (làm) => đủ 3 ngày, không ngày nghỉ nào
    assert off_days(prow(qty=4000, xn="XN2"), cal2)["calculated"] == 1            # ngày làm việc thứ 4 phải qua T2 (nghỉ Tết) => 1 ngày nghỉ
    assert off_days(prow(qty=3000, xn="XN1"), cal2)["calculated"] == 3            # XN1 vẫn theo lịch công ty
    # Ngoại lệ = OFF (ghi đè ngày làm việc)
    cal3 = CalendarResolver([Rule("LINE", "XN1:7", "DATE_OFF", rule_date=date(2026, 9, 18), day_type="EXCEPTION")])
    assert off_days(prow(qty=1000), cal3)["calculated"] == 1 and off_days(prow(qty=1000, line="8"), cal3)["calculated"] == 0


def test_end_date_uses_calendar_off_days_and_recalculates_when_calendar_changes():
    ops = []
    r = prow(qty=3000)
    rows, _ = apply_ops([r], {}, [{"type": "RECALC_LANE", "factory": "XN1", "line": "7"}], CalendarResolver([SUN]), FACTORIES)
    row = rows[0]
    assert row["total_day"] == 3.0 and row["extra"]["serial"]["end_prod_date"] == pytest.approx(to_serial(FRI) + 3 + 1)       # END = BEGIN + TOTAL_DAY + OFF_DAYS(1)
    rows2, _ = apply_ops([r], {}, [{"type": "RECALC_LANE", "factory": "XN1", "line": "7"}], CalendarResolver([]), FACTORIES)  # lịch đổi: không còn Chủ nhật nghỉ
    assert rows2[0]["extra"]["serial"]["end_prod_date"] == pytest.approx(to_serial(FRI) + 3)
    assert ops == []


def test_excel_import_keeps_exact_off_days_and_marks_source():
    from app.services.planning_service import _baseline_extra

    pr = SimpleNamespace(grid={"off_days": 2.4, "begin_serial": 46283.0}, worker=30, ehd_etd=None, risk="OK", risk_reason="", gap_days=None)
    extra = _baseline_extra(pr)
    ov = extra["off_days_override"]
    assert ov["value"] == 2.4 and ov["source"] == "EXCEL_IMPORT"                  # không làm tròn half-up
    row = prow(qty=3000, extra={**extra, "serial": {"begin_prod_date": to_serial(FRI)}})
    d = off_days(row, CalendarResolver([SUN]))
    assert d["effective"] == 2.4 and d["calculated"] == 1 and d["override"] == 2.4 and d["source"] == "EXCEL_IMPORT" and d["overridden"]
    # END của baseline khớp workbook: BEGIN + TOTAL_DAY + OFF_DAYS(Excel)
    rows, _ = apply_ops([row], {}, [{"type": "RECALC_LANE", "factory": "XN1", "line": "7"}], CalendarResolver([SUN]), FACTORIES)
    assert rows[0]["extra"]["serial"]["end_prod_date"] == pytest.approx(to_serial(FRI) + 3 + 2.4)
    assert "off_days_override" not in _baseline_extra(SimpleNamespace(grid={"off_days": None}, worker=1, ehd_etd=None, risk="OK", risk_reason="", gap_days=None))


def test_manual_override_requires_reason_keeps_all_values_survives_calendar_change_until_reset():
    cal = CalendarResolver([SUN])
    base = [prow(qty=3000)]
    bad = {"type": "SET_OFF_DAYS", "rowUid": "a", "value": 3}
    with pytest.raises(OpError, match="lý do"):
        apply_ops(base, {}, [bad], cal, FACTORIES)
    with pytest.raises(OpError):
        apply_ops(base, {}, [{**bad, "reason": "Bảo trì kéo dài"} | {"value": -1}], cal, FACTORIES)
    ops = [{"type": "SET_OFF_DAYS", "rowUid": "a", "value": 3, "reason": "Bảo trì kéo dài", "by": "planner1", "at": "2026-09-21T08:00:00"}]
    rows, changed = apply_ops(base, {}, ops, cal, FACTORIES)
    row = rows[0]
    assert "a" in changed and row["extra"]["off_days_override"] == {"value": 3.0, "source": "MANUAL", "reason": "Bảo trì kéo dài", "by": "planner1", "at": "2026-09-21T08:00:00"}
    d = fx.active().display(row)["off_days_detail"]
    assert (d["calculated"], d["override"], d["effective"], d["source"], d["reason"], d["by"], d["overridden"]) == (1, 3.0, 3.0, "MANUAL", "Bảo trì kéo dài", "planner1", True)
    assert row["extra"]["serial"]["end_prod_date"] == pytest.approx(to_serial(FRI) + 3 + 3)     # END dùng giá trị áp dụng (3)
    # đổi lịch: calculated đổi, override GIỮ NGUYÊN
    rows2, _ = apply_ops(rows, {}, [{"type": "RECALC_LANE", "factory": "XN1", "line": "7"}], CalendarResolver([]), FACTORIES)
    d2 = fx.active().display(rows2[0])["off_days_detail"]
    assert d2["calculated"] == 0 and d2["effective"] == 3.0 and d2["overridden"]
    # Reset to Calculated
    rows3, _ = apply_ops(rows2, {}, [{"type": "RESET_OFF_DAYS", "rowUid": "a"}], cal, FACTORIES)
    d3 = fx.active().display(rows3[0])["off_days_detail"]
    assert d3["overridden"] is False and d3["effective"] == d3["calculated"] == 1 and "off_days_override" not in rows3[0]["extra"]
    assert rows3[0]["extra"]["serial"]["end_prod_date"] == pytest.approx(to_serial(FRI) + 3 + 1)


def test_off_days_v2_is_builtin_and_v1_workbook_set_still_available():
    assert fx.builtin_set().formulas["OFF_DAYS"].version == 2 and "OFF_DAYS_IN_SPAN" in fx.builtin_set().formulas["OFF_DAYS"].expression
    assert fx.workbook_set().formulas["OFF_DAYS"].version == 1 and "/ 7" in fx.workbook_set().formulas["OFF_DAYS"].expression
