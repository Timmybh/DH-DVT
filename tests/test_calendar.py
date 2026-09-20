from datetime import date

from app.services.calendar import OFF, OVERTIME, WORKING, CalendarResolver, Rule, off_days

SUN = 6


def company_sunday_off():
    return [Rule("COMPANY", "", "WEEKLY_OFF", weekday=SUN)]


def test_company_weekly_off():
    cal = CalendarResolver(company_sunday_off())
    assert cal.status(date(2026, 9, 20)) == OFF  # Chủ nhật
    assert cal.status(date(2026, 9, 21)) == WORKING


def test_handoff_example_line_beats_xn_beats_company():
    # Company: Sunday = OFF; XN1: 20/09 = OVERTIME; Line 7: 20/09 = OFF
    cal = CalendarResolver(
        [
            *company_sunday_off(),
            Rule("XN", "XN1", "OVERTIME", rule_date=date(2026, 9, 20)),
            Rule("LINE", "XN1:7", "DATE_OFF", rule_date=date(2026, 9, 20)),
        ]
    )
    d = date(2026, 9, 20)
    assert cal.status(d, "XN1", "7") == OFF  # Line 7 = OFF
    assert cal.status(d, "XN1", "8") == OVERTIME  # các chuyền khác của XN1 làm việc
    assert cal.status(d, "XN2", "1") == OFF  # XN khác theo Company
    assert cal.is_working_day(d, "XN1", "8") and not cal.is_working_day(d, "XN1", "7")


def test_date_rule_beats_weekly_in_same_scope():
    cal = CalendarResolver([*company_sunday_off(), Rule("COMPANY", "", "OVERTIME", rule_date=date(2026, 9, 20))])
    assert cal.status(date(2026, 9, 20)) == OVERTIME


def test_add_working_days_skips_off_days():
    cal = CalendarResolver([*company_sunday_off(), Rule("COMPANY", "", "DATE_OFF", rule_date=date(2026, 9, 21))])
    fri = date(2026, 9, 18)
    assert cal.add_working_days(fri, 1) == date(2026, 9, 19)  # Thứ bảy làm việc
    assert cal.add_working_days(date(2026, 9, 19), 1) == date(2026, 9, 22)  # bỏ Chủ nhật 20 và nghỉ lễ 21
    assert cal.add_working_days(fri, 0) == fri
    assert cal.add_working_days(date(2026, 9, 22), -1) == date(2026, 9, 19)
    assert cal.next_working_day(date(2026, 9, 19)) == date(2026, 9, 22)
    assert cal.previous_working_day(date(2026, 9, 22)) == date(2026, 9, 19)


def test_overtime_makes_off_day_valid_for_add_working_days():
    cal = CalendarResolver([*company_sunday_off(), Rule("XN", "XN1", "OVERTIME", rule_date=date(2026, 9, 20))])
    assert cal.add_working_days(date(2026, 9, 19), 1, "XN1", "7") == date(2026, 9, 20)
    assert cal.add_working_days(date(2026, 9, 19), 1, "XN2", "7") == date(2026, 9, 21)


def test_all_days_off_hits_loop_guard():
    cal = CalendarResolver([Rule("COMPANY", "", "WEEKLY_OFF", weekday=d) for d in range(7)])
    try:
        cal.next_working_day(date(2026, 1, 1))
    except ValueError:
        return
    raise AssertionError("phải báo lỗi khi lịch OFF liên tục")


def test_off_days_half_up_rounding():
    # Ví dụ trong handoff §16
    assert off_days(3) == 0
    assert off_days(4) == 1
    assert off_days(8) == 1
    assert off_days(11) == 2
    assert off_days(0) == 0 and off_days(None) == 0
