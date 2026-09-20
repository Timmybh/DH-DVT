import json
from datetime import date

import pytest

from app.services import formula_runtime as fx
from app.services.formula import FormulaError, compile_expression, detect_cycle, parse, run_case, to_serial
from app.services.formula_service import CANONICAL_PATH

COLS = set(fx.BUILTIN_COLUMNS)


def ev(expr, inputs=None, prev=None, manual=None):
    node, _ = compile_expression(expr, COLS)
    return run_case(node, inputs or {}, prev, manual)


def test_arithmetic_precedence_and_functions():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("-4 + 10 / 4") == -1.5
    assert ev("IF(2 > 1, \"a\", \"b\")") == "a"
    assert ev("CEILING(0.925)") == 1 and ev("ROUND(0.5)") == 1 and ev("ROUND(0.4999)") == 0  # half-up
    assert ev("MAX(1, 5, 3)") == 5


def test_iferror_and_missing_inputs():
    assert ev("IFERROR(QUANTITY / CAPACITY, \"\")", {"QUANTITY": 100, "CAPACITY": 0}) == ""
    assert ev("IFERROR(QUANTITY / CAPACITY, \"\")", {"QUANTITY": 100, "CAPACITY": None}) == ""
    assert ev("IFERROR(QUANTITY / CAPACITY, \"\")", {"QUANTITY": 925, "CAPACITY": 1000}) == 0.925


def test_syntax_reference_and_function_errors():
    for bad in ("1 +", "FOO(1)", "QUANTITY $ 2", "IF(1, 2)", "(1 + 2"):
        with pytest.raises(FormulaError):
            compile_expression(bad, COLS)
    with pytest.raises(FormulaError, match="không tồn tại"):
        compile_expression("NOT_A_COLUMN + 1", COLS)
    with pytest.raises(FormulaError, match="ngữ nghĩa"):
        compile_expression("NEXT_SEQUENCE.END_BEGIN_DATE", COLS)


def test_dependencies_extracted_and_cycle_detected():
    _, deps = compile_expression("PREVIOUS_SEQUENCE.END_BEGIN_DATE + TOTAL_DAY + OFF_DAYS", COLS)
    assert deps.columns == {"TOTAL_DAY", "OFF_DAYS"} and deps.semantic == {("PREVIOUS_SEQUENCE", "END_BEGIN_DATE")}
    assert detect_cycle({"A": {"B"}, "B": {"C"}, "C": {"A"}}) is not None
    assert detect_cycle({"A": {"B"}, "B": {"C"}, "C": set()}) is None
    with pytest.raises(FormulaError, match="Vòng"):
        fx.build_set({"TOTAL_DAY": (1, "OFF_DAYS + 1"), "OFF_DAYS": (1, "TOTAL_DAY + 1")})


def test_every_published_canonical_case_passes():
    canon = json.loads(CANONICAL_PATH.read_text(encoding="utf-8"))
    fs = fx.builtin_set()
    total = 0
    for code, cases in canon["cases"].items():
        if code not in fs.formulas:
            continue
        node = fs.formulas[code].node
        for c in cases:
            actual = run_case(node, c.get("inputs") or {}, c.get("prev"), c.get("manual"))
            exp = c["expected"]
            ok = abs(actual - exp) <= canon["tolerance"] if isinstance(exp, (int, float)) else (actual or "") == (exp or "")
            assert ok, f"{code}/{c['kind']}: expected {exp}, got {actual}"
            total += 1
    assert total >= 20


def test_workbook_real_example_row():
    # Dòng thật trong workbook: 1110 / 1200 = 0.925 ; OFF = 0.925 / 7 ; END = BEGIN + 0.925 + OFF
    assert ev("IFERROR(QUANTITY / CAPACITY, \"\")", {"QUANTITY": 1110, "CAPACITY": 1200}) == pytest.approx(0.925)
    assert ev("IFERROR(TOTAL_DAY / 7, \"\")", {"TOTAL_DAY": 0.925}) == pytest.approx(0.1321428571, abs=1e-9)
    assert ev("BEGIN_PROD_DATE + TOTAL_DAY + OFF_DAYS", {"BEGIN_PROD_DATE": 45990.0, "TOTAL_DAY": 0.925, "OFF_DAYS": 0.925 / 7}) == pytest.approx(45991.0571428, abs=1e-6)


def _row(uid, begin=None, end=None, qty=1000, cap=500, **extra):
    r = {"row_uid": uid, "quantity": qty, "capacity": cap, "total_day": None, "begin_prod_date": None, "end_prod_date": None, "warehouse_date": None, "chd": None, "extra": extra}
    fs = fx.active()
    if begin:
        fs.set_stored(r, "BEGIN_PROD_DATE", to_serial(begin))
    fs.apply(r, None, "TOTAL_DAY")
    return r


def test_previous_sequence_chain_and_override_effective_value():
    fs = fx.active()
    a = _row("a", begin=date(2026, 9, 14))
    fs.apply(a, None, "END_BEGIN_DATE")
    b = _row("b")
    fs.apply(b, a, "BEGIN_PROD_DATE")
    fs.apply(b, a, "END_BEGIN_DATE")
    assert b["extra"]["serial"]["begin_prod_date"] == pytest.approx(a["extra"]["serial"]["end_prod_date"] + 1 / 9)  # a.TOTAL_DAY = 2 >= 1

    # override END của a -> b dùng EffectiveValue (giá trị override) thay vì kết quả công thức
    a["extra"]["overrides"] = {"end_prod_date": {"source": "OVERRIDE", "calculated": None}}
    fs.set_stored(a, "END_BEGIN_DATE", to_serial(date(2026, 9, 30)))
    fs.apply(b, a, "BEGIN_PROD_DATE")
    assert b["begin_prod_date"] == date(2026, 9, 30)
    # Return to Auto: bỏ override, tính lại -> chuỗi công thức được khôi phục
    a["extra"]["overrides"].clear()
    fs.apply(a, None, "END_BEGIN_DATE")
    fs.apply(b, a, "BEGIN_PROD_DATE")
    assert b["begin_prod_date"] == date(2026, 9, 16)


def test_previous_sequence_short_predecessor_has_no_changeover():
    fs = fx.active()
    a = _row("a", begin=date(2026, 9, 14), qty=200, cap=500)  # TOTAL_DAY 0.4 < 1
    fs.apply(a, None, "END_BEGIN_DATE")
    b = _row("b")
    fs.apply(b, a, "BEGIN_PROD_DATE")
    assert b["extra"]["serial"]["begin_prod_date"] == pytest.approx(a["extra"]["serial"]["end_prod_date"])


def test_first_in_lane_keeps_manual_anchor():
    fs = fx.active()
    a = _row("a", begin=date(2026, 9, 14))
    fs.apply(a, None, "BEGIN_PROD_DATE")  # không có dòng trước -> MANUAL()
    assert a["begin_prod_date"] == date(2026, 9, 14)


def test_display_columns_off_days_and_on_time():
    fs = fx.active()
    r = {"quantity": 1110, "capacity": 1200, "total_day": 0.925, "chd": date(2026, 9, 20), "extra": {"ref": {"ehd_etd": "2026-09-30"}}}
    d = fs.display(r)
    assert d["off_days"] == pytest.approx(0.925 / 7) and d["on_time"] == "DELAY"
    r["extra"]["ref"]["ehd_etd"] = "2026-09-20"
    assert fs.display(r)["on_time"] == "ON TIME"
    r["extra"]["ref"] = {}
    assert fs.display(r)["on_time"] is None


def test_workbook_lead_days_chain_and_sot():
    # END P DATE = END BE + LEAD_DAYS ; W.HOUSE = OUTPUT + LEAD_DAYS ; SOT = WORKING_DAY * WORKER / CAPACITY
    assert ev("END_BEGIN_DATE + LEAD_DAYS", {"END_BEGIN_DATE": 45991.05714, "LEAD_DAYS": 1}) == pytest.approx(45992.05714)
    assert ev("END_BEGIN_DATE + LEAD_DAYS", {"END_BEGIN_DATE": 45991.05714, "LEAD_DAYS": 3}) == pytest.approx(45994.05714)
    assert ev("IFERROR(WORKING_DAY * WORKER / CAPACITY, \"\")", {"WORKING_DAY": 540, "WORKER": 36, "CAPACITY": 1200}) == pytest.approx(16.2)
    assert ev("IFERROR(WORKING_DAY * WORKER / CAPACITY, \"\")", {"WORKING_DAY": 540, "WORKER": 36, "CAPACITY": 0}) == ""


def test_display_uses_lead_days_default_and_customer_value():
    fs = fx.active()
    r = {"quantity": 1000, "capacity": 500, "total_day": 2.0, "begin_prod_date": date(2026, 9, 14),
         "extra": {"serial": {"begin_prod_date": 46279.0, "end_prod_date": 46281.3}, "ref": {"worker": 36, "working_day": 540}}}
    d = fs.display(r)
    assert d["output_date"] == "2026-09-15"  # LEAD_DAYS mặc định 1
    assert d["sot"] == pytest.approx(540 * 36 / 500) and d["total_sot"] == pytest.approx(540 * 36 / 500 * 1000)
    r["extra"]["ref"]["lead_days"] = 3
    assert fs.display(r)["output_date"] == "2026-09-17"
