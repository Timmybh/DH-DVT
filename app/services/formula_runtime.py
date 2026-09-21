"""Runtime tính công thức trên dòng Planning: tính giá trị, EffectiveValue (Calculated/Override), tham chiếu dòng trước.

Dòng là dict như PlanningVersionRow. Ngày lưu ở cột ``date`` (làm tròn xuống) VÀ số serial có phần lẻ trong
``extra["serial"][<trường>]`` — cần thiết vì workbook nối chuỗi BEGIN/END bằng số lẻ ngày.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.services import formula_defs as defs
from app.services.formula import (
    Context, FormulaError, MAX_DEPTH, Node, Dependencies, compile_expression, detect_cycle, evaluate, from_serial, to_serial,
)


@dataclass(frozen=True)
class ColumnMeta:
    code: str
    label: str
    workbook: str
    value_type: str  # number | date | text
    input_type: str
    list_source: str
    source: str

    @property
    def row_field(self) -> str | None:
        return self.source[4:] if self.source.startswith("row:") else None

    @property
    def ref_key(self) -> str | None:
        return self.source[4:] if self.source.startswith("ref:") else None


# Lịch làm việc dùng cho công thức OFF_DAYS (nạp từ DB bởi planning_service.load_resolver; engine thuần đặt qua apply_ops/recheck)
_calendar = None
MAX_SPAN_DAYS = 3660


def set_calendar(cal) -> None:
    global _calendar
    _calendar = cal


def calendar_off_days(row: dict, begin_serial: float, working_days: float) -> float:
    """Số ngày NGHỈ gặp phải khi làm đủ `working_days` ngày làm việc, bắt đầu từ ngày vào chuyền (tính cả ngày bắt đầu).
    Ngày làm việc cuối có thể là ngày lẻ (0,5 ngày vẫn chiếm trọn một ngày lịch). Ngày Nghỉ sau ngày làm việc cuối không tính."""
    cal = _calendar
    if cal is None or working_days <= 0:
        return 0.0
    cur = from_serial(begin_serial)
    if cur is None:
        raise FormulaError("Ngày vào chuyền không hợp lệ")
    xn, line = row.get("factory_code") or None, row.get("primary_line") or None
    remaining, off, guard = float(working_days), 0, 0
    while remaining > 1e-9:
        if guard >= MAX_SPAN_DAYS:
            raise FormulaError("Lịch làm việc đang Nghỉ liên tục quá dài — không tính được OFF DAYS")
        if cal.is_working_day(cur, xn, line):
            remaining -= 1
        else:
            off += 1
        cur += timedelta(days=1)
        guard += 1
    return float(off)


BUILTIN_COLUMNS: dict[str, ColumnMeta] = {c[0]: ColumnMeta(c[0], c[1], c[2], c[3], c[4], c[5], c[6]) for c in defs.COLUMNS}


@dataclass
class CompiledFormula:
    code: str
    version: int
    expression: str
    node: Node
    deps: Dependencies


class FormulaSet:
    """Tập công thức đang hiệu lực (mỗi cột một phiên bản đã Publish)."""

    def __init__(self, formulas: dict[str, CompiledFormula], columns: dict[str, ColumnMeta] | None = None):
        self.formulas = formulas
        self.columns = columns or BUILTIN_COLUMNS

    # ------------------------------------------------------------ giá trị lưu trên dòng
    def _ref(self, row: dict) -> dict:
        return (row.get("extra") or {}).get("ref") or row.get("ref") or {}

    def stored(self, row: dict, code: str) -> Any:
        meta = self.columns[code]
        if meta.row_field:
            f = meta.row_field
            if f in defs.DATE_ROW_FIELDS:
                serial = ((row.get("extra") or {}).get("serial") or {}).get(f)
                return serial if serial is not None else to_serial(row.get(f))
            return row.get(f)
        if meta.ref_key:
            v = self._ref(row).get(meta.ref_key)
            if meta.code == "LEAD_DAYS" and v is None:
                return 1.0  # mặc định 1 ngày (workbook: OUT PUT DATE = ngày vào chuyền + 1)
            if meta.value_type == "date" and isinstance(v, str):
                try:
                    return to_serial(date.fromisoformat(v[:10]))
                except ValueError:
                    return None
            return v
        return None

    def is_overridden(self, row: dict, code: str) -> bool:
        f = self.columns[code].row_field
        return bool(f and f in ((row.get("extra") or {}).get("overrides") or {}))

    def set_stored(self, row: dict, code: str, value: Any) -> None:
        meta = self.columns[code]
        f = meta.row_field
        if not f:
            return
        if f in defs.DATE_ROW_FIELDS:
            serial = to_serial(value)
            row[f] = from_serial(serial)
            extra = row.setdefault("extra", {})
            ser = extra.setdefault("serial", {})
            if serial is None:
                ser.pop(f, None)
            else:
                ser[f] = serial
        else:
            row[f] = value

    # ------------------------------------------------------------ tính
    def has(self, code: str) -> bool:
        return code in self.formulas

    def calculated(self, row: dict, prev: dict | None, code: str, _stack: tuple[str, ...] = ()) -> Any:
        """Kết quả CÔNG THỨC (CalculatedValue), bỏ qua override. Lỗi tính -> FormulaError."""
        f = self.formulas.get(code)
        if f is None:
            return self.stored(row, code)
        if code in _stack or len(_stack) > MAX_DEPTH:
            raise FormulaError(f"Vòng lặp công thức: {' → '.join((*_stack, code))}")
        stack = (*_stack, code)
        ctx = Context(
            get=lambda c: self.effective(row, prev, c, stack),
            prev=lambda c: self._prev_value(prev, c),
            manual=lambda: self.stored(row, code),
            off_days=lambda b, w: calendar_off_days(row, b, w),
        )
        return evaluate(f.node, ctx)

    def effective(self, row: dict, prev: dict | None, code: str, _stack: tuple[str, ...] = ()) -> Any:
        """EffectiveValue: OVERRIDE thắng; nếu không thì công thức (nếu có); nếu không thì giá trị nhập."""
        if code == "OFF_DAYS":  # OFF DAYS ghi đè (nhập tay / lấy từ Excel) nằm ở extra.off_days_override
            ov = (row.get("extra") or {}).get("off_days_override") or {}
            if ov.get("value") is not None:
                return float(ov["value"])
        if self.is_overridden(row, code) or code not in self.formulas:
            return self.stored(row, code)
        try:
            v = self.calculated(row, prev, code, _stack)
        except FormulaError:
            if len(_stack) > 0:
                raise
            return None
        return None if v == "" else v

    def _prev_value(self, prev: dict | None, code: str) -> Any:
        if prev is None:
            return None
        v = self.stored(prev, code)
        if v is None and code in self.formulas:  # cột chỉ tính (không lưu) -> tính trên dòng trước, không đệ quy chuỗi dòng
            try:
                v = self.calculated(prev, None, code)
            except FormulaError:
                v = None
        return None if v == "" else v

    def apply(self, row: dict, prev: dict | None, code: str) -> Any:
        """Tính lại và GHI vào dòng (cột có trường lưu trữ). Bỏ qua nếu đang override."""
        if self.is_overridden(row, code):
            return self.stored(row, code)
        try:
            v = self.calculated(row, prev, code)
        except FormulaError:
            v = None
        v = None if v == "" else v
        if self.columns[code].value_type == "date" and v is not None:
            v = float(v)
        self.set_stored(row, code, v)
        return v

    def display(self, row: dict) -> dict[str, Any]:
        """Cột chỉ tính, không lưu trong DB (OFF_DAYS, ON_TIME) — để UI/API hiển thị."""
        out: dict[str, Any] = {}
        for code in ("OFF_DAYS", "ON_TIME", "SOT", "TOTAL_SOT", "OUTPUT_DATE", "END_PROD_DATE", "END_WAREHOUSE_IMPORT"):
            if code in self.formulas:
                try:
                    v = self.calculated(row, None, code)
                except FormulaError:
                    v = None
                if code == "OFF_DAYS":  # giữ riêng: giá trị tính / ghi đè / nguồn / áp dụng
                    ov = (row.get("extra") or {}).get("off_days_override") or {}
                    has = ov.get("value") is not None
                    v = None if v == "" else v
                    out["off_days"] = float(ov["value"]) if has else v
                    out["off_days_detail"] = {"calculated": v, "override": float(ov["value"]) if has else None, "source": ov.get("source") if has else None, "reason": ov.get("reason", "") if has else "",
                                              "by": ov.get("by", "") if has else "", "at": ov.get("at", "") if has else "", "effective": out["off_days"], "overridden": has}
                    continue
                v = None if v == "" else v
                if v is not None and self.columns[code].value_type == "date":
                    v = defs.serial_to_iso(float(v))
                out[code.lower()] = v
        return out

    # ------------------------------------------------------------ phiên bản
    def version_set(self) -> dict[str, int]:
        return {c: f.version for c, f in sorted(self.formulas.items())}


def build_set(defs_by_code: dict[str, tuple[int, str]], columns: dict[str, ColumnMeta] | None = None) -> FormulaSet:
    cols = columns or BUILTIN_COLUMNS
    known = set(cols)
    compiled: dict[str, CompiledFormula] = {}
    for code, (version, expr) in defs_by_code.items():
        node, deps = compile_expression(expr, known)
        compiled[code] = CompiledFormula(code, version, expr, node, deps)
    cyc = detect_cycle({c: {d for d in f.deps.columns if d in compiled} for c, f in compiled.items()})
    if cyc:
        raise FormulaError(f"Vòng phụ thuộc: {' → '.join(cyc)}")
    return FormulaSet(compiled, cols)


def builtin_set() -> FormulaSet:
    base = {code: (defs.BUILTIN_VERSION, spec["expression"]) for code, spec in defs.V1.items()}
    base.update({code: (defs.V2_VERSION, spec["expression"]) for code, spec in defs.V2.items()})  # phiên bản 2 thay phiên bản 1 của cùng cột
    return build_set(base)


def workbook_set() -> FormulaSet:
    """Bộ công thức v1 (khớp workbook: OFF DAYS = TOTAL DAY / 7) — dùng đối chiếu / kiểm thử."""
    return build_set({code: (defs.BUILTIN_VERSION, spec["expression"]) for code, spec in defs.V1.items()})


# Bộ công thức đang hiệu lực toàn tiến trình; service nạp lại từ DB khi khởi động / sau Publish.
_active: FormulaSet | None = None


def active() -> FormulaSet:
    global _active
    if _active is None:
        _active = builtin_set()
    return _active


def set_active(fs: FormulaSet | None) -> None:
    global _active
    _active = fs
