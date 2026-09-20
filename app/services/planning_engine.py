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

from app.services.calendar import CalendarResolver
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
    """Xây lại thứ tự 1..n trong từng lane (XN, chuyền) — tương đương virtualSequence sau thao tác cấu trúc."""
    lanes: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        lanes.setdefault(lane_key(r), []).append(r)
    out: list[dict] = []
    for key in sorted(lanes):
        for i, r in enumerate(sorted(lanes[key], key=lambda x: x["sequence"]), start=1):
            r["sequence"] = i
            out.append(r)
    return out


# --------------------------------------------------------------------------- tự tính (công thức tối thiểu)
def calc_total_day(quantity, capacity) -> float | None:
    return round(quantity / capacity, 4) if quantity and capacity else None


def calc_begin(prev: dict | None, cal: CalendarResolver, xn: str, line: str) -> date | None:
    """BEGIN_PROD_DATE = PREVIOUS_SEQUENCE.END_PROD_DATE + 1 Working Day."""
    if prev is None or prev.get("end_prod_date") is None:
        return None
    return cal.add_working_days(prev["end_prod_date"], 1, xn, line)


def calc_end(begin: date | None, total_day, cal: CalendarResolver, xn: str, line: str) -> date | None:
    if begin is None or not total_day:
        return None
    days = max(1, math.ceil(total_day - 1e-9))
    return cal.add_working_days(begin, days - 1, xn, line)


def _prev_in_lane(rows: list[dict], row: dict) -> dict | None:
    lane = sorted((r for r in rows if lane_key(r) == lane_key(row)), key=lambda r: r["sequence"])
    idx = next((i for i, r in enumerate(lane) if r["row_uid"] == row["row_uid"]), None)
    return lane[idx - 1] if idx else None


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
) -> tuple[list[dict], set[str]]:
    """Áp danh sách thao tác lên bản sao của base_rows. Trả (rows đã reindex, tập row_uid bị thay đổi).

    `returned` (tùy chọn) là danh sách dòng đã trả về Unplanned; được cập nhật tại chỗ bởi UNPLAN / ADD_RETURNED.
    """
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
                    "quantity": src["quantity"], "capacity": capacity, "total_day": calc_total_day(src["quantity"], capacity),
                    "begin_prod_date": None, "end_prod_date": None, "warehouse_date": None, "chd": src.get("chd"),
                    "note": src.get("note", ""), "extra": {},
                }
                _insert_after(rows, row, op.get("afterRowUid"))
                prev = _prev_in_lane_by_position(rows, row)
                row["begin_prod_date"] = calc_begin(prev, cal, factory, line)
                row["end_prod_date"] = calc_end(row["begin_prod_date"], row["total_day"], cal, factory, line)
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
                prev = _prev_in_lane_by_position(rows, row)
                row["begin_prod_date"] = calc_begin(prev, cal, factory, line)
                row["end_prod_date"] = calc_end(row["begin_prod_date"], row.get("total_day"), cal, factory, line)
                by_uid[row["row_uid"]] = row
                changed.add(row["row_uid"])

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
                elif field in ("quantity", "capacity", "total_day"):
                    num = float(value) if value not in (None, "") else None
                    if field == "total_day":
                        _mark_override(row, field, row.get(field))
                    row[field] = num
                else:
                    row[field] = str(value or "")[:400]
                changed.add(row["row_uid"])

            elif kind == "RETURN_TO_AUTO_CALC":
                row = by_uid.get(op["rowUid"])
                field = op.get("field")
                if row is None or field not in CALCULATED_FIELDS:
                    raise OpError("Dòng hoặc cột không hợp lệ")
                xn, line = row["factory_code"], row["primary_line"]
                if field == "total_day":
                    row[field] = calc_total_day(row["quantity"], row["capacity"])
                elif field == "begin_prod_date":
                    row[field] = calc_begin(_prev_in_lane_by_position(rows, row), cal, xn, line)
                elif field == "end_prod_date":
                    row[field] = calc_end(row["begin_prod_date"], row["total_day"], cal, xn, line)
                else:
                    raise OpError("Cột này chưa có công thức tự tính")
                (row["extra"].get("overrides") or {}).pop(field, None)
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


def _prev_in_lane_by_position(rows: list[dict], row: dict) -> dict | None:
    lane = sorted((r for r in rows if lane_key(r) == lane_key(row)), key=lambda r: r["sequence"])
    idx = next((i for i, r in enumerate(lane) if r is row), None)
    return lane[idx - 1] if idx else None


def _mark_override(row: dict, field: str, previous) -> None:
    overrides = row["extra"].setdefault("overrides", {})
    if field not in overrides:
        overrides[field] = {"source": "OVERRIDE", "calculated": previous.isoformat() if isinstance(previous, date) else previous}


# --------------------------------------------------------------------------- Recheck All Plan
def recheck(rows: list[dict], cal: CalendarResolver, factory_codes: set[str]) -> dict:
    """Tính lại + kiểm tra toàn bộ kế hoạch. Trả {result, issues, counts, trace_id, started_at, completed_at, duration_ms}."""
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
        expected = calc_total_day(r["quantity"], r.get("capacity"))
        tot = r.get("total_day")
        overridden = "total_day" in (r.get("extra", {}).get("overrides") or {})
        if expected is not None and tot is not None and abs(tot - expected) > 0.01 and not overridden:
            add("WARNING", r, "total_day", f"TOTAL_DAY={tot:.2f} khác kết quả tự tính {expected:.2f} (giữ nguyên giá trị kế hoạch, dùng Return to Auto Calculate nếu muốn cập nhật)", "CALC_MISMATCH")
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

    for key, lane in lanes.items():
        lane.sort(key=lambda x: x["sequence"])
        seqs = [x["sequence"] for x in lane]
        if len(set(seqs)) != len(seqs):
            add("ERROR", lane[0], "sequence", f"Trùng thứ tự trong chuyền {key[0]}/{key[1]}", "SEQ_DUP")
        for prev, cur in zip(lane, lane[1:]):
            if prev.get("end_prod_date") and cur.get("begin_prod_date") and cur["begin_prod_date"] < prev["end_prod_date"]:
                add("WARNING", cur, "begin_prod_date", f"Chồng lấn với dòng trước ({prev.get('po_number') or prev['row_uid']}) trên chuyền {key[0]}/{key[1]}", "LINE_OVERLAP")

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
