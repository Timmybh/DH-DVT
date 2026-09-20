"""Lịch làm việc mức ngày (handoff §15–16).

Trạng thái ngày: WORKING | OFF | OVERTIME. Kế thừa Company -> XN -> Line; phạm vi hẹp hơn thắng.
Trong cùng một phạm vi, quy tắc theo ngày cụ thể (DATE_OFF/OVERTIME) thắng quy tắc lặp hằng tuần (WEEKLY_OFF).
OVERTIME ở phạm vi hẹp có thể biến một ngày OFF (từ phạm vi rộng) thành ngày làm việc hợp lệ.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

WORKING, OFF, OVERTIME = "WORKING", "OFF", "OVERTIME"
MAX_SCAN_DAYS = 3660  # loop guard: không quét quá ~10 năm


@dataclass(frozen=True)
class Rule:
    scope_type: str  # COMPANY | XN | LINE
    scope_key: str  # '' | 'XN1' | 'XN1:07'
    rule_type: str  # WEEKLY_OFF | DATE_OFF | OVERTIME
    weekday: int | None = None
    rule_date: date | None = None


def scope_chain(xn: str | None, line: str | None) -> list[tuple[str, str]]:
    """Thứ tự ưu tiên từ hẹp đến rộng."""
    chain: list[tuple[str, str]] = []
    if xn and line:
        chain.append(("LINE", f"{xn}:{line}"))
    if xn:
        chain.append(("XN", xn))
    chain.append(("COMPANY", ""))
    return chain


class CalendarResolver:
    def __init__(self, rules: Iterable[Rule]):
        self._date_rules: dict[tuple[str, str, date], str] = {}
        self._weekly: dict[tuple[str, str], set[int]] = {}
        for r in rules:
            key = (r.scope_type, r.scope_key)
            if r.rule_type == "WEEKLY_OFF" and r.weekday is not None:
                self._weekly.setdefault(key, set()).add(r.weekday)
            elif r.rule_type in ("DATE_OFF", "OVERTIME") and r.rule_date is not None:
                self._date_rules[(r.scope_type, r.scope_key, r.rule_date)] = OFF if r.rule_type == "DATE_OFF" else OVERTIME

    def status(self, d: date, xn: str | None = None, line: str | None = None) -> str:
        for scope_type, scope_key in scope_chain(xn, line):
            explicit = self._date_rules.get((scope_type, scope_key, d))
            if explicit:
                return explicit
            if d.weekday() in self._weekly.get((scope_type, scope_key), ()):
                return OFF
        return WORKING

    def is_working_day(self, d: date, xn: str | None = None, line: str | None = None) -> bool:
        return self.status(d, xn, line) != OFF

    def next_working_day(self, d: date, xn: str | None = None, line: str | None = None) -> date:
        """Ngày làm việc đầu tiên SAU d (không tính d)."""
        cur = d
        for _ in range(MAX_SCAN_DAYS):
            cur += timedelta(days=1)
            if self.is_working_day(cur, xn, line):
                return cur
        raise ValueError("Không tìm được ngày làm việc kế tiếp (lịch có thể đang OFF liên tục)")

    def previous_working_day(self, d: date, xn: str | None = None, line: str | None = None) -> date:
        cur = d
        for _ in range(MAX_SCAN_DAYS):
            cur -= timedelta(days=1)
            if self.is_working_day(cur, xn, line):
                return cur
        raise ValueError("Không tìm được ngày làm việc trước đó")

    def add_working_days(self, d: date, n: int, xn: str | None = None, line: str | None = None) -> date:
        """ADD_WORKING_DAYS(d, 1) = ngày làm việc kế tiếp sau d, bỏ qua ngày OFF. n=0 trả về d; n<0 đi lùi."""
        cur = d
        step = self.next_working_day if n > 0 else self.previous_working_day
        for _ in range(abs(n)):
            cur = step(cur, xn, line)
        return cur


def off_days(total_day: float | None) -> int:
    """OFF_DAYS = TOTAL_DAY / 7, làm tròn half-up (handoff §16). Khác với ngày OFF của Calendar."""
    if not total_day or total_day <= 0:
        return 0
    return int(total_day / 7 + 0.5)
