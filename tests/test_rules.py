from datetime import date

from app.core.permissions import ROLE_PERMISSIONS, permissions_for, validate_password
from app.services.rules import (
    classify_row,
    elapsed_pct,
    excel_serial_to_date,
    parse_month,
    safe_pct,
)


def test_excel_serial_to_date():
    assert excel_serial_to_date(45906.0) == date(2025, 9, 6)
    assert excel_serial_to_date(45993.05714285715) == date(2025, 12, 2)
    assert excel_serial_to_date("0xf") is None
    assert excel_serial_to_date(None) is None
    assert excel_serial_to_date(12.5) is None


def test_classify_row_late_uses_one_day_threshold():
    assert classify_row(-1.56, "ON TIME", "", None)[0] == "LATE"
    assert classify_row(-0.3, "ON TIME", "", None)[0] == "OK"
    assert classify_row(22.9, "ON TIME", None, None)[0] == "OK"


def test_classify_row_advance_and_material():
    assert classify_row(5.0, "ADVANCE", None, None)[0] == "ADVANCE"
    assert classify_row(5.0, "ON TIME", None, "CHƯA CÓ VẢI")[0] == "MATERIAL"
    assert classify_row(5.0, "ON TIME", "fabric NOT YET PURCHASE", None)[0] == "MATERIAL"
    assert classify_row(-3.0, "ON TIME", "chưa có vải", None)[0] == "LATE"


def test_pct_helpers():
    assert safe_pct(50, 200) == 25
    assert safe_pct(None, 200) is None
    assert safe_pct(10, 0) is None
    assert round(elapsed_pct(2026, 9, date(2026, 9, 15)), 1) == 50.0
    assert elapsed_pct(2026, 8, date(2026, 9, 15)) == 100.0
    assert elapsed_pct(2026, 10, date(2026, 9, 15)) == 0.0


def test_parse_month_falls_back_to_today():
    today = date(2026, 9, 20)
    assert parse_month("2026-03", today) == (2026, 3)
    assert parse_month("bad", today) == (2026, 9)
    assert parse_month(None, today) == (2026, 9)


def test_role_permissions_baseline():
    assert "planning.edit" not in ROLE_PERMISSIONS["VIEWER"]
    assert "planning.issue" not in ROLE_PERMISSIONS["PLANNER"]
    assert "planning.force_unlock" in permissions_for("ADMIN")
    assert permissions_for("UNKNOWN") == []


def test_password_policy():
    assert validate_password("short1") is not None
    assert validate_password("onlyletters") is not None
    assert validate_password("Abcdef12") is None


def test_gap_without_chd_is_not_late():
    from pathlib import Path  # noqa: F401
    from app.services.plan_import import _parse_plan_rows

    header = [None] * 40
    rows = [header, header]
    row = [None] * 40
    row[0], row[10], row[28], row[31], row[32] = 1.0, 100.0, None, -46266.5, "ON TIME"
    rows.append(row)
    good = [None] * 40
    good[0], good[10], good[28], good[31], good[32] = 1.0, 50.0, 46016.0, -3.2, "ON TIME"
    rows.append(good)
    parsed = _parse_plan_rows(iter(rows), "PLANNED")
    assert parsed[0]["risk"] == "OK" and parsed[0]["gap_days"] is None
    assert parsed[1]["risk"] == "LATE" and parsed[1]["gap_days"] == -3.2


def test_three_dimensions_are_independent():
    from app.services.rules import assess_factory

    # A. Chưa lên KH nhưng ĐÃ biết XN: KNOWN + mapping OK (thuộc pool chưa lên KH của XN đó)
    assert assess_factory("UNPLANNED", True, "2") == ("KNOWN", "OK", "")
    # B. Chưa lên KH và chưa biết XN: UNASSIGNED nhưng mapping vẫn OK — KHÔNG phải "chưa khớp"
    assert assess_factory("UNPLANNED", False, "") == ("UNASSIGNED", "OK", "")
    # FAC/XN lạ (VD 'DPC') -> UNASSIGNED + mapping WARNING, bất kể trạng thái kế hoạch
    fa, ms, note = assess_factory("UNPLANNED", False, "DPC")
    assert (fa, ms) == ("UNASSIGNED", "WARNING") and "DPC" in note
    # Đã lên KH mà thiếu XN -> cảnh báo mapping
    assert assess_factory("PLANNED", False, "")[:2] == ("UNASSIGNED", "WARNING")
    assert assess_factory("PLANNED", True, "1")[:2] == ("KNOWN", "OK")
