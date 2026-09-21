"""Engine Planning thuần (không I/O): áp thao tác lên Draft, Recheck All Plan, so sánh phiên bản.

Hàng kế hoạch là dict với các khóa của PlanningVersionRow. Ngày là `datetime.date`.
Nguyên tắc (handoff): không tự sửa kế hoạch một cách âm thầm — khi kết quả tự tính khác giá trị đang có thì GIỮ giá trị
và báo cảnh báo (dấu "!" cam ở UI); người dùng chủ động "Return to Auto Calculate".
"""

import hashlib
import json
import math
import re
import time
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from typing import Iterable

from app.services import formula_runtime as fx
from app.services.calendar import CalendarResolver
from app.services.lanes import build_lanes, lane_of, previous_map, previous_sequence, refresh_virtual, row_lines
from app.services.rules import strip_accents

DATE_FIELDS = ("begin_prod_date", "end_prod_date", "warehouse_date", "chd")
CALCULATED_FIELDS = ("total_day", "begin_prod_date", "end_prod_date", "warehouse_date")
EDITABLE_FIELDS = {"quantity", "capacity", "total_day", "begin_prod_date", "end_prod_date", "warehouse_date", "chd", "note", "transfer_effective_date"}


# --------------------------------------------------------------------------- ký hiệu chuyền
def parse_line_notation(raw: str | None) -> tuple[list[str], dict | None, str]:
    """"4 + 5 + 9" (dồn chuyền) và "1 ==> 2" (chuyển chuyền) -> cấu trúc thật + chuỗi hiển thị.

    Trả về (line_assignments, transfer, display). Chuỗi chỉ để trình bày, logic dùng cấu trúc (handoff §17–18).
    """
    text = (raw or "").strip()
    if not text:
        return [], None, ""
    transfer = None
    if "==>" in text:
        left, right = (p.strip() for p in text.split("==>", 1))
        assignments = re.findall(r"[^+\s]+", left)
        dest = re.findall(r"[^+\s]+", right)
        transfer = {
            "from": " + ".join(assignments),
            "to": " + ".join(dest),
            "effective_date": None,
            "planned_remaining_qty": None,
            "status": "PLANNED",
        }
        display = f"{' + '.join(assignments)} ==> {' + '.join(dest)}"
        return assignments, transfer, display
    assignments = re.findall(r"[^+\s]+", text)
    return assignments, None, " + ".join(assignments)


def source_key(po: str, style: str, model: str, customer: str, quantity: float) -> str:
    """Khóa nghiệp vụ ổn định (không dùng ID nội bộ) — handoff §25."""
    return "|".join([po.strip(), style.strip(), model.strip(), customer.strip(), f"{quantity:.0f}"])


def new_uid(prefix: str = "R") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def ops_hash(ops: list[dict]) -> str:
    return hashlib.sha256(json.dumps(ops, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _to_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def lane_key(row: dict) -> tuple[str, str]:
    return row.get("factory_code", ""), row.get("primary_line", "")


def sort_rows(rows: Iterable[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["factory_code"], r["primary_line"], r["sequence"]))


def reindex(rows: list[dict]) -> list[dict]:
    """Xây lại `sequence` 1..n trong từng lane SỞ HỮU (XN, primary_line) rồi dựng virtual lane / virtual_sequence cho mọi chuyền của dòng."""
    lanes: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        lanes.setdefault(lane_key(r), []).append(r)
    out: list[dict] = []
    for key in sorted(lanes):
        for i, r in enumerate(sorted(lanes[key], key=lambda x: x["sequence"]), start=1):
            r["sequence"] = i
            out.append(r)
    refresh_virtual(out)  # VirtualSequence theo TOÀN BỘ line_assignments: dòng 4+5 nằm trong cả lane 4 và lane 5
    return out


# --------------------------------------------------------------------------- tự tính (theo Formula Definition đang Publish)
CALC_CODE = {"total_day": "TOTAL_DAY", "begin_prod_date": "BEGIN_PROD_DATE", "end_prod_date": "END_BEGIN_DATE", "warehouse_date": "BEGIN_WAREHOUSE_IMPORT"}


def calc_total_day(quantity, capacity) -> float | None:
    """TOTAL_DAY theo công thức hiệu lực (giá trị thô, không làm tròn)."""
    row = {"quantity": quantity, "capacity": capacity}
    try:
        v = fx.active().calculated(row, None, "TOTAL_DAY")
    except Exception:  # noqa: BLE001 - FormulaError: thiếu dữ liệu
        return None
    return None if v == "" else v


def recalc_row(row: dict, prev: dict | None) -> None:
    """Tính lại TOTAL_DAY → BEGIN_PROD_DATE → END_BEGIN_DATE của một dòng (bỏ qua cột đang override)."""
    fs = fx.active()
    for code in ("TOTAL_DAY", "BEGIN_PROD_DATE", "END_BEGIN_DATE", "BEGIN_WAREHOUSE_IMPORT"):
        if fs.has(code):
            fs.apply(row, prev, code)


def _prev_in_lane(rows: list[dict], row: dict) -> dict | None:
    return previous_sequence(rows, row)  # theo lane ảo (mọi chuyền của dòng), không theo primary_line


# --------------------------------------------------------------------------- áp thao tác lên Draft
class OpError(ValueError):
    pass


def _insert_after(rows: list[dict], row: dict, after_uid: str | None) -> None:
    lane = sorted((r for r in rows if lane_key(r) == lane_key(row) and r is not row), key=lambda r: r["sequence"])
    if after_uid is None:
        position = 0
    else:
        idx = next((i for i, r in enumerate(lane) if r["row_uid"] == after_uid), None)
        if idx is None:
            raise OpError(f"Không tìm thấy dòng đích '{after_uid}' trong chuyền {row['factory_code']}/{row['primary_line']}")
        position = idx + 1
    # Đặt sequence bằng số thực tạm rồi reindex để không phụ thuộc số lượng dòng
    before = lane[position - 1]["sequence"] if position > 0 else 0
    after = lane[position]["sequence"] if position < len(lane) else before + 2
    row["sequence"] = (before + after) / 2
    rows.append(row)


def apply_ops(
    base_rows: list[dict],
    unplanned: dict[int, dict],
    ops: list[dict],
    cal: CalendarResolver,
    factory_codes: set[str],
    returned: list[dict] | None = None,
    cap_resolver=None,
    factory_lines: dict[str, set[str]] | None = None,
) -> tuple[list[dict], set[str]]:
    """Áp danh sách thao tác lên bản sao của base_rows. Trả (rows đã reindex, tập row_uid bị thay đổi).

    `returned` (tùy chọn) là danh sách dòng đã trả về Unplanned; được cập nhật tại chỗ bởi UNPLAN / ADD_RETURNED.
    """
    fx.set_calendar(cal)  # công thức OFF_DAYS tính theo Lịch làm việc
    if returned is None:
        returned = []
    rows = [dict(r, extra=json.loads(json.dumps(r.get("extra") or {}))) for r in base_rows]
    by_uid = {r["row_uid"]: r for r in rows}
    changed: set[str] = set()

    for n, op in enumerate(ops, start=1):
        kind = op.get("type")
        try:
            if kind == "ADD_FROM_UNPLANNED":
                src = unplanned.get(int(op["sourceId"]))
                if src is None:
                    raise OpError("Nguồn Unplanned không tồn tại hoặc đã được đưa vào kế hoạch")
                factory = op.get("factory") or src.get("factory_code") or ""
                if factory not in factory_codes:
                    raise OpError("Cần chọn Xí nghiệp hợp lệ trước khi xác nhận (PO chưa xác định XN)")
                line = str(op.get("line") or "").strip()
                if not line:
                    raise OpError("Cần chọn Chuyền đích")
                uid = "D" + re.sub(r"\W", "", str(op["tempRowId"]))[:30]
                if uid in by_uid:
                    raise OpError("tempRowId bị trùng")
                capacity = op.get("capacity") or src.get("capacity")
                cap_source = None
                if not capacity and cap_resolver is not None:  # thiếu năng suất -> lấy từ Capacity Definition (mức cụ thể nhất)
                    d = cap_resolver({"factory_code": factory, "primary_line": line, "style_cc": src["style_cc"], "model_code": src["model_code"]})
                    if d:
                        capacity, cap_source = d["capacity_per_day"], {"definition_id": d["id"], "version": d["version"], "source": d["source"]}
                row = {
                    "row_uid": uid,
                    "sequence": 0,
                    "origin": "DRAFT_NEW",
                    "source_key": src["source_key"],
                    "source_plan_row_id": src["id"],
                    "factory_code": factory,
                    "primary_line": line,
                    "line_raw": line,
                    "line_assignments": [line],
                    "transfer": None,
                    "po_number": src["po_number"], "style_cc": src["style_cc"], "model_code": src["model_code"],
                    "description": src["description"], "customer": src["customer"], "sport": src["sport"], "season": src["season"],
                    "so_id": src.get("so_id"),  # SO đi theo dòng từ Unplanned (Split không đổi SO)
                    "quantity": src["quantity"], "capacity": capacity, "total_day": None,
                    "begin_prod_date": None, "end_prod_date": None, "warehouse_date": None, "chd": src.get("chd"),
                    "note": src.get("note", ""), "extra": {"ref": src.get("ref") or {}, **({"capacity_source": cap_source} if cap_source else {})},
                }
                _insert_after(rows, row, op.get("afterRowUid"))
                recalc_row(row, _prev_in_lane_by_position(rows, row))
                by_uid[uid] = row
                changed.add(uid)

            elif kind == "MOVE":
                row = by_uid.get(op["rowUid"])
                if row is None:
                    raise OpError("Không tìm thấy dòng cần di chuyển")
                factory, line = op.get("factory") or row["factory_code"], str(op.get("line") or row["primary_line"])
                if factory not in factory_codes:
                    raise OpError("Xí nghiệp đích không hợp lệ")
                if op.get("afterRowUid") == row["row_uid"]:
                    raise OpError("Không thể đặt dòng sau chính nó")
                rows.remove(row)
                if (factory, line) != lane_key(row):
                    row["factory_code"], row["primary_line"], row["line_raw"], row["line_assignments"] = factory, line, line, [line]
                _insert_after(rows, row, op.get("afterRowUid"))
                changed.add(row["row_uid"])

            elif kind == "UNPLAN":
                row = by_uid.pop(op["rowUid"], None)
                if row is None:
                    raise OpError("Không tìm thấy dòng cần trả về Unplanned")
                rows.remove(row)
                returned.append(row)

            elif kind == "ADD_RETURNED":
                snap = next((r for r in returned if r["row_uid"] == op.get("rowUid")), None)
                if snap is None:
                    raise OpError("Dòng không nằm trong danh sách đã trả về Unplanned")
                factory = op.get("factory") or snap["factory_code"]
                line = str(op.get("line") or "").strip()
                if factory not in factory_codes:
                    raise OpError("Cần chọn Xí nghiệp hợp lệ")
                if not line:
                    raise OpError("Cần chọn Chuyền đích")
                returned.remove(snap)
                row = _thaw(snap)
                row["factory_code"], row["primary_line"], row["line_raw"], row["line_assignments"], row["transfer"] = factory, line, line, [line], None
                _insert_after(rows, row, op.get("afterRowUid"))
                recalc_row(row, _prev_in_lane_by_position(rows, row))
                by_uid[row["row_uid"]] = row
                changed.add(row["row_uid"])

            elif kind == "SET_LINES":
                # Dồn chuyền "4 + 5 + 9": chạy ĐỒNG THỜI trên nhiều chuyền; chuyền đầu là chuyền chính (xác định hàng chờ/thứ tự)
                row = by_uid.get(op["rowUid"])
                if row is None:
                    raise OpError("Không tìm thấy dòng")
                requested = _clean_lines(op.get("lines")) if not op.get("all") else [row["primary_line"]]
                lines = _resolve_lines(op, rows, row["factory_code"], requested[0], requested, factory_lines)
                old_lane = lane_key(row)
                row["line_assignments"], row["line_raw"], row["transfer"] = lines, format_lines(lines), None  # dồn chuyền thay thế chuyển chuyền cũ
                if (row["factory_code"], lines[0]) != old_lane:
                    rows.remove(row)
                    row["primary_line"] = lines[0]
                    lane = sorted((r for r in rows if lane_key(r) == lane_key(row)), key=lambda r: r["sequence"])
                    _insert_after(rows, row, lane[-1]["row_uid"] if lane else None)  # xếp cuối chuyền chính mới
                # Năng suất tổng = Σ năng suất từng chuyền (nếu có định nghĩa cho MỌI chuyền), hoặc giá trị nhập trong thao tác
                if op.get("capacity"):
                    row["capacity"] = float(op["capacity"])
                elif cap_resolver is not None and len(lines) > 1:
                    defs = [cap_resolver({"factory_code": row["factory_code"], "primary_line": ln, "style_cc": row.get("style_cc", ""), "model_code": row.get("model_code", "")}) for ln in lines]
                    if all(defs):
                        row["capacity"] = float(sum(d["capacity_per_day"] for d in defs))
                        row["extra"]["capacity_source"] = {"definition_id": None, "version": None, "source": f"SUM({len(lines)} chuyền)"}
                recalc_row(row, _prev_in_lane_by_position(rows, row))
                changed.add(row["row_uid"])

            elif kind == "MERGE_LINES":
                # Dồn chuyền từ nhiều dòng đã chọn -> MỘT dòng chạy đồng thời trên các chuyền đó (SL, năng suất, nhân công được cộng)
                uids = list(dict.fromkeys(op.get("rowUids") or []))
                if len(uids) < 2:
                    raise OpError("Cần chọn ít nhất 2 dòng để dồn chuyền")
                group = []
                for u in uids:
                    r = by_uid.get(u)
                    if r is None:
                        raise OpError(f"Không tìm thấy dòng {u}")
                    group.append(r)
                keep = by_uid.get(op.get("primaryUid") or uids[0])
                if keep is None or all(keep is not r for r in group):
                    raise OpError("Dòng giữ lại phải nằm trong các dòng được chọn")
                if not all(r["po_number"] for r in group):
                    raise OpError("Có dòng chưa có số PO — không thể dồn")
                if len({(r["factory_code"], r["po_number"]) for r in group}) > 1:
                    raise OpError("Chỉ dồn được các dòng của cùng 1 PO (cùng xí nghiệp)")
                if any(r.get("transfer") for r in group):
                    raise OpError("Có dòng đang chuyển chuyền — gỡ chuyển chuyền trước khi dồn")
                lines: list[str] = []
                for r in [keep, *[x for x in group if x is not keep]]:
                    for ln in r["line_assignments"]:
                        if ln not in lines:
                            lines.append(ln)
                lines = _resolve_lines({"all": op.get("all")} if op.get("all") else {}, rows, keep["factory_code"], keep["primary_line"], lines, factory_lines)
                others = [r for r in group if r is not keep]
                merged_from = [{"row_uid": r["row_uid"], "line": r["line_raw"], "quantity": r["quantity"], "capacity": r.get("capacity"), "source_key": r.get("source_key", "")} for r in others]
                pre_qty = {r["row_uid"]: float(r["quantity"] or 0) for r in group}
                keep["quantity"] = float(sum(r["quantity"] or 0 for r in group))
                if all(r.get("capacity") for r in group):
                    keep["capacity"] = float(sum(r["capacity"] for r in group))
                workers = [((r.get("extra") or {}).get("ref") or {}).get("worker") for r in group]
                if any(workers):
                    keep["extra"].setdefault("ref", {})["worker"] = float(sum(w or 0 for w in workers))
                keep["line_assignments"], keep["line_raw"], keep["transfer"] = lines, format_lines(lines), None
                keep["extra"]["merged_from"] = [*(keep["extra"].get("merged_from") or []), *merged_from]
                # dồn các dòng thuộc nhiều SO: giữ lineage theo từng SO (không ép mất SO nào)
                prior = keep["extra"].get("so_allocations")
                allocs = {a["so_id"]: a for a in (prior or [])}
                for r0 in ([] if prior else [keep]) + others:
                    if r0.get("so_id"):
                        a = allocs.setdefault(r0["so_id"], {"so_id": r0["so_id"], "quantity": 0.0})
                        a["quantity"] += pre_qty[r0["row_uid"]]
                keep["extra"]["so_allocations"] = list(allocs.values())
                drop = {r["row_uid"] for r in others}
                for u in drop:
                    by_uid.pop(u, None)
                rows[:] = [r for r in rows if r["row_uid"] not in drop]
                recalc_row(keep, _prev_in_lane_by_position(rows, keep))
                changed.add(keep["row_uid"])

            elif kind == "SPLIT_LINES":
                # Tách chuyền: các chuyền được chọn rời dòng dồn chuyền, thành MỘT DÒNG MỚI (cùng PO) bắt đầu từ ngày tách
                row = by_uid.get(op["rowUid"])
                if row is None:
                    raise OpError("Không tìm thấy dòng")
                if row.get("transfer"):
                    raise OpError("Dòng đang chuyển chuyền — gỡ chuyển chuyền trước khi tách")
                cur = list(row["line_assignments"])
                if op.get("newLines") or op.get("newAll"):
                    # Tách SANG chuyền khác (dùng được cho dòng chỉ chạy 1 chuyền): dòng gốc giữ chuyền cũ, dòng mới chạy trên các chuyền được chọn
                    eff = _to_date(op.get("effectiveDate"))
                    if eff is None:
                        raise OpError("Cần chọn ngày tách")
                    qty_total, q = float(row["quantity"] or 0), float(op.get("quantity") or 0)
                    if not 0 < q < qty_total:
                        raise OpError("Số lượng tách phải lớn hơn 0 và nhỏ hơn số lượng của dòng")
                    req = _clean_lines(op.get("newLines")) if op.get("newLines") else [row["primary_line"]]
                    new_lines = _resolve_lines({"all": op.get("newAll")}, rows, row["factory_code"], req[0], req, factory_lines)
                    if op.get("newAll"):
                        new_lines = [l for l in new_lines if l not in cur]
                    if not new_lines or any(l in cur for l in new_lines):
                        raise OpError("Chuyền đích phải khác các chuyền đang chạy của dòng")
                    defs = [cap_resolver({"factory_code": row["factory_code"], "primary_line": ln, "style_cc": row.get("style_cc", ""), "model_code": row.get("model_code", "")}) for ln in new_lines] if cap_resolver else []
                    cap = row.get("capacity")
                    per_line = (cap / len(cur)) if cap else None
                    cap_new = float(sum(d["capacity_per_day"] for d in defs)) if defs and all(defs) else (per_line * len(new_lines) if per_line else None)
                    worker = ((row.get("extra") or {}).get("ref") or {}).get("worker")
                    uid = "D" + re.sub(r"\W", "", str(op["tempRowId"]))[:30]
                    if uid in by_uid:
                        raise OpError("tempRowId bị trùng")
                    new = {**{k: v for k, v in row.items() if k != "extra"}, "row_uid": uid, "sequence": 0, "origin": "DRAFT_NEW", "transfer": None,
                           "line_assignments": new_lines, "line_raw": format_lines(new_lines), "primary_line": new_lines[0], "quantity": q, "capacity": cap_new,
                           "begin_prod_date": eff, "end_prod_date": None, "warehouse_date": None, "total_day": None,
                           "extra": {"ref": {**((row.get("extra") or {}).get("ref") or {}), **({"worker": round(worker / len(cur) * len(new_lines), 1)} if worker else {})},
                                     "split_from": row["row_uid"], "serial": {}, "overrides": {"begin_prod_date": {"source": "OVERRIDE", "calculated": None}}}}
                    row["quantity"] = qty_total - q
                    recalc_row(row, _prev_in_lane_by_position(rows, row))
                    lane_new = sorted((r for r in rows if lane_key(r) == lane_key(new)), key=lambda r: r["sequence"])
                    _insert_after(rows, new, lane_new[-1]["row_uid"] if lane_new else None)
                    by_uid[uid] = new
                    recalc_row(new, _prev_in_lane_by_position(rows, new))
                    changed.update({row["row_uid"], uid})
                    continue
                take = _clean_lines(op.get("lines"))
                if any(l not in cur for l in take):
                    raise OpError("Chỉ tách được các chuyền đang có trong dòng")
                if len(take) >= len(cur):
                    raise OpError("Phải để lại ít nhất 1 chuyền cho dòng gốc")
                stay = [l for l in cur if l not in take]
                eff = _to_date(op.get("effectiveDate"))
                if eff is None:
                    raise OpError("Cần chọn ngày tách")
                qty_total = float(row["quantity"] or 0)
                q = float(op.get("quantity") or 0)
                if not 0 < q < qty_total:
                    raise OpError("Số lượng tách phải lớn hơn 0 và nhỏ hơn số lượng của dòng")
                # tỷ trọng năng suất/nhân công của phần tách: theo định nghĩa từng chuyền (nếu đủ), không thì chia đều theo số chuyền
                per = None
                if cap_resolver is not None:
                    defs = {ln: cap_resolver({"factory_code": row["factory_code"], "primary_line": ln, "style_cc": row.get("style_cc", ""), "model_code": row.get("model_code", "")}) for ln in cur}
                    if all(defs.values()):
                        per = {ln: float(d["capacity_per_day"]) for ln, d in defs.items()}
                share = (sum(per[l] for l in take) / sum(per.values())) if per else len(take) / len(cur)
                cap = row.get("capacity")
                cap_new = (sum(per[l] for l in take) if per else cap * share) if cap else None
                cap_old = (cap - cap_new) if (cap and cap_new is not None) else cap
                worker = ((row.get("extra") or {}).get("ref") or {}).get("worker")
                uid = "D" + re.sub(r"\W", "", str(op["tempRowId"]))[:30]
                if uid in by_uid:
                    raise OpError("tempRowId bị trùng")
                new = {**{k: v for k, v in row.items() if k != "extra"}, "row_uid": uid, "sequence": 0, "origin": "DRAFT_NEW", "transfer": None,
                       "line_assignments": take, "line_raw": format_lines(take), "primary_line": take[0], "quantity": q, "capacity": cap_new,
                       "begin_prod_date": eff, "end_prod_date": None, "warehouse_date": None,
                       "extra": {"ref": {**((row.get("extra") or {}).get("ref") or {}), **({"worker": round(worker * share, 1)} if worker else {})}, "split_from": row["row_uid"],
                                 "overrides": {"begin_prod_date": {"source": "OVERRIDE", "calculated": None}}}}
                new["total_day"] = None
                new["extra"]["serial"] = {}
                # phần còn lại của dòng gốc
                old_lane = lane_key(row)
                row["line_assignments"], row["line_raw"] = stay, format_lines(stay)
                row["quantity"], row["capacity"] = qty_total - q, cap_old
                if worker:
                    row["extra"].setdefault("ref", {})["worker"] = round(worker * (1 - share), 1)
                if (row["factory_code"], stay[0]) != old_lane:  # chuyền chính cũ đã bị tách đi -> dòng gốc sang chuyền chính mới
                    rows.remove(row)
                    row["primary_line"] = stay[0]
                    lane = sorted((r for r in rows if lane_key(r) == lane_key(row)), key=lambda r: r["sequence"])
                    _insert_after(rows, row, lane[-1]["row_uid"] if lane else None)
                recalc_row(row, _prev_in_lane_by_position(rows, row))
                lane_new = sorted((r for r in rows if lane_key(r) == lane_key(new)), key=lambda r: r["sequence"])
                _insert_after(rows, new, lane_new[-1]["row_uid"] if lane_new else None)
                by_uid[uid] = new
                recalc_row(new, _prev_in_lane_by_position(rows, new))
                changed.update({row["row_uid"], uid})

            elif kind == "SET_TRANSFER":
                # Chuyển chuyền "2 ==> 1": chuyển phần còn lại sang chuyền khác từ ngày hiệu lực
                row = by_uid.get(op["rowUid"])
                if row is None:
                    raise OpError("Không tìm thấy dòng")
                current = " + ".join(row["line_assignments"])
                if op.get("clear"):
                    row["transfer"], row["line_raw"] = None, current
                else:
                    to_lines = _clean_lines(op.get("toLines"))
                    if set(to_lines) == set(row["line_assignments"]):
                        raise OpError("Chuyền đến phải khác chuyền hiện tại")
                    eff = _to_date(op.get("effectiveDate"))
                    remaining = op.get("plannedRemainingQty")
                    remaining = None if remaining in (None, "") else float(remaining)
                    if remaining is not None and not 0 <= remaining <= float(row["quantity"] or 0):
                        raise OpError("Số lượng còn lại chuyển đi phải trong khoảng 0 … số lượng của dòng")
                    to = " + ".join(to_lines)
                    row["transfer"] = {"from": current, "to": to, "effective_date": eff.isoformat() if eff else None, "planned_remaining_qty": remaining,
                                       "status": "EFFECTIVE" if eff and eff <= date.today() else "PLANNED"}
                    row["line_raw"] = f"{current} ==> {to}"
                changed.add(row["row_uid"])

            elif kind == "RECALC_LANE":
                # Tính lại theo công thức từ một dòng (hoặc đầu chuyền) đến hết chuyền; ô đang OVERRIDE được giữ nguyên
                lane_id = (op.get("factory") or "", str(op.get("line") or ""))
                lane = lane_of(rows, lane_id[0], lane_id[1])  # lane ảo: gồm cả dòng nhiều chuyền có chuyền này
                if not lane:
                    raise OpError(f"Không có dòng nào trong chuyền {lane_id[0]}/{lane_id[1]}")
                start = 0
                if op.get("fromRowUid"):
                    start = next((i for i, r in enumerate(lane) if r["row_uid"] == op["fromRowUid"]), None)
                    if start is None:
                        raise OpError("Dòng bắt đầu tính lại không thuộc chuyền này")
                for i in range(start, len(lane)):
                    recalc_row(lane[i], previous_sequence(rows, lane[i]))
                    changed.add(lane[i]["row_uid"])

            elif kind == "EDIT_FIELD":
                row = by_uid.get(op["rowUid"])
                field = op.get("field")
                if row is None or field not in EDITABLE_FIELDS:
                    raise OpError("Dòng hoặc cột không hợp lệ")
                value = op.get("value")
                if field == "transfer_effective_date":
                    if not row.get("transfer"):
                        raise OpError("Dòng này không có chuyển chuyền")
                    row["transfer"] = dict(row["transfer"], effective_date=_to_date(value).isoformat() if value else None)
                elif field in DATE_FIELDS:
                    _mark_override(row, field, row.get(field))
                    row[field] = _to_date(value)
                    (row["extra"].get("serial") or {}).pop(field, None)  # giá trị nhập tay là ngày nguyên
                elif field in ("quantity", "capacity", "total_day"):
                    num = float(value) if value not in (None, "") else None
                    if field == "total_day":
                        _mark_override(row, field, row.get(field))
                    row[field] = num
                else:
                    row[field] = str(value or "")[:400]
                changed.add(row["row_uid"])

            elif kind == "SET_OFF_DAYS":
                # Ghi đè OFF DAYS bằng tay: bắt buộc lý do; giữ cả giá trị tính + giá trị ghi đè + giá trị áp dụng
                row = by_uid.get(op["rowUid"])
                if row is None:
                    raise OpError("Dòng không tồn tại")
                try:
                    value = float(op.get("value"))
                except (TypeError, ValueError):
                    raise OpError("Giá trị OFF DAYS phải là số") from None
                if not 0 <= value <= 3660:
                    raise OpError("OFF DAYS phải trong khoảng 0…3660")
                reason = str(op.get("reason") or "").strip()
                if len(reason) < 3:
                    raise OpError("Ghi đè OFF DAYS bắt buộc nêu lý do")
                row.setdefault("extra", {})["off_days_override"] = {"value": value, "source": "MANUAL", "reason": reason[:300], "by": str(op.get("by") or ""), "at": str(op.get("at") or "")}
                recalc_row(row, _prev_in_lane_by_position(rows, row))
                changed.add(row["row_uid"])

            elif kind == "RESET_OFF_DAYS":
                row = by_uid.get(op["rowUid"])
                if row is None:
                    raise OpError("Dòng không tồn tại")
                (row.setdefault("extra", {})).pop("off_days_override", None)  # chỉ Reset mới bỏ ghi đè (đổi Lịch làm việc KHÔNG tự xóa ghi đè)
                recalc_row(row, _prev_in_lane_by_position(rows, row))
                changed.add(row["row_uid"])

            elif kind == "RETURN_TO_AUTO_CALC":
                row = by_uid.get(op["rowUid"])
                field = op.get("field")
                if row is None or field not in CALCULATED_FIELDS:
                    raise OpError("Dòng hoặc cột không hợp lệ")
                if field not in CALC_CODE:
                    raise OpError("Cột này chưa có công thức tự tính")
                (row["extra"].get("overrides") or {}).pop(field, None)
                fs = fx.active()
                if not fs.has(CALC_CODE[field]):
                    raise OpError("Cột này chưa có công thức được Publish")
                fs.apply(row, _prev_in_lane_by_position(rows, row), CALC_CODE[field])
                changed.add(row["row_uid"])
            else:
                raise OpError(f"Loại thao tác không hỗ trợ: {kind}")
        except OpError as exc:
            raise OpError(f"Thao tác #{n} ({kind}): {exc}") from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise OpError(f"Thao tác #{n} ({kind}) không hợp lệ: {exc}") from exc

    return sort_rows(reindex(rows)), changed


def _thaw(snap: dict) -> dict:
    """Ảnh chụp dòng lưu trong JSON (ngày dạng chuỗi) -> dòng dùng được trong engine."""
    row = dict(snap, extra=json.loads(json.dumps(snap.get("extra") or {})))
    for f in DATE_FIELDS:
        if isinstance(row.get(f), str):
            row[f] = _to_date(row[f])
    return row


MAX_LOOSE_LINES = 4  # dồn lẻ tối đa 4 chuyền; muốn nhiều hơn phải dồn TẤT CẢ chuyền của xí nghiệp (hiển thị 1:18)


def _natural(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def format_lines(lines: list[str]) -> str:
    """<= 4 chuyền: "4 + 5 + 9" (giữ thứ tự, chuyền chính đứng đầu). Nhiều hơn: gộp dải số liên tiếp, VD tất cả chuyền -> "1:18"."""
    if len(lines) <= MAX_LOOSE_LINES:
        return " + ".join(lines)
    nums = sorted((int(l) for l in lines if l.isdigit()))
    others = sorted((l for l in lines if not l.isdigit()), key=_natural)
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if i == j else f"{nums[i]}:{nums[j]}")
        i = j + 1
    return " + ".join([*parts, *others])


def _factory_lines(rows: list[dict], factory: str, known: dict[str, set[str]] | None) -> set[str]:
    out = set((known or {}).get(factory, set()))
    for r in rows:
        if r.get("factory_code") == factory:
            out.add(r["primary_line"])
            out.update(r.get("line_assignments") or [])
    return out


def _resolve_lines(op: dict, rows: list[dict], factory: str, primary: str, requested: list[str], known) -> list[str]:
    """Áp quy tắc: dồn lẻ tối đa 4 chuyền; dồn TẤT CẢ chuyền của xí nghiệp thì không giới hạn (cờ `all` hoặc tự nhận biết)."""
    all_set = _factory_lines(rows, factory, known)
    if op.get("all"):
        rest = sorted((l for l in all_set if l != primary), key=_natural)
        return [primary, *rest]
    if len(requested) > MAX_LOOSE_LINES and set(requested) != all_set:
        raise OpError(f"Dồn lẻ tối đa {MAX_LOOSE_LINES} chuyền — muốn dồn nhiều hơn hãy chọn Tất cả chuyền của xí nghiệp")
    return requested


def _clean_lines(value) -> list[str]:
    """['4', ' 5', '4'] -> ['4', '5'] (bỏ trống/trùng, giữ thứ tự); rỗng -> lỗi."""
    seen: list[str] = []
    for x in value or []:
        s = str(x).strip()
        if s and s not in seen:
            seen.append(s)
    if not seen:
        raise OpError("Cần ít nhất một chuyền")
    return seen


def _prev_in_lane_by_position(rows: list[dict], row: dict) -> dict | None:
    return previous_sequence(rows, row)


def _mark_override(row: dict, field: str, previous) -> None:
    overrides = row["extra"].setdefault("overrides", {})
    if field not in overrides:
        overrides[field] = {"source": "OVERRIDE", "calculated": previous.isoformat() if isinstance(previous, date) else previous}


# --------------------------------------------------------------------------- Recheck All Plan
def recheck(rows: list[dict], cal: CalendarResolver, factory_codes: set[str], resource_check=None) -> dict:
    """Tính lại + kiểm tra toàn bộ kế hoạch. Trả {result, issues, counts, trace_id, started_at, completed_at, duration_ms}."""
    fx.set_calendar(cal)
    t0 = time.perf_counter()
    started = datetime.now(timezone.utc)
    issues: list[dict] = []

    def add(sev, row, column, message, code):
        issues.append({"severity": sev, "row_uid": row["row_uid"] if row else "", "column": column, "message": message, "rule_code": code,
                       "po_number": row.get("po_number", "") if row else ""})

    seen_uid: set[str] = set()
    lanes: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if r["row_uid"] in seen_uid:
            add("ERROR", r, "row_uid", "Trùng định danh dòng", "ROW_DUP_UID")
        seen_uid.add(r["row_uid"])
        lanes.setdefault(lane_key(r), []).append(r)

        xn, line = r["factory_code"], r["primary_line"]
        if xn not in factory_codes:
            add("ERROR", r, "factory_code", f"Xí nghiệp '{xn or 'trống'}' không hợp lệ", "FACTORY_INVALID")
        if not line:
            add("ERROR", r, "primary_line", "Chưa có chuyền", "LINE_MISSING")
        if not r["quantity"] or r["quantity"] <= 0:
            add("ERROR", r, "quantity", "Số lượng phải > 0", "QTY_INVALID")
        b, e = r.get("begin_prod_date"), r.get("end_prod_date")
        if b and e and b > e:
            add("ERROR", r, "begin_prod_date", "Ngày vào chuyền sau ngày may xong", "DATE_ORDER")
        if not r.get("capacity"):
            add("WARNING", r, "capacity", "Thiếu năng suất chuyền/ngày (CAPACITY)", "CAPACITY_MISSING")
        if b and xn and line and not cal.is_working_day(b, xn, line):
            add("WARNING", r, "begin_prod_date", f"Ngày vào chuyền {b:%d/%m/%Y} là ngày OFF theo lịch làm việc", "BEGIN_ON_OFF_DAY")
        # (kiểm tra lệch công thức: xem vòng lặp theo chuyền bên dưới — cần dòng đứng trước theo thứ tự nghiệp vụ)
        end_or_wh = r.get("warehouse_date") or e
        if end_or_wh and r.get("chd") and end_or_wh > r["chd"]:
            add("WARNING", r, "chd", f"Kết thúc {end_or_wh:%d/%m/%Y} sau ngày khách yêu cầu (CHD) {r['chd']:%d/%m/%Y}", "LATE_VS_CHD")
        t = r.get("transfer")
        if t:
            eff = _to_date(t.get("effective_date"))
            if eff is None:
                add("WARNING", r, "transfer", "Chuyển chuyền chưa có ngày hiệu lực (TransferEffectiveDate)", "TRANSFER_DATE_MISSING")
            else:
                if b and e and not (b <= eff <= e):
                    add("ERROR", r, "transfer", f"Ngày hiệu lực chuyển chuyền {eff:%d/%m/%Y} nằm ngoài khoảng sản xuất", "TRANSFER_OUT_OF_RANGE")
                dest = str(t.get("to", "")).split("+")[0].strip()
                if dest and not cal.is_working_day(eff, xn, dest):
                    add("WARNING", r, "transfer", f"Chuyền đích {dest} không làm việc vào ngày hiệu lực {eff:%d/%m/%Y}", "TRANSFER_DEST_UNAVAILABLE")
            if t.get("from") and t.get("from") == t.get("to"):
                add("ERROR", r, "transfer", "Chuyền đi và chuyền đến trùng nhau", "TRANSFER_SAME_LINE")

    if resource_check is not None:  # năng suất / nhân lực / máy móc (nguồn lực)
        for r in rows:
            for sev, col, msg, code in resource_check(r):
                add(sev, r, col, msg, code)

    # SEQ_DUP theo lane SỞ HỮU (sequence là thứ tự của primary_line)
    for key, lane in lanes.items():
        seqs = [x["sequence"] for x in lane]
        if len(set(seqs)) != len(seqs):
            add("ERROR", sorted(lane, key=lambda x: x["sequence"])[0], "sequence", f"Trùng thứ tự trong chuyền {key[0]}/{key[1]}", "SEQ_DUP")

    # Công thức + chồng lấn theo LANE ẢO: dòng 4+5 xuất hiện trong cả lane 4 và lane 5; PREVIOUS_SEQUENCE = dòng trước trong lane ảo
    vlanes = build_lanes(rows)
    prev_of = previous_map(vlanes, rows)
    fs = fx.active()
    for key in sorted(lanes):
        for cur in sorted(lanes[key], key=lambda x: x["sequence"]):
            prev_row = prev_of.get(cur["row_uid"])
            for col, field, label in (("TOTAL_DAY", "total_day", "TOTAL_DAY"), ("BEGIN_PROD_DATE", "begin_prod_date", "BEGIN_PROD_DATE"), ("END_BEGIN_DATE", "end_prod_date", "END_BEGIN_DATE"), ("BEGIN_WAREHOUSE_IMPORT", "warehouse_date", "BEGIN_WAREHOUSE_IMPORT")):
                if not fs.has(col) or fs.is_overridden(cur, col):
                    continue
                if col == "BEGIN_PROD_DATE" and prev_row is None:
                    continue  # dòng đầu mọi chuyền của nó là mốc nhập tay
                try:
                    exp = fs.calculated(cur, prev_row, col)
                except Exception:  # noqa: BLE001 - thiếu dữ liệu đầu vào: đã có cảnh báo riêng (CAPACITY_MISSING...)
                    continue
                got = fs.stored(cur, col)
                if exp in (None, "") or got is None or isinstance(exp, str):
                    continue
                tol = 0.01
                if abs(float(got) - float(exp)) > tol:
                    add("WARNING", cur, field, f"{label} hiện tại khác kết quả công thức v{fs.formulas[col].version} (giữ nguyên giá trị kế hoạch, dùng Return to Auto Calculate nếu muốn cập nhật)", "CALC_MISMATCH")
    overlaps: dict[tuple[str, str], list[str]] = {}
    for (xn, line), lane in sorted(vlanes.items()):
        for prev, cur in zip(lane, lane[1:]):
            if prev.get("end_prod_date") and cur.get("begin_prod_date") and cur["begin_prod_date"] < prev["end_prod_date"]:
                overlaps.setdefault((cur["row_uid"], prev["row_uid"]), []).append(f"{xn}/{line}")
    by_uid = {r["row_uid"]: r for r in rows}
    for (cur_uid, prev_uid), where in overlaps.items():
        prev = by_uid[prev_uid]
        add("WARNING", by_uid[cur_uid], "begin_prod_date", f"Chồng lấn với dòng trước ({prev.get('po_number') or prev['row_uid']}) trên chuyền {', '.join(where)}", "LINE_OVERLAP")

    counts = Counter(i["severity"] for i in issues)
    result = "ERROR" if counts["ERROR"] else "WARNING" if counts["WARNING"] else "PASS"
    return {
        "result": result,
        "issues": issues,
        "counts": {"ERROR": counts["ERROR"], "WARNING": counts["WARNING"], "rows": len(rows)},
        "by_rule": dict(Counter(i["rule_code"] for i in issues)),
        "trace_id": uuid.uuid4().hex[:12],
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }


# --------------------------------------------------------------------------- so sánh phiên bản
def compare_versions(rows_a: list[dict], rows_b: list[dict], limit: int = 2000) -> dict:
    """So sánh A -> B theo row_uid (handoff §20)."""
    a = {r["row_uid"]: r for r in rows_a}
    b = {r["row_uid"]: r for r in rows_b}
    common = [u for u in a if u in b]

    def lane_order(rows_by_uid: dict[str, dict]) -> dict[str, tuple]:
        lanes: dict[tuple[str, str], list[str]] = {}
        for u in common:
            lanes.setdefault(lane_key(rows_by_uid[u]), []).append(u)
        pos = {}
        for key, uids in lanes.items():
            for i, u in enumerate(sorted(uids, key=lambda x: rows_by_uid[x]["sequence"])):
                pos[u] = (key, i)
        return pos

    pos_a, pos_b = lane_order(a), lane_order(b)
    changes: list[dict] = []

    def add(uid, row, category, field, before, after):
        changes.append({"row_uid": uid, "po_number": row.get("po_number", ""), "category": category, "field": field,
                        "before": _jsonable(before), "after": _jsonable(after)})

    for uid in b:
        if uid not in a:
            add(uid, b[uid], "ADDED", "", None, f"{b[uid]['factory_code']}/{b[uid]['primary_line']}")
    for uid in a:
        if uid not in b:
            add(uid, a[uid], "REMOVED", "", f"{a[uid]['factory_code']}/{a[uid]['primary_line']}", None)
    for uid in common:
        ra, rb = a[uid], b[uid]
        if lane_key(ra) != lane_key(rb):
            add(uid, rb, "LINE_CHANGE", "line", "/".join(lane_key(ra)), "/".join(lane_key(rb)))
        elif pos_a[uid] != pos_b[uid]:
            add(uid, rb, "SEQUENCE_CHANGE", "sequence", pos_a[uid][1] + 1, pos_b[uid][1] + 1)
        if list(ra.get("line_assignments") or []) != list(rb.get("line_assignments") or []) and lane_key(ra) == lane_key(rb):
            add(uid, rb, "MULTI_LINE_CHANGE", "line_assignments", ra.get("line_assignments"), rb.get("line_assignments"))
        if ra.get("quantity") != rb.get("quantity"):
            add(uid, rb, "QUANTITY_CHANGE", "quantity", ra.get("quantity"), rb.get("quantity"))
        if ra.get("capacity") != rb.get("capacity"):
            add(uid, rb, "CAPACITY_CHANGE", "capacity", ra.get("capacity"), rb.get("capacity"))
        for f in ("begin_prod_date", "end_prod_date", "warehouse_date", "chd"):
            if ra.get(f) != rb.get(f):
                add(uid, rb, "DATE_CHANGE", f, ra.get(f), rb.get(f))
        if (ra.get("transfer") or None) != (rb.get("transfer") or None):
            add(uid, rb, "TRANSFER_CHANGE", "transfer", ra.get("transfer"), rb.get("transfer"))
        oa, ob = set((ra.get("extra") or {}).get("overrides") or {}), set((rb.get("extra") or {}).get("overrides") or {})
        if oa != ob:
            add(uid, rb, "OVERRIDE_CHANGE", "overrides", sorted(oa), sorted(ob))
        if ra.get("total_day") != rb.get("total_day") and rb.get("total_day") is not None:
            add(uid, rb, "FORMULA_RESULT_CHANGE", "total_day", ra.get("total_day"), rb.get("total_day"))
    summary = dict(Counter(c["category"] for c in changes))
    return {"summary": summary, "total_changes": len(changes), "changes": changes[:limit], "truncated": len(changes) > limit}


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v
