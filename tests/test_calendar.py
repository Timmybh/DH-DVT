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


# --------------------------------------------------------------------------- loại ngày, khoảng ngày, kế thừa & ghi đè theo xí nghiệp
def test_date_range_rule_and_shorter_range_wins():
    tet = Rule("COMPANY", "", "DATE_OFF", rule_date=date(2027, 2, 5), end_date=date(2027, 2, 13), day_type="TET", rule_id=1)
    work = Rule("COMPANY", "", "DATE_WORK", rule_date=date(2027, 2, 10), day_type="EXCEPTION", rule_id=2)          # ngoại lệ 1 ngày trong kỳ Tết
    cal = CalendarResolver([tet, work])
    assert cal.status(date(2027, 2, 4)) == WORKING and cal.status(date(2027, 2, 5)) == OFF and cal.status(date(2027, 2, 13)) == OFF and cal.status(date(2027, 2, 14)) == WORKING
    assert cal.status(date(2027, 2, 10)) == WORKING                                                             # khoảng ngắn hơn (1 ngày) thắng khoảng Tết
    assert cal.explain(date(2027, 2, 10))["day_type"] == "EXCEPTION" and cal.explain(date(2027, 2, 6))["day_type"] == "TET"
    assert cal.next_working_day(date(2027, 2, 4)) == date(2027, 2, 10)                                          # +1 ngày làm việc nhảy qua kỳ nghỉ Tết


def test_factory_inherits_company_calendar_and_can_override():
    cal = CalendarResolver([
        Rule("COMPANY", "", "WEEKLY_OFF", weekday=6, day_type="WEEKLY_OFF", rule_id=1),
        Rule("COMPANY", "", "DATE_OFF", rule_date=date(2026, 9, 2), day_type="HOLIDAY", rule_id=2, note="Quốc khánh"),
        Rule("XN", "XN2", "WEEKLY_WORK", weekday=6, day_type="EXCEPTION", rule_id=3),                            # XN2 làm Chủ nhật
        Rule("XN", "XN3", "DATE_WORK", rule_date=date(2026, 9, 2), day_type="EXCEPTION", rule_id=4),              # XN3 đi làm ngày lễ
        Rule("XN", "XN1", "OVERTIME", rule_date=date(2026, 9, 6), day_type="OVERTIME", rule_id=5),
    ])
    sun, holiday = date(2026, 9, 6), date(2026, 9, 2)
    # XN chưa ghi đè -> kế thừa nguyên lịch công ty, cùng tên loại ngày
    e = cal.explain(holiday, "XN1")
    assert (e["status"], e["day_type"], e["scope"], e["inherited"], e["overrides"]) == (OFF, "HOLIDAY", "COMPANY", True, False) and e["note"] == "Quốc khánh"
    # XN ghi đè
    e = cal.explain(holiday, "XN3")
    assert (e["status"], e["day_type"], e["scope"], e["inherited"], e["overrides"]) == (WORKING, "EXCEPTION", "XN", False, True)
    assert cal.status(sun, "XN2") == WORKING and cal.explain(sun, "XN2")["overrides"] is True
    assert cal.status(sun, "XN1") == OVERTIME and cal.status(sun) == OFF                                       # công ty vẫn nghỉ
    assert cal.status(date(2026, 9, 13), "XN2") == WORKING and cal.status(date(2026, 9, 13), "XN1") == OFF     # override lặp hằng tuần chỉ ảnh hưởng XN2
    # ghi đè cấp chuyền thắng ghi đè XN
    line = CalendarResolver([Rule("XN", "XN2", "WEEKLY_WORK", weekday=6), Rule("LINE", "XN2:7", "DATE_OFF", rule_date=sun, day_type="OTHER_OFF")])
    assert line.status(sun, "XN2", "7") == OFF and line.status(sun, "XN2", "8") == WORKING


def test_rule_type_for_maps_effect_and_recurrence():
    from app.services.calendar import rule_type_for

    assert rule_type_for(OFF, True) == "WEEKLY_OFF" and rule_type_for(OFF, False) == "DATE_OFF"
    assert rule_type_for(WORKING, True) == "WEEKLY_WORK" and rule_type_for(WORKING, False) == "DATE_WORK"
    assert rule_type_for(OVERTIME, True) == "WEEKLY_OT" and rule_type_for(OVERTIME, False) == "OVERTIME"


def test_day_type_catalog_defaults_validation_and_custom_types():
    import pytest
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.session import Base
    from app.models.planning import WorkingCalendarRule
    from app.services import calendar_types as ct

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    assert ct.list_types(db) == []                                                                              # không nạp sẵn: danh mục do người dùng định nghĩa
    assert ct.create_templates(db, "admin") == 6 and ct.create_templates(db, "admin") == 0                      # tạo mẫu theo yêu cầu, idempotent
    names = {t.code: t.name for t in ct.list_types(db)}
    assert names == {"WEEKLY_OFF": "Nghỉ hàng tuần", "TET": "Nghỉ Tết", "HOLIDAY": "Nghỉ lễ khác", "OTHER_OFF": "Nghỉ khác", "EXCEPTION": "Ngoại lệ", "OVERTIME": "Tăng ca"}
    by = {t.code: t for t in ct.list_types(db)}
    # mọi loại ngày đều đăng ký được theo ngày chi tiết lẫn kiểu lặp (loại chỉ gợi ý kiểu mặc định)
    n = ct.normalize_rule
    assert n(by["WEEKLY_OFF"], "WEEKLY", weekday=6)["rule_type"] == "WEEKLY_OFF"
    assert n(by["WEEKLY_OFF"], "NONE", rule_date=date(2027, 1, 1))["rule_type"] == "DATE_OFF"
    assert n(by["TET"], "NONE", rule_date=date(2027, 2, 5), end_date=date(2027, 2, 13))["rule_end_date"] == date(2027, 2, 13)
    assert n(by["HOLIDAY"], "YEARLY", month=9, month_day=2)["rule_type"] == "YEARLY_OFF"
    assert n(by["OTHER_OFF"], "MONTHLY", month_day=15, valid_from=date(2027, 1, 1), valid_to=date(2027, 12, 31))["rule_type"] == "MONTHLY_OFF"
    assert n(by["EXCEPTION"], "WEEKLY", weekday=6, effect="WORKING")["rule_type"] == "WEEKLY_WORK" and n(by["EXCEPTION"], "NONE", rule_date=date(2027, 1, 1), effect="WORKING")["rule_type"] == "DATE_WORK"
    # Ngoại lệ: hiệu lực chọn theo từng đăng ký (Làm việc ngày 1 / Nghỉ ngày 2); các loại khác cố định
    assert n(by["EXCEPTION"], "NONE", rule_date=date(2027, 1, 2), effect="OFF")["rule_type"] == "DATE_OFF"
    for bad_effect in (None, "OVERTIME", "X"):
        with pytest.raises(HTTPException):
            n(by["EXCEPTION"], "NONE", rule_date=date(2027, 1, 2), effect=bad_effect)
    with pytest.raises(HTTPException):
        n(by["TET"], "NONE", rule_date=date(2027, 2, 5), effect="WORKING")                                          # Nghỉ Tết cố định là nghỉ
    assert n(by["TET"], "NONE", rule_date=date(2027, 2, 5), effect="OFF")["rule_type"] == "DATE_OFF"
    assert n(by["OVERTIME"], "NONE", rule_date=date(2027, 1, 2))["rule_type"] == "OVERTIME" and n(by["OVERTIME"], "WEEKLY", weekday=5)["rule_type"] == "WEEKLY_OT"
    for args in (("NONE",), ("NONE", None, None, None, date(2027, 2, 13), date(2027, 2, 5)), ("NONE", None, None, None, date(2027, 1, 1), date(2028, 6, 1)), ("WEEKLY",), ("WEEKLY", 9),
                 ("MONTHLY",), ("MONTHLY", None, None, 32), ("YEARLY", None, 2, 30), ("YEARLY", None, None, 5), ("YEARLY", None, 13, 5), ("WEEKLY", 6, None, None, date(2027, 1, 1)),
                 ("MONTHLY", None, None, 5, None, None, date(2027, 5, 1), date(2027, 1, 1)), ("DAILY",)):
        with pytest.raises(HTTPException):
            n(by["TET"], *args)
    # công ty đổi tên, thêm loại riêng; không xóa loại đang được dùng
    assert ct.update_type(db, "HOLIDAY", {"name": "Nghỉ lễ quốc gia", "color": "#112233"}, "admin").name == "Nghỉ lễ quốc gia"
    with pytest.raises(HTTPException):
        ct.update_type(db, "TET", {"name": "nghỉ lễ QUỐC GIA"}, "admin")                                        # trùng tên
    with pytest.raises(HTTPException):
        ct.update_type(db, "TET", {"color": "red"}, "admin")
    assert ct.update_type(db, "OTHER_OFF", {"is_active": False}, "admin").is_active is False                    # loại mẫu cũng tắt được
    ct.update_type(db, "OTHER_OFF", {"is_active": True}, "admin")
    ct.delete_type(db, "TET")                                                                                   # và xóa được khi chưa dùng
    assert "TET" not in {t.code for t in ct.list_types(db)}
    custom = ct.create_type(db, "Nghỉ bảo trì máy", "OFF", "DATE", "#123456", "admin")
    assert custom.code == "NGHI_BAO_TRI_MAY" and not custom.is_system
    db.add(WorkingCalendarRule(scope_type="XN", scope_key="XN1", rule_type="DATE_OFF", day_type=custom.code, rule_date=date(2027, 3, 1)))
    db.commit()
    with pytest.raises(HTTPException):
        ct.delete_type(db, custom.code)                                                                         # đang được dùng
    with pytest.raises(HTTPException):
        ct.create_type(db, "Tăng ca", "OVERTIME", "ANY", "#123456", "admin")                                    # trùng tên loại mặc định
    # quy tắc cũ được gán loại ngày tương ứng
    db.add_all([WorkingCalendarRule(scope_type="COMPANY", scope_key="", rule_type="WEEKLY_OFF", weekday=6), WorkingCalendarRule(scope_type="COMPANY", scope_key="", rule_type="DATE_OFF", rule_date=date(2027, 4, 30)),
                WorkingCalendarRule(scope_type="XN", scope_key="XN1", rule_type="OVERTIME", rule_date=date(2027, 5, 1))])
    db.commit()
    assert ct.backfill_rule_day_types(db) == 3
    assert sorted(r.day_type for r in db.query(WorkingCalendarRule).filter(WorkingCalendarRule.scope_key != "XN1")) == ["OTHER_OFF", "WEEKLY_OFF"]
    # nếu loại mẫu tương ứng không tồn tại (người dùng đã xóa/không tạo) thì để trống, không bịa loại ngày
    db.add(WorkingCalendarRule(scope_type="COMPANY", scope_key="", rule_type="OVERTIME", rule_date=date(2027, 6, 1)))
    ct.delete_type(db, "OVERTIME") if not db.query(WorkingCalendarRule).filter(WorkingCalendarRule.day_type == "OVERTIME").count() else None
    db.commit()


# --------------------------------------------------------------------------- kiểu lặp: hằng tuần / hằng tháng / hằng năm, có giới hạn trong năm
def test_repeat_kinds_yearly_monthly_weekly_with_year_bounds():
    y27 = (date(2027, 1, 1), date(2027, 12, 31))
    cal = CalendarResolver([
        Rule("COMPANY", "", "WEEKLY_OFF", weekday=6, day_type="WEEKLY_OFF", rule_id=1, valid_from=y27[0], valid_to=y27[1]),           # Chủ nhật nghỉ, CHỈ trong 2027
        Rule("COMPANY", "", "YEARLY_OFF", month=9, month_day=2, day_type="HOLIDAY", rule_id=2),                                        # Quốc khánh 2/9 mọi năm
        Rule("COMPANY", "", "MONTHLY_OFF", month_day=15, day_type="OTHER_OFF", rule_id=3, valid_from=date(2027, 6, 1), valid_to=date(2027, 8, 31)),   # ngày 15 hằng tháng, chỉ hè 2027
        Rule("COMPANY", "", "MONTHLY_OT", month_day=28, day_type="OVERTIME", rule_id=4),
    ])
    assert cal.status(date(2027, 3, 7)) == OFF and cal.status(date(2028, 3, 5)) == WORKING                                        # ngoài năm giới hạn thì không lặp
    assert cal.status(date(2027, 9, 2)) == OFF and cal.status(date(2031, 9, 2)) == OFF and cal.explain(date(2030, 9, 2))["day_type"] == "HOLIDAY"   # hằng năm, không giới hạn
    assert cal.status(date(2027, 7, 15)) == OFF and cal.status(date(2027, 9, 15)) == WORKING and cal.status(date(2027, 6, 15)) == OFF
    assert cal.status(date(2027, 2, 28)) == OVERTIME and cal.explain(date(2027, 2, 28))["kind"] == "MONTHLY"
    # ưu tiên trong cùng phạm vi: ngày cụ thể > hằng năm > hằng tháng > hằng tuần
    cal2 = CalendarResolver([
        Rule("COMPANY", "", "WEEKLY_OFF", weekday=6, day_type="WEEKLY_OFF"),
        Rule("COMPANY", "", "MONTHLY_WORK", month_day=5, day_type="EXCEPTION"),
        Rule("COMPANY", "", "YEARLY_OT", month=7, month_day=5, day_type="OVERTIME"),
        Rule("COMPANY", "", "DATE_OFF", rule_date=date(2027, 12, 5), day_type="OTHER_OFF"),
    ])
    sun_5 = date(2027, 9, 5)                                                                                                      # Chủ nhật, ngày 5
    assert sun_5.weekday() == 6 and cal2.status(sun_5) == WORKING                                                                # hằng tháng (làm) thắng hằng tuần (nghỉ)
    assert cal2.status(date(2027, 7, 5)) == OVERTIME and cal2.status(date(2027, 12, 5)) == OFF                                    # hằng năm thắng hằng tháng; ngày cụ thể thắng tất cả
    # XN ghi đè lịch lặp của công ty: XN2 vẫn làm các Chủ nhật trong quý 4/2027
    cal3 = CalendarResolver([Rule("COMPANY", "", "WEEKLY_OFF", weekday=6), Rule("XN", "XN2", "WEEKLY_WORK", weekday=6, day_type="EXCEPTION", valid_from=date(2027, 10, 1), valid_to=date(2027, 12, 31))])
    assert cal3.status(date(2027, 10, 3), "XN2") == WORKING and cal3.status(date(2027, 9, 26), "XN2") == OFF and cal3.status(date(2027, 10, 3), "XN1") == OFF
    from app.services.calendar import kind_of, rule_type_for

    assert rule_type_for(OFF, "YEARLY") == "YEARLY_OFF" and rule_type_for(OVERTIME, "MONTHLY") == "MONTHLY_OT" and kind_of("WEEKLY_WORK") == "WEEKLY"
