"""Các hàm thuần (không I/O) cho quy tắc nghiệp vụ dashboard — dễ kiểm thử."""

import calendar
import unicodedata
from datetime import date, datetime, timedelta

EXCEL_EPOCH = date(1899, 12, 30)

# EHD/CHD (số ngày CHD - ngày kết thúc nhập kho). Âm từ 1 ngày trở lên = trễ hạn khách hàng.
LATE_THRESHOLD_DAYS = -1.0

MATERIAL_KEYWORDS = (
    "chua co vai",
    "chua co pl",
    "chua co",
    "chua ve",
    "not yet",
    "not ready",
    "thieu",
    "cho vai",
    "cho pl",
    "check voi",
)


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()


def to_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def excel_serial_to_date(value) -> date | None:
    """Số serial Excel -> date. Trả None với giá trị lỗi/không phải ngày (VD '0xf', text)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    num = to_float(value)
    if num is None or num < 20000 or num > 80000:
        return None
    return EXCEL_EPOCH + timedelta(days=int(num))


def has_material_issue(*texts: str | None) -> bool:
    for t in texts:
        if not t or not isinstance(t, str):
            continue
        norm = strip_accents(t)
        if any(k in norm for k in MATERIAL_KEYWORDS):
            return True
    return False


def classify_row(gap_days: float | None, status_text: str | None, note: str | None, fabric_text: str | None):
    """Trả (risk, reason). risk: LATE | MATERIAL | ADVANCE | OK."""
    status = strip_accents(status_text or "").strip()
    if gap_days is not None and gap_days <= LATE_THRESHOLD_DAYS:
        return "LATE", f"EHD/CHD = {gap_days:.1f} ngày"
    if any(k in status for k in ("delay", "late", "tre")):
        return "LATE", f"Trạng thái: {status_text}"
    if has_material_issue(note, fabric_text):
        return "MATERIAL", (note or fabric_text or "")[:200]
    if status == "advance":
        return "ADVANCE", "Hoàn thành sớm hơn ngày khách yêu cầu"
    return "OK", ""


def safe_pct(actual: float | None, plan: float | None) -> float | None:
    if actual is None or not plan:
        return None
    return actual / plan * 100.0


def elapsed_pct(year: int, month: int, today: date) -> float:
    """% thời gian đã trôi qua của tháng (theo ngày lịch)."""
    days = calendar.monthrange(year, month)[1]
    if (year, month) == (today.year, today.month):
        return today.day / days * 100.0
    return 100.0 if (year, month) < (today.year, today.month) else 0.0


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def parse_month(value: str | None, today: date) -> tuple[int, int]:
    if not value:
        return today.year, today.month
    try:
        y, m = value.split("-")
        y, m = int(y), int(m)
        if 1 <= m <= 12 and 2000 <= y <= 2100:
            return y, m
    except ValueError:
        pass
    return today.year, today.month


def assess_factory(planning_status: str, factory_known: bool, fac_raw: str) -> tuple[str, str, str]:
    """Tách 2 chiều độc lập cho 1 dòng kế hoạch: (factory_assignment, mapping_status, mapping_note).

    - factory_assignment: KNOWN nếu đã xác định được XN, ngược lại UNASSIGNED.
    - mapping_status: chỉ WARNING khi dữ liệu nguồn có vấn đề (FAC/XN lạ, hoặc dòng đã xếp KH mà thiếu XN).
      Một PO chưa lên KH và chưa có XN là trạng thái HỢP LỆ -> mapping OK.
    Planning status (UNPLANNED/PLANNED) do sheet nguồn quyết định, không suy ra từ hai chiều này.
    """
    if factory_known:
        return "KNOWN", "OK", ""
    raw = (fac_raw or "").strip()
    if raw:
        return "UNASSIGNED", "WARNING", f"FAC/XN '{raw}' không thuộc danh mục XN1/XN2/XN3"
    if planning_status == "PLANNED":
        return "UNASSIGNED", "WARNING", "Dòng đã xếp kế hoạch nhưng thiếu XN"
    return "UNASSIGNED", "OK", ""
