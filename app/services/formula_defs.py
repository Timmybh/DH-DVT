"""Danh mục cột Planning + định nghĩa công thức phiên bản 1 (đối chiếu với workbook thật).

Mã cột theo handoff §6; `workbook` là tiêu đề cột trong sheet KẾ HOẠCH của file Excel kế hoạch SX.
`source`: ``row:<trường PlanningVersionRow>`` | ``ref:<khóa trong dữ liệu tham chiếu Excel>`` | ``calc`` (chỉ tính, không lưu).
input_type: MANUAL | LIST | CALCULATED. `list_source` là tên đối tượng nghiệp vụ, không phải tên bảng.
"""

from datetime import date

# (code, label, workbook header, value_type, input_type, list_source, source)
COLUMNS: list[tuple] = [
    ("FACTORY", "Factory", "FAC / XN", "text", "LIST", "Factory", "row:factory_code"),
    ("LINE", "Line", "LINE", "text", "LIST", "Production Line", "row:primary_line"),
    ("PO_DATE", "PO date", "PO DATE", "date", "MANUAL", "", "ref:po_date"),
    ("SPORT", "Sport", "SPORT", "text", "LIST", "Sport", "row:sport"),
    ("SEASON", "Season", "SEASON", "text", "LIST", "Season", "row:season"),
    ("PO_NUMBER", "PO", "PO NUMBER", "text", "MANUAL", "", "row:po_number"),
    ("STYLE_CC", "Style/CC", "STYLE/ CC", "text", "LIST", "Style", "row:style_cc"),
    ("MODEL_CODE", "Model", "MODEL CODE", "text", "LIST", "Model", "row:model_code"),
    ("DESCRIPTION", "Description", "DECRIPTION", "text", "MANUAL", "", "row:description"),
    ("CUSTOMER", "Customer", "CUSTOMER", "text", "LIST", "Customer", "row:customer"),
    ("QUANTITY", "Quantity", "QUANTITY", "number", "MANUAL", "", "row:quantity"),
    ("WORKER", "Worker", "WORKER", "number", "MANUAL", "", "ref:worker"),
    ("CAPACITY", "Capacity", "CAPACITY", "number", "MANUAL", "", "row:capacity"),
    ("TOTAL_DAY", "Total day", "TOTAL DAY", "number", "CALCULATED", "", "row:total_day"),
    ("OFF_DAYS", "Off days", "OFF DAYS", "number", "CALCULATED", "", "calc"),
    ("FABRIC_READY", "Fabric ready", "FACBRIC READY", "date", "MANUAL", "", "ref:fabric_ready"),
    ("ACC_READY", "Acc ready", "ACC READY", "date", "MANUAL", "", "ref:acc_ready"),
    ("NO_ISSUE", "No issue", "NO ISSUE", "text", "MANUAL", "", "ref:no_issue"),
    ("DATE_ISSUE", "Date issue", "NO ISSUE (ngày)", "date", "MANUAL", "", "ref:date_issue"),
    ("WORKING_DAY", "Working day", "WORKING DAY", "number", "MANUAL", "", "ref:working_day"),
    ("SOT", "SOT", "SOT", "number", "MANUAL", "", "ref:sot"),
    ("TOTAL_SOT", "Total SOT", "TOTAL SOT", "number", "MANUAL", "", "ref:total_sot"),
    ("BEGIN_PROD_DATE", "Begin prod date", "BEGINING P. DATE", "date", "CALCULATED", "", "row:begin_prod_date"),
    ("END_BEGIN_DATE", "End begin date", "END BE. DATE", "date", "CALCULATED", "", "row:end_prod_date"),
    ("OUTPUT_DATE", "Output date", "OUT PUT DATE", "date", "MANUAL", "", "ref:output_date"),
    ("END_PROD_DATE", "End prod date", "END P DATE", "date", "MANUAL", "", "ref:end_p_date"),
    ("BEGIN_WAREHOUSE_IMPORT", "Begin warehouse import", "W.HOUSE", "date", "MANUAL", "", "row:warehouse_date"),
    ("END_WAREHOUSE_IMPORT", "End warehouse import", "END W. HOUS", "date", "MANUAL", "", "ref:end_wh"),
    ("CHD", "CHD", "CHD", "date", "MANUAL", "", "row:chd"),
    ("EHD_ETD", "EHD/ETD", "EHD/ ETD", "date", "MANUAL", "", "ref:ehd_etd"),
    ("AHD", "AHD", "AHD", "date", "MANUAL", "", "ref:ahd"),
    ("ON_TIME", "On time", "EHD/ CHD (trạng thái)", "text", "CALCULATED", "", "calc"),
]

DATE_ROW_FIELDS = ("begin_prod_date", "end_prod_date", "warehouse_date", "chd")

# Công thức v1: mã cột -> (biểu thức, mô tả, công thức gốc trong workbook (suy ra từ dữ liệu), làm tròn, lịch)
V1 = {
    "TOTAL_DAY": dict(
        expression="IFERROR(QUANTITY / CAPACITY, \"\")",
        description="Số ngày sản xuất thô = số lượng / năng suất ngày. Giữ nguyên số lẻ, không làm tròn.",
        workbook_formula="TOTAL DAY = QUANTITY / CAPACITY",
        rounding="NONE (giữ giá trị thô)", calendar="KHÔNG dùng lịch",
        result_type="number", source_columns="QUANTITY (cột 10), CAPACITY (cột 12) → TOTAL DAY (cột 13)",
    ),
    "OFF_DAYS": dict(
        expression="IFERROR(TOTAL_DAY / 7, \"\")",
        description="Ngày nghỉ tuần theo workbook = TOTAL_DAY / 7 (số lẻ). Khác với ngày OFF của Lịch làm việc.",
        workbook_formula="OFF DAYS = TOTAL DAY / 7",
        rounding="NONE (giữ giá trị thô)", calendar="KHÔNG dùng lịch",
        result_type="number", source_columns="TOTAL DAY (cột 13) → OFF DAYS (cột 14)",
    ),
    "BEGIN_PROD_DATE": dict(
        expression="IF(ISBLANK(PREVIOUS_SEQUENCE.END_BEGIN_DATE), MANUAL(), "
                   "PREVIOUS_SEQUENCE.END_BEGIN_DATE + IF(PREVIOUS_SEQUENCE.TOTAL_DAY >= 1, 1/9, 0))",
        description="Ngày vào chuyền = END BE. DATE của dòng đứng trước trong chuyền, cộng thêm 1/9 ngày nếu dòng trước có "
                    "TOTAL_DAY ≥ 1. Dòng đầu chuyền là mốc nhập tay.",
        workbook_formula="BEGINING P. DATE = END BE. DATE (dòng trước cùng chuyền) + IF(TOTAL DAY dòng trước ≥ 1, 1/9, 0); dòng đầu chuyền nhập tay",
        rounding="NONE (giữ số lẻ ngày)", calendar="KHÔNG dùng lịch làm việc (đúng như workbook)",
        result_type="date", source_columns="END BE. DATE, TOTAL DAY của dòng trước (cột 23, 13) → BEGINING P. DATE (cột 22)",
    ),
    "END_BEGIN_DATE": dict(
        expression="BEGIN_PROD_DATE + TOTAL_DAY + OFF_DAYS",
        description="Ngày may xong (END BE. DATE) = ngày vào chuyền + TOTAL_DAY + OFF_DAYS, cộng thẳng số lẻ như workbook.",
        workbook_formula="END BE. DATE = BEGINING P. DATE + TOTAL DAY + OFF DAYS",
        rounding="NONE (giữ số lẻ ngày)", calendar="KHÔNG dùng lịch làm việc (đúng như workbook)",
        result_type="date", source_columns="BEGINING P. DATE, TOTAL DAY, OFF DAYS (cột 22, 13, 14) → END BE. DATE (cột 23)",
    ),
    "ON_TIME": dict(
        expression="IFERROR(IF(EHD_ETD - CHD > 4.9, \"DELAY\", IF(EHD_ETD - CHD < -4, \"ADVANCE\", \"ON TIME\")), \"\")",
        description="Trạng thái giao hàng: chênh lệch EHD/ETD − CHD > 4,9 ngày = DELAY; < −4 ngày = ADVANCE; còn lại ON TIME; thiếu dữ liệu = trống.",
        workbook_formula='IFERROR(IF((EHD/ETD - CHD) > 4.9, "DELAY", IF((EHD/ETD - CHD) < -4, "ADVANCE", "ON TIME")), "")',
        rounding="NONE", calendar="KHÔNG dùng lịch",
        result_type="text", source_columns="EHD/ ETD, CHD (cột 29, 28) → trạng thái (cột 32)",
    ),
}

# Bản nháp: chưa có công thức được xác minh 100% với workbook nên KHÔNG được publish (bằng chứng: xem ca chuẩn)
DRAFTS = {
    "END_PROD_DATE": dict(
        expression="END_BEGIN_DATE + 1",
        description="END P DATE ≈ END BE. DATE + 1 ngày (khớp 96% dòng); 4% dòng cộng thêm 2–14 ngày chưa rõ quy tắc.",
        workbook_formula="(chưa xác định) — dữ liệu cho thấy END P DATE = END BE. DATE + 1, một số dòng + 3",
        rounding="NONE", calendar="Chưa xác định",
        result_type="date", source_columns="END BE. DATE (cột 23) → END P DATE (cột 25)",
    ),
}

BUILTIN_VERSION = 1


def serial_to_iso(serial: float | None) -> str | None:
    if serial is None:
        return None
    from app.services.formula import from_serial

    d: date | None = from_serial(serial)
    return d.isoformat() if d else None
