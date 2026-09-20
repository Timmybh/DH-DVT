"""Lịch làm việc mức ngày (handoff §15–16).

Trạng thái ngày (hiệu lực): WORKING | OFF | OVERTIME. Kế thừa Company -> XN -> Line; phạm vi hẹp hơn thắng (XN "ghi đè" lịch công ty).
Mỗi quy tắc thuộc một LOẠI NGÀY do công ty định nghĩa (Nghỉ hàng tuần / Nghỉ Tết / Nghỉ lễ khác / Nghỉ khác / Ngoại lệ / Tăng ca / loại tự thêm);
loại ngày quyết định hiệu lực (OFF / WORKING / OVERTIME) — xí nghiệp dùng đúng danh mục tên này.

Một quy tắc đăng ký theo một trong các kiểu:
  DATE     một ngày hoặc khoảng ngày [rule_date, end_date]
  WEEKLY   lặp hằng tuần vào một thứ
  MONTHLY  lặp hằng tháng vào một ngày trong tháng (month_day)
  YEARLY   lặp hằng năm vào một ngày cố định (month, month_day)
Quy tắc lặp có thể giới hạn trong [valid_from, valid_to] (VD "trong năm 2027") hoặc để trống = mọi năm.
Thứ tự ưu tiên trong cùng một phạm vi: ngày/khoảng ngày (ngắn hơn thắng) > lặp hằng năm > lặp hằng tháng > lặp hằng tuần; cùng nhóm thì quy tắc đăng ký sau thắng.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

WORKING, OFF, OVERTIME = "WORKING", "OFF", "OVERTIME"
MAX_SCAN_DAYS = 3660  # loop guard: không quét quá ~10 năm

# rule_type lưu trong DB -> (hiệu lực, kiểu đăng ký)
RULE_TYPES: dict[str, tuple[str, str]] = {
    "DATE_OFF": (OFF, "DATE"), "DATE_WORK": (WORKING, "DATE"), "OVERTIME": (OVERTIME, "DATE"),  # "OVERTIME" giữ tên cũ để tương thích dữ liệu đã có
    "WEEKLY_OFF": (OFF, "WEEKLY"), "WEEKLY_WORK": (WORKING, "WEEKLY"), "WEEKLY_OT": (OVERTIME, "WEEKLY"),
    "MONTHLY_OFF": (OFF, "MONTHLY"), "MONTHLY_WORK": (WORKING, "MONTHLY"), "MONTHLY_OT": (OVERTIME, "MONTHLY"),
    "YEARLY_OFF": (OFF, "YEARLY"), "YEARLY_WORK": (WORKING, "YEARLY"), "YEARLY_OT": (OVERTIME, "YEARLY"),
}
KINDS = ("DATE", "WEEKLY", "MONTHLY", "YEARLY")


def rule_type_for(effect: str, kind: "str | bool") -> str:
    """Suy ra rule_type từ hiệu lực của loại ngày và kiểu đăng ký (bool cũ: True = WEEKLY, False = DATE)."""
    if isinstance(kind, bool):
        kind = "WEEKLY" if kind else "DATE"
    for name, (eff, k) in RULE_TYPES.items():
        if eff == effect and k == kind:
            return name
    raise ValueError(f"Không có rule_type cho hiệu lực {effect} / {kind}")


def kind_of(rule_type: str) -> str:
    return RULE_TYPES[rule_type][1]


@dataclass(frozen=True)
class Rule:
    scope_type: str  # COMPANY | XN | LINE
    scope_key: str  # '' | 'XN1' | 'XN1:07'
    rule_type: str  # xem RULE_TYPES
    weekday: int | None = None
    rule_date: date | None = None
    end_date: date | None = None  # khoảng ngày [rule_date, end_date]; None = một ngày
    day_type: str = ""  # mã loại ngày trong danh mục (TET, HOLIDAY, ...)
    rule_id: int | None = None
    note: str = ""
    month: int | None = None  # YEARLY
    month_day: int | None = None  # MONTHLY / YEARLY
    valid_from: date | None = None  # giới hạn hiệu lực của quy tắc lặp
    valid_to: date | None = None


def scope_chain(xn: str | None, line: str | None) -> list[tuple[str, str]]:
    """Thứ tự ưu tiên từ hẹp đến rộng."""
    chain: list[tuple[str, str]] = []
    if xn and line:
        chain.append(("LINE", f"{xn}:{line}"))
    if xn:
        chain.append(("XN", xn))
    chain.append(("COMPANY", ""))
    return chain


def _in_bounds(r: Rule, d: date) -> bool:
    return (r.valid_from is None or d >= r.valid_from) and (r.valid_to is None or d <= r.valid_to)


class CalendarResolver:
    def __init__(self, rules: Iterable[Rule]):
        self._dates: dict[tuple[str, str], list[tuple[date, date, Rule]]] = {}
        self._weekly: dict[tuple[str, str], dict[int, list[Rule]]] = {}
        self._monthly: dict[tuple[str, str], list[Rule]] = {}
        self._yearly: dict[tuple[str, str], list[Rule]] = {}
        for r in rules:
            key = (r.scope_type, r.scope_key)
            info = RULE_TYPES.get(r.rule_type)
            if info is None:
                continue
            kind = info[1]
            if kind == "DATE" and r.rule_date is not None:
                self._dates.setdefault(key, []).append((r.rule_date, r.end_date or r.rule_date, r))
            elif kind == "WEEKLY" and r.weekday is not None:
                self._weekly.setdefault(key, {}).setdefault(r.weekday, []).append(r)
            elif kind == "MONTHLY" and r.month_day is not None:
                self._monthly.setdefault(key, []).append(r)
            elif kind == "YEARLY" and r.month is not None and r.month_day is not None:
                self._yearly.setdefault(key, []).append(r)

    @staticmethod
    def _effect(rule: Rule) -> str:
        return RULE_TYPES[rule.rule_type][0]

    def _decide_chain(self, d: date, chain: list[tuple[str, str]]) -> tuple[str, str, str, Rule | None]:
        """(hiệu lực, scope_type, scope_key, quy tắc quyết định)."""
        for scope_type, scope_key in chain:
            key = (scope_type, scope_key)
            hits = [(end - start, i, r) for i, (start, end, r) in enumerate(self._dates.get(key, ())) if start <= d <= end]
            if hits:
                r = min(hits, key=lambda h: (h[0], -h[1]))[2]  # khoảng ngắn nhất; bằng nhau -> đăng ký sau
                return self._effect(r), scope_type, scope_key, r
            yearly = [r for r in self._yearly.get(key, ()) if r.month == d.month and r.month_day == d.day and _in_bounds(r, d)]
            if yearly:
                return self._effect(yearly[-1]), scope_type, scope_key, yearly[-1]
            monthly = [r for r in self._monthly.get(key, ()) if r.month_day == d.day and _in_bounds(r, d)]
            if monthly:
                return self._effect(monthly[-1]), scope_type, scope_key, monthly[-1]
            weekly = [r for r in self._weekly.get(key, {}).get(d.weekday(), ()) if _in_bounds(r, d)]
            if weekly:
                return self._effect(weekly[-1]), scope_type, scope_key, weekly[-1]
        return WORKING, "DEFAULT", "", None

    def status(self, d: date, xn: str | None = None, line: str | None = None) -> str:
        return self._decide_chain(d, scope_chain(xn, line))[0]

    def explain(self, d: date, xn: str | None = None, line: str | None = None) -> dict:
        """Trạng thái + LÝ DO: loại ngày, phạm vi quyết định, kế thừa hay ghi đè lịch của phạm vi rộng hơn."""
        chain = scope_chain(xn, line)
        effect, s_type, s_key, rule = self._decide_chain(d, chain)
        top = chain[0][0]
        inherited = s_type != top and s_type != "DEFAULT"
        overrides = False
        if not inherited and rule is not None and len(chain) > 1:
            parent = self._decide_chain(d, chain[1:])
            overrides = parent[0] != effect  # phạm vi hẹp làm khác kết quả của phạm vi rộng
        return {"status": effect, "scope": s_type, "scope_key": s_key, "day_type": rule.day_type if rule else "", "rule_id": rule.rule_id if rule else None,
                "note": rule.note if rule else "", "inherited": inherited, "overrides": overrides, "kind": kind_of(rule.rule_type) if rule else ""}

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
