"""Nạp SAM, SOT và Brand theo mã hàng từ file Excel báo cáo năng suất vào bảng style_sam (Thông tin sản phẩm).

    .venv\\Scripts\\python.exe scripts\\import_sam_sot_from_excel.py "<file.xlsx>"            # chạy thử, chỉ in báo cáo
    .venv\\Scripts\\python.exe scripts\\import_sam_sot_from_excel.py "<file.xlsx>" --apply    # ghi vào Postgres

Quy tắc (không ghi đè số liệu có thẩm quyền):
- SOT  : sheet "SOT" cột C (STT, CC, SOT). Cột D không có tiêu đề → không dùng, chỉ báo cáo.
- SAM TT: sheet "SAM" (STT, CC, SAM) → cột SAM TT (SAM bình quân thực tế). SAM KT là SAM ERP (LCD_Truc_QUan_ChuyenMay_MaHang_Sam) — không bị ghi đè.
- Brand: cột "Brand hàng" trong các sheet ngày (04…23); lần xuất hiện sau cùng thắng, chuẩn hoá theo tên trong sheet "brand+ khách hàng". Chỉ điền cho mã hàng đã có trong style_sam hoặc trong sheet SAM/SOT; brand đã nhập tay được giữ.
- Mã hàng mới: tạo dòng nguồn EXCEL. Ghi ảnh chụp giá trị cũ ra file JSON (scripts/output) để hoàn tác.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import openpyxl  # noqa: E402

from app.db.session import SessionLocal, utcnow  # noqa: E402
from app.models.resources import BrandCustomer, StyleSam  # noqa: E402

REPLACEABLE = ("ESTIMATE", "DEFAULT", "EXCEL")


def norm(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s.upper() or None


def read_excel(path: str) -> dict:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sam, sot, sot_d = {}, {}, {}
    for r in wb["SAM"].iter_rows(min_row=2, values_only=True):
        if r[1] is not None and isinstance(r[2], (int, float)) and r[2] > 0:
            sam[norm(r[1])] = round(float(r[2]), 3)
    for r in wb["SOT"].iter_rows(min_row=2, values_only=True):
        if r[1] is not None and isinstance(r[2], (int, float)) and r[2] > 0:
            sot[norm(r[1])] = round(float(r[2]), 3)
            if len(r) > 3 and isinstance(r[3], (int, float)):
                sot_d[norm(r[1])] = round(float(r[3]), 3)
    canon, cust = {}, {}
    for r in wb["brand+ khách hàng"].iter_rows(min_row=2, values_only=True):
        if r[1]:
            canon[str(r[1]).strip().upper()] = str(r[1]).strip()
            if r[2]:
                cust[str(r[1]).strip()] = str(r[2]).strip()
    brand = {}
    for ws in wb.worksheets:
        if not ws.title.isdigit():
            continue
        for r in ws.iter_rows(min_row=4, max_row=90, min_col=6, max_col=7, values_only=True):
            style, br = norm(r[0]), norm(r[1])
            if style and br and br in canon:
                brand[style] = canon[br]
    return {"sam": sam, "sot": sot, "sot_d": sot_d, "brand": brand, "cust": cust}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if not args:
        sys.exit(__doc__)
    ex = read_excel(args[0])
    universe = set(ex["sam"]) | set(ex["sot"])
    report = {"sam": {"inserted": 0, "updated": 0}, "sot": {"inserted": 0, "updated": 0, "unchanged": 0},
              "brand": {"set": 0, "kept_manual": 0, "skipped_no_style": 0}, "sot_col_d_ignored": ex["sot_d"], "before": {}}
    with SessionLocal() as db:
        rows = {r.style_cc.upper(): r for r in db.query(StyleSam)}
        universe |= set(rows)

        def get(style: str) -> StyleSam:
            r = rows.get(style)
            if r is None:
                r = StyleSam(style_cc=style, sam_minutes=None, source="EXCEL", samples=0, note="Tạo từ file Excel báo cáo năng suất", updated_by="import-excel")
                db.add(r)
                rows[style] = r
                report["before"].setdefault(style, None)
            else:
                report["before"].setdefault(style, {"sam": r.sam_minutes, "source": r.source, "sot": r.sot_minutes, "brand": r.brand})
            return r

        # SAM sheet Excel → SAM TT (SAM bình quân thực tế). SAM KT (ERP) không bị đụng.
        for style, v in ex["sam"].items():
            r = rows.get(style)
            if r is not None and r.sam_tt == v:
                continue
            new = r is None
            r = get(style)
            r.sam_tt = v
            report["sam"]["inserted" if new else "updated"] += 1
        # SAM KT = SAM ERP đã có (source=ERP)
        for r in rows.values():
            if r.source == "ERP" and r.sam_kt is None and r.sam_minutes is not None:
                r = get(r.style_cc)
                r.sam_kt = r.sam_minutes
                report["sam"]["kt_filled"] = report["sam"].get("kt_filled", 0) + 1
        for style, v in ex["sot"].items():
            r = rows.get(style)
            if r is not None and r.sot_minutes == v:
                report["sot"]["unchanged"] += 1
                continue
            new = r is None
            r = get(style)
            r.sot_minutes = v
            report["sot"]["inserted" if new else "updated"] += 1
        for style, br in ex["brand"].items():
            if style not in universe:
                report["brand"]["skipped_no_style"] += 1
                continue
            r = rows.get(style)
            if r is not None and r.brand and r.brand != br and r.updated_by not in ("", "import-excel"):
                report["brand"]["kept_manual"] += 1
                continue
            if r is None or r.brand != br:
                r = get(style)
                r.brand = br
                report["brand"]["set"] += 1
        have_bc = {b.brand: b for b in db.query(BrandCustomer)}
        report["brand_customer"] = {"set": 0}
        for b, c in ex["cust"].items():
            cur = have_bc.get(b)
            if cur is None:
                db.add(BrandCustomer(brand=b, customer=c))
                report["brand_customer"]["set"] += 1
            elif cur.customer != c:
                cur.customer = c
                report["brand_customer"]["set"] += 1
        for r in rows.values():
            if r in db.new or r in db.dirty:
                r.updated_by, r.updated_at = "import-excel", utcnow()
        summary = {k: (v if not isinstance(v, (dict, list)) or k in ("sam", "sot", "brand", "brand_customer") else len(v)) for k, v in report.items() if k != "before"}
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        if not apply:
            db.rollback()
            print("\n(chạy thử — chưa ghi gì. Thêm --apply để ghi.)")
            return
        out = Path(__file__).resolve().parent / "output"
        out.mkdir(exist_ok=True)
        snap = out / f"style_sam_before_{datetime.now():%Y%m%d_%H%M%S}.json"
        snap.write_text(json.dumps(report["before"], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        db.commit()
        print(f"\nĐã ghi. Ảnh chụp giá trị cũ (để hoàn tác): {snap}")


if __name__ == "__main__":
    main()
