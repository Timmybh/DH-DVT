"""Virtual lane (handoff §7/§15): một dòng chạy trên NHIỀU chuyền (line_assignments, VD 4 + 5) thuộc TẤT CẢ các lane tương ứng.

- Lane (XN, chuyền L) = các dòng có primary_line == L ("sở hữu", thứ tự theo `sequence`) + các dòng nhiều chuyền có L trong line_assignments ("thành viên phụ").
- Thành viên phụ đứng sau dòng neo `extra.vanchor[L]` (row_uid dòng sở hữu đứng ngay trước nó; None = đầu lane). Chưa có neo (hoặc neo không còn) thì suy ra theo
  (ngày bắt đầu, sequence): đứng trước dòng sở hữu đầu tiên có khóa lớn hơn hoặc bằng khóa của nó.
- `extra.virtual_sequence[L]` = chỉ số 1..m của dòng trong lane ảo L (thông tin/hiển thị; nguồn thứ tự thật là `sequence` + neo).
- PREVIOUS_SEQUENCE của một dòng = dòng đứng trước nó trong lane ảo; dòng nhiều chuyền không thể bắt đầu trước khi MỌI chuyền rảnh nên lấy dòng trước có ngày kết thúc muộn nhất.
"""

from collections import defaultdict
from datetime import date


def _to_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def row_lines(row: dict) -> list[str]:
    """Các chuyền của dòng, chuyền chính đứng đầu, không trùng."""
    out: list[str] = []
    for line in [row.get("primary_line"), *(row.get("line_assignments") or [])]:
        if line and str(line) not in out:
            out.append(str(line))
    return out


def _key(r: dict) -> tuple:
    return (_to_date(r.get("begin_prod_date")) or date.max, r.get("sequence") or 0)


def order_lane(line: str, members: list[dict]) -> list[dict]:
    """Sắp xếp thành viên của lane ảo (cùng XN) theo quy tắc trên."""
    owned = sorted((r for r in members if r.get("primary_line") == line), key=lambda r: r["sequence"])
    sec = [r for r in members if r.get("primary_line") != line]
    if not sec:
        return owned
    pos_of = {r["row_uid"]: i for i, r in enumerate(owned)}
    by_pos: dict[int, list[dict]] = defaultdict(list)
    for s in sec:
        anchors = (s.get("extra") or {}).get("vanchor") or {}
        anchor = anchors.get(line, "__missing__")
        if anchor is None:
            pos = 0
        elif anchor in pos_of:
            pos = pos_of[anchor] + 1
        else:  # chưa có neo / neo đã mất -> suy ra theo (ngày bắt đầu, sequence)
            k = _key(s)
            pos = 0
            for i, o in enumerate(owned):
                if _key(o) < k:
                    pos = i + 1
        by_pos[pos].append(s)
    out: list[dict] = []
    for p in range(len(owned) + 1):
        out.extend(sorted(by_pos.get(p, []), key=lambda r: (_key(r), r["row_uid"])))
        if p < len(owned):
            out.append(owned[p])
    return out


def build_lanes(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """{(XN, chuyền): các dòng theo thứ tự lane ảo} — dòng nhiều chuyền xuất hiện ở mọi lane của nó."""
    members: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        for line in row_lines(r):
            members[(r.get("factory_code", ""), line)].append(r)
    return {key: order_lane(key[1], ms) for key, ms in members.items()}


def lane_of(rows: list[dict], factory: str, line: str) -> list[dict]:
    return order_lane(line, [r for r in rows if r.get("factory_code", "") == factory and line in row_lines(r)])


def prev_in_lane(rows: list[dict], row: dict, line: str) -> dict | None:
    lane = lane_of(rows, row.get("factory_code", ""), line)
    idx = next((i for i, r in enumerate(lane) if r is row or r["row_uid"] == row["row_uid"]), None)
    return lane[idx - 1] if idx else None


def pick_previous(prevs: list[dict | None], primary_prev: dict | None) -> dict | None:
    cands = [p for p in prevs if p is not None]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    return max(cands, key=lambda p: (_to_date(p.get("end_prod_date")) or date.min, p is primary_prev))


def previous_sequence(rows: list[dict], row: dict) -> dict | None:
    """PREVIOUS_SEQUENCE theo lane ảo (mọi chuyền của dòng), không theo primary_line."""
    lines = row_lines(row)
    prevs = [prev_in_lane(rows, row, line) for line in lines]
    return pick_previous(prevs, prevs[0] if prevs else None)


def previous_map(lanes: dict[tuple[str, str], list[dict]], rows: list[dict]) -> dict[str, dict | None]:
    """{row_uid: PREVIOUS_SEQUENCE} tính một lần cho toàn bộ dòng (dùng trong Recheck / dựng baseline)."""
    per_row: dict[str, dict[str, dict | None]] = defaultdict(dict)
    for (_xn, line), lane in lanes.items():
        for i, r in enumerate(lane):
            per_row[r["row_uid"]][line] = lane[i - 1] if i else None
    out: dict[str, dict | None] = {}
    for r in rows:
        by_line = per_row.get(r["row_uid"], {})
        lines = row_lines(r)
        out[r["row_uid"]] = pick_previous([by_line.get(line) for line in lines], by_line.get(lines[0]) if lines else None)
    return out


def refresh_virtual(rows: list[dict]) -> None:
    """Cập nhật extra.virtual_sequence (chỉ số trong từng lane ảo) và extra.vanchor (neo của thành viên phụ) cho mọi dòng."""
    lanes = build_lanes(rows)
    for r in rows:
        ex = r.setdefault("extra", {})
        ex["virtual_sequence"] = {}
        anchors = {k: v for k, v in (ex.get("vanchor") or {}).items() if k in row_lines(r)}
        ex["vanchor"] = anchors
    for (xn, line), lane in lanes.items():
        last_owned: str | None = None
        for i, r in enumerate(lane, start=1):
            r["extra"]["virtual_sequence"][line] = i
            if r.get("primary_line") == line:
                last_owned = r["row_uid"]
                r["extra"]["vanchor"].pop(line, None)
            else:
                r["extra"]["vanchor"][line] = last_owned
    for r in rows:
        if not r["extra"]["vanchor"]:
            r["extra"].pop("vanchor")
