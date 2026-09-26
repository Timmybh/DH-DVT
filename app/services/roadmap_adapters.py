"""Allowlist adapter tính toán Roadmap (Task 6 — Issue #13, GPT APPROVED_TO_IMPLEMENT + FORMULA CONTRACT).

CHỈ 2 adapter, code-defined, KHÔNG formula builder tự do:
  LABOR_GAP_REQUIREMENT_V1, MACHINE_GAP_REQUIREMENT_V1.
Ngữ nghĩa: INCREMENTAL GAP — trả lời "để bù output gap tăng thêm này cần tăng thêm bao nhiêu labor/machine theo productivity đã duyệt".
Không tính total resource requirement, không trừ available labor/machine (chỉ là context), không quy đổi period, không derive productivity từ DB.

    raw = gap_output / productivity
    additional = CEIL(raw)                       # nguyên, không âm; không banker rounding
    proposed_increment = additional * productivity
    remaining_gap_after_proposal = gap_output - proposed_increment   # giữ dấu (âm = vượt gap do làm tròn)

Tính bằng Decimal (từ repr của số) để CEIL không lệch do sai số float (vd 3*1.1/1.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Callable

PERIOD_TYPES = ("MONTH", "YEAR")
REQUIREMENT_BASIS = "INCREMENTAL_GAP"
ROUNDING_RULE = "CEIL"


class AdapterInputError(ValueError):
    """Input vi phạm contract adapter. `code` ổn định để engine/API ánh xạ (PERIOD_MISMATCH, UNIT_MISMATCH, ...)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _dec(v, name: str) -> Decimal:
    if isinstance(v, bool) or v is None:
        raise AdapterInputError("INVALID_INPUT", f"{name} phải là số")
    try:
        d = Decimal(str(v))
    except Exception:
        raise AdapterInputError("INVALID_INPUT", f"{name} phải là số") from None
    if not d.is_finite():
        raise AdapterInputError("INVALID_INPUT", f"{name} phải là số hữu hạn")
    return d


def _pos(v, name: str) -> Decimal:
    d = _dec(v, name)
    if d <= 0:
        raise AdapterInputError("INVALID_INPUT", f"{name} phải > 0")
    return d


def _count(v, name: str) -> int:
    if isinstance(v, bool) or v is None:
        raise AdapterInputError("INVALID_INPUT", f"{name} phải là số nguyên >= 0")
    if isinstance(v, float):
        if not v.is_integer():
            raise AdapterInputError("INVALID_INPUT", f"{name} phải là số nguyên >= 0")
        v = int(v)
    if not isinstance(v, int) or v < 0:
        raise AdapterInputError("INVALID_INPUT", f"{name} phải là số nguyên >= 0")
    return v


def _num(d: Decimal) -> float:
    return float(round(d, 6))


@dataclass(frozen=True)
class Adapter:
    code: str
    version: str
    proposal_type: str
    resource: str  # worker | machine
    productivity_key: str  # tên field productivity trong input
    unit_prefix: str  # sp/worker | sp/machine
    available_key: str
    result_keys: tuple[str, ...]  # field số dùng để đối chiếu sample calculation
    needs_machine_type: bool
    run: Callable[[dict], dict]
    description: str

    def unit_for(self, period_type: str) -> str:
        return f"{self.unit_prefix}/{period_type}"

    def contract(self) -> dict:
        return {"adapter_code": self.code, "adapter_version": self.version, "proposal_type": self.proposal_type, "requirement_basis": REQUIREMENT_BASIS,
                "rounding_rule": ROUNDING_RULE, "productivity_key": self.productivity_key, "productivity_units": [self.unit_for(p) for p in PERIOD_TYPES],
                "needs_machine_type": self.needs_machine_type, "available_key": self.available_key, "result_keys": list(self.result_keys), "description": self.description}


def _common(inp: dict, adapter: "Adapter") -> tuple[Decimal, str, Decimal, int]:
    gap = _pos(inp.get("gap_output"), "gap_output")
    if inp.get("gap_unit") != "sp":
        raise AdapterInputError("UNIT_MISMATCH", f"gap_unit phải là 'sp' (nhận '{inp.get('gap_unit')}') — không quy đổi đơn vị")
    period = inp.get("period_type")
    if period not in PERIOD_TYPES:
        raise AdapterInputError("PERIOD_MISMATCH", f"period_type phải là một trong {PERIOD_TYPES}")
    prod = _pos(inp.get(adapter.productivity_key), adapter.productivity_key)
    expected_unit = adapter.unit_for(period)
    if inp.get("productivity_unit") != expected_unit:
        raise AdapterInputError("PERIOD_MISMATCH", f"productivity_unit phải là '{expected_unit}' khớp period target (nhận '{inp.get('productivity_unit')}') — không quy đổi period")
    avail = _count(inp.get(adapter.available_key), adapter.available_key)
    return gap, period, prod, avail


def _labor(inp: dict) -> dict:
    gap, period, prod, avail = _common(inp, ADAPTERS["LABOR_GAP_REQUIREMENT_V1"])
    raw = gap / prod
    add = int(raw.to_integral_value(rounding=ROUND_CEILING))
    inc = add * prod
    return {"requirement_basis": REQUIREMENT_BASIS, "required_incremental_labor_raw": _num(raw), "required_incremental_labor": add, "additional_labor": add,
            "available_labor": avail, "proposed_increment": _num(inc), "remaining_gap_after_proposal": _num(gap - inc), "rounding_rule": ROUNDING_RULE,
            "period_type": period, "productivity_per_worker": _num(prod), "productivity_unit": inp["productivity_unit"]}


def _machine(inp: dict) -> dict:
    gap, period, prod, avail = _common(inp, ADAPTERS["MACHINE_GAP_REQUIREMENT_V1"])
    mt = inp.get("machine_type_code")
    if not isinstance(mt, str) or not mt.strip():
        raise AdapterInputError("INVALID_INPUT", "machine_type_code bắt buộc (explicit, 1 rule = 1 loại máy)")
    raw = gap / prod
    add = int(raw.to_integral_value(rounding=ROUND_CEILING))
    inc = add * prod
    return {"requirement_basis": REQUIREMENT_BASIS, "machine_type_code": mt.strip(), "required_incremental_machines_raw": _num(raw), "required_incremental_machines": add,
            "additional_machines": add, "available_machines": avail, "proposed_increment": _num(inc), "remaining_gap_after_proposal": _num(gap - inc), "rounding_rule": ROUNDING_RULE,
            "period_type": period, "productivity_per_machine": _num(prod), "productivity_unit": inp["productivity_unit"]}


ADAPTERS: dict[str, Adapter] = {
    "LABOR_GAP_REQUIREMENT_V1": Adapter(
        "LABOR_GAP_REQUIREMENT_V1", "1", "LABOR_RECRUITMENT", "worker", "productivity_per_worker", "sp/worker", "available_labor",
        ("required_incremental_labor", "additional_labor", "proposed_increment", "remaining_gap_after_proposal"), False, _labor,
        "additional_labor = CEIL(gap_output / productivity_per_worker) — incremental gap, không trừ available_labor"),
    "MACHINE_GAP_REQUIREMENT_V1": Adapter(
        "MACHINE_GAP_REQUIREMENT_V1", "1", "MACHINE_PURCHASE", "machine", "productivity_per_machine", "sp/machine", "available_machines",
        ("required_incremental_machines", "additional_machines", "proposed_increment", "remaining_gap_after_proposal"), True, _machine,
        "additional_machines = CEIL(gap_output / productivity_per_machine) — incremental gap, không trừ available_machines"),
}
ALLOWLISTED_ADAPTERS = tuple(ADAPTERS)


def get_adapter(code: str) -> Adapter | None:
    return ADAPTERS.get(code)


def run_adapter(code: str, inp: dict) -> dict:
    a = ADAPTERS.get(code)
    if a is None:
        raise AdapterInputError("ADAPTER_NOT_ALLOWLISTED", f"Adapter '{code}' không nằm trong allowlist {ALLOWLISTED_ADAPTERS}")
    return a.run(inp)


def same_number(a, b) -> bool:
    """So sánh chính xác (Decimal) hai số của sample calculation."""
    try:
        return Decimal(str(a)) == Decimal(str(b)) and math.isfinite(float(a))
    except Exception:
        return False
