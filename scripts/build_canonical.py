"""Sinh bộ ca chuẩn (canonical cases) cho công thức v1 từ workbook kế hoạch SX THẬT.

Chạy: .venv/Scripts/python.exe scripts/build_canonical.py "<đường dẫn .xlsb>"
Kết quả: app/data/formula_canonical.json (được commit; dùng làm test và làm điều kiện Publish).
Mỗi ca chuẩn = inputs + expected lấy NGUYÊN từ workbook (kèm số dòng nguồn). Ca tổng hợp (SYNTHETIC) chỉ dùng cho biên/rỗng.
Thống kê `verification` = độ khớp của bộ tính mới trên TOÀN BỘ dòng của sheet KẾ HOẠCH.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from pyxlsb import open_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import formula_runtime as fx  # noqa: E402
from app.services.formula import run_case  # noqa: E402

num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)  # noqa: E731
OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "formula_canonical.json"


def load_rows(path: str):
    rows = []
    with open_workbook(path) as wb:
        with wb.get_sheet("KẾ HOẠCH") as sh:
            for i, r in enumerate(sh.rows()):
                if i < 3:
                    continue
                v = [c.v for c in r] + [None] * 45
                if num(v[10]) and v[10] > 0:
                    rows.append((i + 1, v))  # số dòng Excel (1-based)
    return rows


def main(path: str):
    fs = fx.builtin_set()
    rows = load_rows(path)
    stats = defaultdict(lambda: {"tested": 0, "matched": 0})
    cases = defaultdict(list)
    picked = defaultdict(set)

    def pick(code, kind, case):
        if kind not in picked[code]:
            picked[code].add(kind)
            cases[code].append({"kind": kind, **case})

    prev = None
    node = {c: f.node for c, f in fs.formulas.items()}
    for xl, v in rows:
        q, cap, td, off, b, e = v[10], v[12], v[13], v[14], v[22], v[23]
        # ---- TOTAL_DAY
        if num(q) and num(cap) and cap:
            exp = run_case(node["TOTAL_DAY"], {"QUANTITY": q, "CAPACITY": cap})
            stats["TOTAL_DAY"]["tested"] += 1
            ok = num(td) and abs(exp - td) < 1e-6
            stats["TOTAL_DAY"]["matched"] += ok
            if ok:
                pick("TOTAL_DAY", "normal" if 0.3 < td < 3 else "small" if td <= 0.3 else "large",
                     {"inputs": {"QUANTITY": q, "CAPACITY": cap}, "expected": td, "source_row": xl})
                if 0.99 < td < 1.01:
                    pick("TOTAL_DAY", "threshold_1_day", {"inputs": {"QUANTITY": q, "CAPACITY": cap}, "expected": td, "source_row": xl})
        # ---- OFF_DAYS
        if num(td) and num(off):
            exp = run_case(node["OFF_DAYS"], {"TOTAL_DAY": td})
            stats["OFF_DAYS"]["tested"] += 1
            ok = abs(exp - off) < 1e-6
            stats["OFF_DAYS"]["matched"] += ok
            if ok:
                pick("OFF_DAYS", "small" if td < 1 else "large" if td > 7 else "normal", {"inputs": {"TOTAL_DAY": td}, "expected": off, "source_row": xl})
        # ---- END_BEGIN_DATE
        if num(b) and num(td) and num(off) and num(e):
            exp = run_case(node["END_BEGIN_DATE"], {"BEGIN_PROD_DATE": b, "TOTAL_DAY": td, "OFF_DAYS": off})
            stats["END_BEGIN_DATE"]["tested"] += 1
            ok = abs(exp - e) < 1e-4
            stats["END_BEGIN_DATE"]["matched"] += ok
            if ok:
                pick("END_BEGIN_DATE", "normal" if td < 3 else "long", {"inputs": {"BEGIN_PROD_DATE": b, "TOTAL_DAY": td, "OFF_DAYS": off}, "expected": e, "source_row": xl})
        # ---- BEGIN_PROD_DATE (cần dòng trước cùng chuyền)
        key = (v[0], v[1])
        if num(b):
            if prev is None or prev[0] != key or not num(prev[1]["e"]):
                pick("BEGIN_PROD_DATE", "first_in_lane_manual", {"inputs": {}, "manual": b, "prev": None, "expected": b, "source_row": xl})
            else:
                pv = {"END_BEGIN_DATE": prev[1]["e"], "TOTAL_DAY": prev[1]["td"]}
                exp = run_case(node["BEGIN_PROD_DATE"], {}, pv, b)
                ok = abs(exp - b) < 1e-4
                kind = "prev_total_day_ge_1_plus_1_9" if prev[1]["td"] is not None and prev[1]["td"] >= 1 else "prev_total_day_lt_1_same_end"
                stats["BEGIN_PROD_DATE"]["tested"] += 1
                stats["BEGIN_PROD_DATE"]["matched"] += ok
                if ok:
                    pick("BEGIN_PROD_DATE", kind, {"inputs": {}, "manual": b, "prev": pv, "expected": b, "source_row": xl})
        # ---- ON_TIME
        txt = v[32]
        if num(v[29]) and num(v[28]) and txt in ("ON TIME", "DELAY", "ADVANCE"):
            exp = run_case(node["ON_TIME"], {"EHD_ETD": v[29], "CHD": v[28]})
            stats["ON_TIME"]["tested"] += 1
            ok = exp == txt
            stats["ON_TIME"]["matched"] += ok
            if ok:
                pick("ON_TIME", txt, {"inputs": {"EHD_ETD": v[29], "CHD": v[28]}, "expected": txt, "source_row": xl})
        prev = (key, {"e": e if num(e) else None, "td": td if num(td) else None})

    # ---- ca tổng hợp (biên / rỗng) — đánh dấu rõ SYNTHETIC
    synthetic = {
        "TOTAL_DAY": [
            {"kind": "capacity_zero", "inputs": {"QUANTITY": 100, "CAPACITY": 0}, "expected": "", "synthetic": True},
            {"kind": "capacity_blank", "inputs": {"QUANTITY": 100, "CAPACITY": None}, "expected": "", "synthetic": True},
        ],
        "OFF_DAYS": [{"kind": "total_day_blank", "inputs": {"TOTAL_DAY": None}, "expected": "", "synthetic": True}],
        "ON_TIME": [
            {"kind": "diff_4.5_on_time", "inputs": {"EHD_ETD": 104.5, "CHD": 100.0}, "expected": "ON TIME", "synthetic": True},
            {"kind": "diff_5_delay", "inputs": {"EHD_ETD": 105.0, "CHD": 100.0}, "expected": "DELAY", "synthetic": True},
            {"kind": "diff_minus_4_on_time", "inputs": {"EHD_ETD": 96.0, "CHD": 100.0}, "expected": "ON TIME", "synthetic": True},
            {"kind": "diff_minus_4.5_advance", "inputs": {"EHD_ETD": 95.5, "CHD": 100.0}, "expected": "ADVANCE", "synthetic": True},
            {"kind": "missing_input", "inputs": {"EHD_ETD": None, "CHD": 100.0}, "expected": "", "synthetic": True},
        ],
    }
    for code, extra in synthetic.items():
        cases[code].extend(extra)

    verification = {code: {**s, "rate": round(s["matched"] / s["tested"], 4) if s["tested"] else None} for code, s in stats.items() if "tested" in s}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"source_document": Path(path).name, "source_sheet": "KẾ HOẠCH", "rows_scanned": len(rows), "tolerance": 1e-4, "verification": verification, "cases": cases},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(verification, ensure_ascii=False, indent=1))
    print({k: len(v) for k, v in cases.items()})


if __name__ == "__main__":
    main(sys.argv[1])
