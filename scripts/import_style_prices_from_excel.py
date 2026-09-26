"""Điền MẪU bảng giá theo mã hàng từ file Excel báo cáo năng suất (cột "Đơn giá công ty" trong các sheet ngày 04…23).

    .venv\\Scripts\\python.exe scripts\\import_style_prices_from_excel.py "<file.xlsx>"            # chạy thử
    .venv\\Scripts\\python.exe scripts\\import_style_prices_from_excel.py "<file.xlsx>" --apply    # ghi vào Postgres

- Mỗi mã hàng lấy đơn giá xuất hiện ở sheet ngày SAU CÙNG; nếu mã hàng có nhiều mức giá khác nhau giữa các ngày thì báo cáo (không tự chọn mức nào khác).
- Ngày hiệu lực của dòng mẫu = 2026-01-01 (mẫu, để giá áp dụng cho cả tháng 5/2026 trở đi); nguồn EXCEL. Chạy lại không tạo trùng.
- Mã hàng đã có giá trong DB (bất kỳ nguồn) được giữ nguyên.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import openpyxl  # noqa: E402

from app.db.session import SessionLocal, utcnow  # noqa: E402
from app.models.resources import StylePrice  # noqa: E402

SAMPLE_FROM = date(2026, 1, 1)


def norm(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().upper() or None


def read_prices(path: str) -> tuple[dict, dict]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    last, seen = {}, {}
    for ws in wb.worksheets:
        if not ws.title.isdigit():
            continue
        for r in ws.iter_rows(min_row=4, max_row=90, min_col=6, max_col=9, values_only=True):
            style, price = norm(r[0]), r[3]
            if style and isinstance(price, (int, float)) and price > 0 and isinstance(r[1], str) and not r[1].strip().isdigit() and not str(r[0]).startswith(("LĐ", "Tổng")):  # r[1] = Brand (chữ): loại dòng tổng LĐ/doanh thu
                last[style] = round(float(price), 6)
                seen.setdefault(style, set()).add(round(float(price), 6))
    return last, {k: sorted(v) for k, v in seen.items() if len(v) > 1}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    apply = "--apply" in sys.argv
    last, multi = read_prices(args[0])
    with SessionLocal() as db:
        have = {r[0] for r in db.query(StylePrice.style_cc)}
        new = {s: p for s, p in last.items() if s not in have}
        for s, p in new.items():
            db.add(StylePrice(style_cc=s, unit_price=p, currency="USD", effective_from=SAMPLE_FROM, source="EXCEL", note="Mẫu điền sẵn từ báo cáo năng suất tháng 5/2026 (Đơn giá công ty) — cần rà soát",
                              updated_by="import-excel", updated_at=utcnow()))
        print(json.dumps({"styles_in_excel": len(last), "already_have_price": len(last) - len(new), "to_insert": len(new), "styles_with_several_prices_in_month": multi}, ensure_ascii=False, indent=1))
        if apply:
            db.commit()
            print("Đã ghi.")
        else:
            db.rollback()
            print("(chạy thử — chưa ghi gì. Thêm --apply để ghi.)")


if __name__ == "__main__":
    main()
