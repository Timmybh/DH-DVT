"""Capacity Definition (phân giải theo mức cụ thể nhất), Machine Capacity, nhân lực khả dụng, kiểm tra nguồn lực và Lịch giải phóng nguồn lực."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.data import PlanRow
from app.models.planning import PlanningVersionRow
from app.models.resources import CapacityDefinition, LaborDaily, MachineCapacity, MachineRequirement, MachineType
from app.services.audit import write_audit
from app.services.formula import EXCEL_EPOCH


# ------------------------------------------------------------------ Capacity Definition
def cap_view(c: CapacityDefinition) -> dict:
    return {
        "id": c.id, "factory_code": c.factory_code, "line": c.line, "style_cc": c.style_cc, "model_code": c.model_code, "process": c.process,
        "worker_count": c.worker_count, "working_minutes": c.working_minutes, "capacity_per_day": c.capacity_per_day,
        "effective_from": c.effective_from.isoformat() if c.effective_from else None, "effective_to": c.effective_to.isoformat() if c.effective_to else None,
        "source": c.source, "owner": c.owner, "status": c.status, "version": c.version, "notes": c.notes, "created_by": c.created_by, "created_at": c.created_at.isoformat(),
    }


def _specificity(d: dict, factory: str, line: str, style: str, model: str) -> int | None:
    """Điểm đặc thù: khớp từng trường được khai báo; trường khai báo mà KHÔNG khớp -> loại. Trường trống = wildcard."""
    score = 0
    for key, weight, val in (("line", 8, line), ("style_cc", 4, style), ("model_code", 2, model), ("factory_code", 1, factory)):
        want = d.get(key) or ""
        if want:
            if want != val:
                return None
            score += weight
    return score


def resolve_capacity(defs: list[dict], factory: str, line: str, style: str, model: str, on: date | None) -> dict | None:
    """Định nghĩa ACTIVE còn hiệu lực, cụ thể nhất thắng; đồng điểm -> phiên bản cao hơn, rồi id lớn hơn."""
    best, best_key = None, None
    for d in defs:
        if d.get("status") != "ACTIVE":
            continue
        if on is not None:
            if d.get("effective_from") and on < d["effective_from"]:
                continue
            if d.get("effective_to") and on > d["effective_to"]:
                continue
        sc = _specificity(d, factory, line, style, model)
        if sc is None:
            continue
        key = (sc, d.get("version", 1), d.get("id", 0))
        if best_key is None or key > best_key:
            best, best_key = d, key
    return best


def load_capacity_defs(db: Session) -> list[dict]:
    return [
        {"id": c.id, "factory_code": c.factory_code, "line": c.line, "style_cc": c.style_cc, "model_code": c.model_code, "capacity_per_day": c.capacity_per_day,
         "worker_count": c.worker_count, "effective_from": c.effective_from, "effective_to": c.effective_to, "source": c.source, "version": c.version, "status": c.status}
        for c in db.query(CapacityDefinition).filter(CapacityDefinition.status == "ACTIVE")
    ]


def _validate_capacity(d: dict) -> None:
    if not d.get("capacity_per_day") or float(d["capacity_per_day"]) <= 0:
        raise HTTPException(422, "Năng suất (pcs/ngày) phải > 0")
    if d.get("effective_from") and d.get("effective_to") and d["effective_from"] > d["effective_to"]:
        raise HTTPException(422, "Ngày hiệu lực đến phải sau ngày hiệu lực từ")
    if d.get("source", "MANUAL") not in ("IE", "LEAN", "CI", "WORKBOOK", "MANUAL"):
        raise HTTPException(422, "Nguồn phải là IE, LEAN, CI, WORKBOOK hoặc MANUAL")


CAP_FIELDS = ("factory_code", "line", "style_cc", "model_code", "process", "worker_count", "working_minutes", "capacity_per_day", "effective_from", "effective_to", "source", "owner", "notes")


def create_capacity(db: Session, user: User, d: dict) -> CapacityDefinition:
    _validate_capacity(d)
    row = CapacityDefinition(created_by=user.username, status="ACTIVE", version=1, **{k: d.get(k) for k in CAP_FIELDS if k in d})
    db.add(row)
    db.commit()
    write_audit("CAPACITY_CREATE", user=user, object_type="CapacityDefinition", object_id=str(row.id), detail=f"{row.factory_code}/{row.line}/{row.style_cc} = {row.capacity_per_day}")
    return row


def revise_capacity(db: Session, user: User, cap_id: int, d: dict) -> CapacityDefinition:
    """Sửa = phiên bản mới cùng khóa nghiệp vụ; bản cũ RETIRED và khép hiệu lực (giữ lịch sử để truy vết Planning cũ)."""
    old = db.get(CapacityDefinition, cap_id)
    if old is None:
        raise HTTPException(404, "Không tìm thấy định nghĩa năng suất")
    if old.status != "ACTIVE":
        raise HTTPException(409, "Chỉ sửa được định nghĩa đang ACTIVE")
    merged = {k: getattr(old, k) for k in CAP_FIELDS}
    merged.update({k: d[k] for k in CAP_FIELDS if k in d})
    _validate_capacity(merged)
    old.status = "RETIRED"
    if old.effective_to is None:
        old.effective_to = date.today()
    new = CapacityDefinition(created_by=user.username, status="ACTIVE", version=old.version + 1, **merged)
    db.add(new)
    db.commit()
    write_audit("CAPACITY_REVISE", user=user, object_type="CapacityDefinition", object_id=f"{new.id} (v{new.version})", detail=f"{old.capacity_per_day} -> {new.capacity_per_day}")
    return new


def retire_capacity(db: Session, user: User, cap_id: int) -> CapacityDefinition:
    c = db.get(CapacityDefinition, cap_id)
    if c is None:
        raise HTTPException(404, "Không tìm thấy định nghĩa năng suất")
    c.status = "RETIRED"
    db.commit()
    write_audit("CAPACITY_RETIRE", user=user, object_type="CapacityDefinition", object_id=str(c.id))
    return c


def import_capacity_from_plan(db: Session, user: User) -> dict:
    """Khởi tạo Capacity Definition (nguồn WORKBOOK) từ file kế hoạch SX đã nhập: (XN, chuyền, style) -> năng suất phổ biến nhất."""
    from app.services.dashboard import current_batch
    from app.services.planning_engine import parse_line_notation

    batch = current_batch(db)
    if batch is None:
        raise HTTPException(409, "Chưa nhập file kế hoạch SX")
    from app.models.core import Factory

    fcode = {f.id: f.code for f in db.query(Factory)}
    groups: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    workers: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for pr in db.query(PlanRow).filter(PlanRow.batch_id == batch.id, PlanRow.planning_status == "PLANNED", PlanRow.capacity.isnot(None), PlanRow.capacity > 0):
        assign, _t, _d = parse_line_notation(pr.line_raw)
        if pr.factory_id is None or not assign or len(assign) != 1 or not pr.style_cc:
            continue  # chuyền dồn/chuyển không đại diện cho năng suất một chuyền
        key = (fcode[pr.factory_id], assign[0], pr.style_cc)
        groups[key][round(pr.capacity)] += 1
        if pr.worker:
            workers[key][round(pr.worker)] += 1
    have = {(c.factory_code, c.line, c.style_cc) for c in db.query(CapacityDefinition).filter(CapacityDefinition.status == "ACTIVE", CapacityDefinition.source == "WORKBOOK")}
    created = 0
    for key, cnt in groups.items():
        if key in have:
            continue
        w = workers[key].most_common(1)[0][0] if workers[key] else None
        db.add(CapacityDefinition(factory_code=key[0], line=key[1], style_cc=key[2], capacity_per_day=float(cnt.most_common(1)[0][0]), worker_count=w, source="WORKBOOK",
                                  owner="import", created_by=user.username, notes=f"Suy ra từ file kế hoạch ({sum(cnt.values())} dòng) — cần IE xác nhận"))
        created += 1
    db.commit()
    write_audit("CAPACITY_IMPORT", user=user, object_type="CapacityDefinition", object_id="WORKBOOK", detail=f"tạo {created} định nghĩa")
    return {"created": created, "groups": len(groups)}


# ------------------------------------------------------------------ Machine
def machine_cap_view(m: MachineCapacity) -> dict:
    return {"id": m.id, "factory_code": m.factory_code, "line": m.line, "machine_type": m.machine_type, "quantity": m.quantity, "nominal_output_per_day": m.nominal_output_per_day,
            "efficiency": m.efficiency, "changeover_minutes": m.changeover_minutes, "planned_downtime_pct": m.planned_downtime_pct, "maintenance_status": m.maintenance_status,
            "is_bottleneck": m.is_bottleneck, "effective_from": m.effective_from.isoformat() if m.effective_from else None,
            "effective_to": m.effective_to.isoformat() if m.effective_to else None, "notes": m.notes, "status": m.status}


MACHINE_FIELDS = ("factory_code", "line", "machine_type", "quantity", "nominal_output_per_day", "efficiency", "changeover_minutes", "planned_downtime_pct", "maintenance_status",
                  "is_bottleneck", "effective_from", "effective_to", "notes", "status")


def save_machine_capacity(db: Session, user: User, d: dict, mid: int | None = None) -> MachineCapacity:
    if d.get("efficiency") is not None and not 0 < float(d["efficiency"]) <= 1:
        raise HTTPException(422, "Hiệu suất (OEE) phải trong khoảng (0, 1]")
    if d.get("maintenance_status", "OK") not in ("OK", "MAINTENANCE", "DOWN"):
        raise HTTPException(422, "Tình trạng bảo trì phải là OK, MAINTENANCE hoặc DOWN")
    if d.get("quantity") is not None and int(d["quantity"]) < 0:
        raise HTTPException(422, "Số lượng máy không được âm")
    if mid is None:
        if not d.get("factory_code") or not d.get("line") or not d.get("machine_type"):
            raise HTTPException(422, "Cần xí nghiệp, chuyền và nhóm máy")
        row = MachineCapacity(updated_by=user.username, **{k: d[k] for k in MACHINE_FIELDS if k in d})
        db.add(row)
        action = "MACHINE_CAPACITY_CREATE"
    else:
        row = db.get(MachineCapacity, mid)
        if row is None:
            raise HTTPException(404, "Không tìm thấy bản ghi máy")
        for k in MACHINE_FIELDS:
            if k in d:
                setattr(row, k, d[k])
        row.updated_by, row.updated_at = user.username, utcnow()
        action = "MACHINE_CAPACITY_UPDATE"
    db.commit()
    write_audit(action, user=user, object_type="MachineCapacity", object_id=str(row.id), detail=f"{row.factory_code}/{row.line}/{row.machine_type} x{row.quantity}")
    return row


# ------------------------------------------------------------------ nguồn lực dùng cho Recheck
class Resources:
    """Ảnh chụp nguồn lực cho một lần Recheck (đọc DB một lần)."""

    def __init__(self, cap_defs=None, labor=None, requirements=None, machines=None, machine_output=None, machine_status=None, as_of: date | None = None):
        self.as_of = as_of or date.today()  # nhân lực chỉ so với các dòng chưa kết thúc tại thời điểm này (số liệu lao động là hiện tại)
        self.cap_defs = cap_defs or []
        self.labor = labor or {}  # (xn, line) -> present
        self.requirements = requirements or {}  # style -> [(type, qty)]
        self.machines = machines or {}  # (xn, line, type) -> qty
        self.machine_output = machine_output or {}  # (xn, line, type) -> pcs/ngày hiệu dụng
        self.machine_status = machine_status or {}  # (xn, line, type) -> OK|MAINTENANCE|DOWN

    def factory_lines(self) -> dict[str, set[str]]:
        """Các chuyền đã biết theo xí nghiệp (lao động, máy, định nghĩa năng suất) — bổ sung cho chuyền có trong kế hoạch."""
        out: dict[str, set[str]] = defaultdict(set)
        for (xn, line) in self.labor:
            out[xn].add(line)
        for (xn, line, _t) in self.machines:
            out[xn].add(line)
        for d in self.cap_defs:
            if d.get("factory_code") and d.get("line"):
                out[d["factory_code"]].add(d["line"])
        return dict(out)

    def check(self, row: dict) -> list[tuple[str, str, str, str]]:
        return check_row_resources(self, row)

    def capacity_for(self, row: dict, on: date | None = None) -> dict | None:
        return resolve_capacity(self.cap_defs, row.get("factory_code", ""), row.get("primary_line", ""), row.get("style_cc", ""), row.get("model_code", ""), on)


def latest_labor(db: Session) -> dict[tuple[str, str], dict]:
    """Số lao động có mặt gần nhất theo (XN, chuyền)."""
    out: dict[tuple[str, str], dict] = {}
    for r in db.query(LaborDaily).order_by(LaborDaily.day):
        out[(r.factory_code, r.line)] = {"day": r.day, "present": r.present, "total": r.total}
    return out


def load_resources(db: Session) -> Resources:
    reqs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in db.query(MachineRequirement):
        reqs[r.style_cc].append((r.machine_type, r.quantity))
    machines, output, status = {}, {}, {}
    for m in db.query(MachineCapacity).filter(MachineCapacity.status == "ACTIVE"):
        k = (m.factory_code, m.line, m.machine_type)
        machines[k] = machines.get(k, 0) + m.quantity
        status[k] = m.maintenance_status
        if m.nominal_output_per_day:
            output[k] = m.nominal_output_per_day * (m.efficiency or 1.0)
    labor = {k: v["present"] for k, v in latest_labor(db).items()}
    return Resources(load_capacity_defs(db), labor, dict(reqs), machines, output, status)


def check_row_resources(res: Resources, row: dict) -> list[tuple[str, str, str, str]]:
    """Trả [(severity, column, message, rule_code)] cho một dòng Planning."""
    out: list[tuple[str, str, str, str]] = []
    xn, line, style = row.get("factory_code", ""), row.get("primary_line", ""), row.get("style_cc", "")
    cap = row.get("capacity")
    d = res.capacity_for(row, row.get("begin_prod_date"))
    if d and cap and abs(cap - d["capacity_per_day"]) / d["capacity_per_day"] > 0.02:
        out.append(("WARNING", "capacity", f"CAPACITY {cap:,.0f} khác định nghĩa năng suất {d['capacity_per_day']:,.0f} pcs/ngày (nguồn {d['source']} v{d['version']})", "CAPACITY_DEFINITION_MISMATCH"))
    worker = ((row.get("extra") or {}).get("ref") or {}).get("worker")
    present = res.labor.get((xn, line))
    end_day = _floor_day(row, "end_prod_date", "end_prod_date")
    still_running = end_day is None or end_day >= res.as_of
    if worker and present is not None and still_running and worker > present:
        out.append(("WARNING", "worker", f"Cần {worker:.0f} lao động nhưng chuyền {xn}/{line} chỉ có {present} người có mặt (lần đồng bộ gần nhất)", "LABOR_SHORTAGE"))
    for mtype, need in res.requirements.get(style, []):
        k = (xn, line, mtype)
        if k in res.machines:
            if res.machine_status.get(k) == "DOWN":
                out.append(("WARNING", "line", f"Nhóm máy {mtype} của chuyền {xn}/{line} đang ngừng (DOWN)", "MACHINE_UNAVAILABLE"))
            elif res.machines[k] < need:
                out.append(("WARNING", "line", f"Mã {style} cần {need} máy {mtype} nhưng chuyền {xn}/{line} chỉ có {res.machines[k]}", "MACHINE_SHORTAGE"))
            elif k in res.machine_output and cap and res.machine_output[k] < cap:
                out.append(("WARNING", "capacity", f"Máy {mtype} của chuyền {xn}/{line} chỉ đạt {res.machine_output[k]:,.0f} pcs/ngày, thấp hơn CAPACITY {cap:,.0f} (nút thắt máy)", "MACHINE_BOTTLENECK"))
    return out


# ------------------------------------------------------------------ Lịch giải phóng nguồn lực
def _floor_day(row: dict, field: str, serial_key: str) -> date | None:
    serial = ((row.get("extra") or {}).get("serial") or {}).get(serial_key)
    if serial is not None:
        return EXCEL_EPOCH + timedelta(days=int(math.floor(serial)))
    v = row.get(field)
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    return v


def release_schedule(rows: list[dict], week_start: date, requirements: dict[str, list[tuple[str, int]]] | None = None) -> dict:
    """Giải phóng trong ngày D của một chuyền = max(0, đang giữ(D−1) − đang giữ(D)).

    Lao động giữ = tổng WORKER của các dòng đang chạy trên chuyền; máy giữ = tổng số máy theo yêu cầu mã hàng (nếu có).
    """
    requirements = requirements or {}
    days = [week_start + timedelta(days=i) for i in range(7)]
    span = [week_start - timedelta(days=1), *days]
    reserved: dict[tuple[str, str], dict[date, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for r in rows:
        b, e = _floor_day(r, "begin_prod_date", "begin_prod_date"), _floor_day(r, "end_prod_date", "end_prod_date")
        if not b or not e:
            continue
        worker = float(((r.get("extra") or {}).get("ref") or {}).get("worker") or 0)
        machines = float(sum(q for _t, q in requirements.get(r.get("style_cc", ""), [])))
        key = (r["factory_code"], r["primary_line"])
        for d in span:
            if b <= d <= e:
                reserved[key][d][0] += worker
                reserved[key][d][1] += machines
    tree: dict[str, list[dict]] = defaultdict(list)
    def natural(s: str):
        return [int(t) if t.isdigit() else t for t in __import__("re").split(r"(\d+)", s)]

    for (xn, line), per in sorted(reserved.items(), key=lambda kv: (kv[0][0], natural(kv[0][1]))):
        cells = []
        for i, d in enumerate(days):
            prev, cur = per.get(span[i], [0.0, 0.0]), per.get(d, [0.0, 0.0])
            cells.append({"date": d.isoformat(), "labor": round(max(0.0, prev[0] - cur[0]), 1), "machine": round(max(0.0, prev[1] - cur[1]), 1),
                          "reserved_labor": round(cur[0], 1), "reserved_machine": round(cur[1], 1)})
        tree[xn].append({"line": line, "days": cells})
    factories = []
    for xn, lines in sorted(tree.items()):
        totals = [{"date": d.isoformat(), "labor": round(sum(l["days"][i]["labor"] for l in lines), 1), "machine": round(sum(l["days"][i]["machine"] for l in lines), 1)} for i, d in enumerate(days)]
        factories.append({"factory": xn, "totals": totals, "lines": lines})
    return {"week_start": week_start.isoformat(), "days": [d.isoformat() for d in days], "factories": factories,
            "note": "Giải phóng = phần nguồn lực được trả lại trong ngày (đang giữ hôm trước trừ đang giữ hôm nay). Máy chỉ tính cho mã hàng có yêu cầu máy."}


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def release_for_version(db: Session, version_id: int, week_start: date) -> dict:
    from app.services.planning_service import get_version, load_rows

    get_version(db, version_id)
    rows = load_rows(db, version_id)
    reqs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in db.query(MachineRequirement):
        reqs[r.style_cc].append((r.machine_type, r.quantity))
    # bổ sung ref (worker) cho dòng chưa lưu ref theo phiên bản
    from app.services.planning_service import refs_for_rows

    refs = refs_for_rows(db, rows)
    for r in rows:
        if not (r.get("extra") or {}).get("ref") and refs.get(r["row_uid"]):
            r.setdefault("extra", {})["ref"] = refs[r["row_uid"]]
    return release_schedule(rows, week_start, dict(reqs))
