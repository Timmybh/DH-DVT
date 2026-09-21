"""Capacity Definition (phân giải theo mức cụ thể nhất), Machine Capacity, nhân lực khả dụng, kiểm tra nguồn lực và Lịch nguồn lực rảnh."""

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
from app.models.resources import CapacityDefinition, LaborDaily, MachineCapacity, MachineMaintenance, MachineRequirement, MachineSharedPool, MachineSharing, MachineStyleOutput, MachineType
from app.services.audit import write_audit
from app.services.formula import EXCEL_EPOCH
from app.services.lanes import row_lines


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
            "effective_to": m.effective_to.isoformat() if m.effective_to else None, "notes": m.notes, "status": m.status,
            "maintenance_quantity": m.maintenance_quantity, "down_quantity": m.down_quantity, "available_quantity": max(0, m.quantity - m.maintenance_quantity - m.down_quantity)}


MACHINE_FIELDS = ("factory_code", "line", "machine_type", "quantity", "nominal_output_per_day", "efficiency", "changeover_minutes", "planned_downtime_pct", "maintenance_status",
                  "is_bottleneck", "effective_from", "effective_to", "notes", "status", "maintenance_quantity", "down_quantity")


def save_machine_capacity(db: Session, user: User, d: dict, mid: int | None = None) -> MachineCapacity:
    if d.get("efficiency") is not None and not 0 < float(d["efficiency"]) <= 1:
        raise HTTPException(422, "Hiệu suất (OEE) phải trong khoảng (0, 1]")
    if d.get("maintenance_status", "OK") not in ("OK", "MAINTENANCE", "DOWN"):
        raise HTTPException(422, "Tình trạng bảo trì phải là OK, MAINTENANCE hoặc DOWN")
    if d.get("quantity") is not None and int(d["quantity"]) < 0:
        raise HTTPException(422, "Số lượng máy không được âm")
    if any(d.get(k) is not None and int(d[k]) < 0 for k in ("maintenance_quantity", "down_quantity")):
        raise HTTPException(422, "Số máy bảo trì/hỏng không được âm")
    if d.get("quantity") is not None and int(d.get("maintenance_quantity") or 0) + int(d.get("down_quantity") or 0) > int(d["quantity"]):
        raise HTTPException(422, "Số máy bảo trì + hỏng vượt số máy được phân bổ")
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
MACHINE_REQUIREMENT_ENABLED = False  # Yêu cầu máy theo mã hàng (style) tạm bỏ: chưa dùng để kiểm tra thiếu máy, chưa tính vào lịch nguồn lực rảnh


class Resources:
    """Ảnh chụp nguồn lực cho một lần Recheck (đọc DB một lần)."""

    def __init__(self, cap_defs=None, labor=None, requirements=None, machines=None, machine_output=None, machine_status=None, as_of: date | None = None, machine_adjust=None):
        self.as_of = as_of or date.today()  # nhân lực chỉ so với các dòng chưa kết thúc tại thời điểm này (số liệu lao động là hiện tại)
        self.cap_defs = cap_defs or []
        self.labor = labor or {}  # (xn, line) -> present
        self.requirements = requirements or {}  # style -> [(type, qty)]
        self.machines = machines or {}  # (xn, line, type) -> qty
        self.machine_output = machine_output or {}  # (xn, line, type) -> pcs/ngày hiệu dụng
        self.machine_status = machine_status or {}  # (xn, line, type) -> OK|MAINTENANCE|DOWN
        self.machine_adjust = machine_adjust or []  # [{key:(xn,line,type), start, end, delta, kind, ref}] — bảo trì theo lịch (âm), mượn máy (âm bên cho, dương bên nhận)

    def machine_qty(self, key: tuple[str, str, str], day: date | None = None) -> int:
        """Số máy sẵn sàng của (xn, chuyền, loại) tại `day` = đã phân bổ (trừ bảo trì/hỏng cố định) ± mượn máy ± bảo trì theo lịch."""
        d = day or self.as_of
        base = self.machines.get(key, 0)
        for a in self.machine_adjust:
            if a["key"] == key and a["start"] <= d <= a["end"]:
                base += a["delta"]
        return max(0, base)

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
    for r in (db.query(MachineRequirement) if MACHINE_REQUIREMENT_ENABLED else []):
        reqs[r.style_cc].append((r.machine_type, r.quantity))
    machines, output, status = {}, {}, {}
    for m in db.query(MachineCapacity).filter(MachineCapacity.status == "ACTIVE"):
        k = (m.factory_code, m.line, m.machine_type)
        machines[k] = machines.get(k, 0) + max(0, m.quantity - m.maintenance_quantity - m.down_quantity)
        status[k] = m.maintenance_status
        if m.nominal_output_per_day:
            output[k] = m.nominal_output_per_day * (m.efficiency or 1.0)
    labor = {k: v["present"] for k, v in latest_labor(db).items()}
    return Resources(load_capacity_defs(db), labor, dict(reqs), machines, output, status, machine_adjust=load_machine_adjust(db))


def check_row_resources(res: Resources, row: dict) -> list[tuple[str, str, str, str]]:
    """Trả [(severity, column, message, rule_code)] cho một dòng Planning.

    Theo LANE ẢO: dòng chạy 4 + 5 được kiểm tra trên cả chuyền 4 và chuyền 5 (không chỉ primary_line):
    năng suất chuẩn = tổng định nghĩa từng chuyền; lao động so với tổng người có mặt của các chuyền; máy theo yêu cầu mã hàng cho TỪNG chuyền.
    """
    out: list[tuple[str, str, str, str]] = []
    xn, style = row.get("factory_code", ""), row.get("style_cc", "")
    lines = row_lines(row)
    where = f"{xn}/{' + '.join(lines)}"
    cap = row.get("capacity")
    defs = [res.capacity_for({**row, "primary_line": ln}, row.get("begin_prod_date")) for ln in lines]
    if defs and all(defs) and cap:
        expected = sum(d["capacity_per_day"] for d in defs)
        if abs(cap - expected) / expected > 0.02:
            out.append(("WARNING", "capacity", f"CAPACITY {cap:,.0f} khác định nghĩa năng suất {expected:,.0f} pcs/ngày (nguồn {defs[0]['source']} v{defs[0]['version']})", "CAPACITY_DEFINITION_MISMATCH"))
    worker = ((row.get("extra") or {}).get("ref") or {}).get("worker")
    known = [res.labor[(xn, ln)] for ln in lines if (xn, ln) in res.labor]
    present = sum(known) if known else None
    end_day = _floor_day(row, "end_prod_date", "end_prod_date")
    still_running = end_day is None or end_day >= res.as_of
    if worker and present is not None and still_running and worker > present:
        out.append(("WARNING", "worker", f"Cần {worker:.0f} lao động nhưng chuyền {where} chỉ có {present} người có mặt (lần đồng bộ gần nhất)", "LABOR_SHORTAGE"))
    cap_per_line = (cap / len(lines)) if cap and lines else None
    day = _floor_day(row, "begin_prod_date", "begin_prod_date") or res.as_of
    for mtype, need in res.requirements.get(style, []):
        for line in lines:
            k = (xn, line, mtype)
            if k not in res.machines:
                continue
            if res.machine_status.get(k) == "DOWN":
                out.append(("WARNING", "line", f"Nhóm máy {mtype} của chuyền {xn}/{line} đang ngừng (DOWN)", "MACHINE_UNAVAILABLE"))
            elif res.machine_qty(k, day) < need:
                out.append(("WARNING", "line", f"Mã {style} cần {need} máy {mtype} nhưng chuyền {xn}/{line} chỉ có {res.machine_qty(k, day)} sẵn sàng" + (f" ngày {day:%d/%m/%Y} (đã trừ bảo trì, cộng/trừ máy mượn)" if any(a["key"] == k for a in res.machine_adjust) else ""), "MACHINE_SHORTAGE"))
            elif k in res.machine_output and cap_per_line and res.machine_output[k] < cap_per_line:
                out.append(("WARNING", "capacity", f"Máy {mtype} của chuyền {xn}/{line} chỉ đạt {res.machine_output[k]:,.0f} pcs/ngày, thấp hơn phần CAPACITY của chuyền {cap_per_line:,.0f} (nút thắt máy)", "MACHINE_BOTTLENECK"))
    return out


# ------------------------------------------------------------------ Lịch nguồn lực rảnh
def _floor_day(row: dict, field: str, serial_key: str) -> date | None:
    serial = ((row.get("extra") or {}).get("serial") or {}).get(serial_key)
    if serial is not None:
        return EXCEL_EPOCH + timedelta(days=int(math.floor(serial)))
    v = row.get(field)
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    return v


def release_schedule(rows: list[dict], week_start: date, requirements: dict[str, list[tuple[str, int]]] | None = None) -> dict:
    """Nguồn lực rảnh trong ngày D của một chuyền = max(0, đang giữ(D−1) − đang giữ(D)).

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
        lines = row_lines(r) or [r["primary_line"]]
        for line in lines:  # giữ nguồn lực trên MỌI chuyền của dòng: nhân công chia đều, mỗi chuyền cần đủ bộ máy theo mã hàng
            key = (r["factory_code"], line)
            for d in span:
                if b <= d <= e:
                    reserved[key][d][0] += worker / len(lines)
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
            "note": "Nguồn lực rảnh = phần nguồn lực được trả lại trong ngày (đang giữ hôm trước trừ đang giữ hôm nay). Máy chỉ tính cho mã hàng có yêu cầu máy."}


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def release_for_version(db: Session, version_id: int, week_start: date) -> dict:
    from app.services.planning_service import get_version, load_rows

    get_version(db, version_id)
    rows = load_rows(db, version_id)
    reqs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in (db.query(MachineRequirement) if MACHINE_REQUIREMENT_ENABLED else []):
        reqs[r.style_cc].append((r.machine_type, r.quantity))
    # bổ sung ref (worker) cho dòng chưa lưu ref theo phiên bản
    from app.services.planning_service import refs_for_rows

    refs = refs_for_rows(db, rows)
    for r in rows:
        if not (r.get("extra") or {}).get("ref") and refs.get(r["row_uid"]):
            r.setdefault("extra", {})["ref"] = refs[r["row_uid"]]
    return release_schedule(rows, week_start, dict(reqs))


# ------------------------------------------------------------------ Cấp 1: Danh mục loại máy
TYPE_FIELDS = ("name", "model", "machine_group", "process", "nominal_output_per_day", "default_efficiency", "changeover_minutes", "is_bottleneck_capable", "effective_from", "effective_to", "note")


def type_view(t: MachineType) -> dict:
    return {"code": t.code, "name": t.name, "source": t.source, "model": t.model, "machine_group": t.machine_group, "process": t.process, "nominal_output_per_day": t.nominal_output_per_day,
            "default_efficiency": t.default_efficiency, "changeover_minutes": t.changeover_minutes, "is_bottleneck_capable": t.is_bottleneck_capable,
            "effective_from": t.effective_from.isoformat() if t.effective_from else None, "effective_to": t.effective_to.isoformat() if t.effective_to else None,
            "status": t.status, "note": t.note, "updated_by": t.updated_by}


def save_machine_type(db: Session, user: User, d: dict, code: str | None = None) -> MachineType:
    if d.get("default_efficiency") is not None and not 0 < float(d["default_efficiency"]) <= 1:
        raise HTTPException(422, "OEE mặc định phải trong khoảng (0, 1]")
    if d.get("effective_from") and d.get("effective_to") and d["effective_from"] > d["effective_to"]:
        raise HTTPException(422, "Hiệu lực từ phải trước hoặc bằng đến")
    if code is None:
        code = (d.get("code") or "").strip().upper()
        if not code:
            raise HTTPException(422, "Cần mã loại máy")
        if db.get(MachineType, code):
            raise HTTPException(409, "Mã loại máy đã tồn tại")
        t = MachineType(code=code, source="MANUAL")
        db.add(t)
        action = "MACHINE_TYPE_CREATE"
    else:
        t = db.get(MachineType, code)
        if t is None:
            raise HTTPException(404, "Không tìm thấy loại máy")
        action = "MACHINE_TYPE_UPDATE"
    for k in TYPE_FIELDS:
        if k in d:
            setattr(t, k, d[k] if d[k] is not None or k in ("nominal_output_per_day", "default_efficiency", "changeover_minutes", "effective_from", "effective_to") else "")
    t.updated_by, t.updated_at = user.username, utcnow()
    db.commit()
    write_audit(action, user=user, object_type="MachineType", object_id=t.code, detail=t.name)
    return t


def set_type_status(db: Session, user: User, code: str, active: bool) -> MachineType:
    t = db.get(MachineType, code)
    if t is None:
        raise HTTPException(404, "Không tìm thấy loại máy")
    t.status, t.updated_by, t.updated_at = ("ACTIVE" if active else "INACTIVE"), user.username, utcnow()
    db.commit()
    write_audit("MACHINE_TYPE_STATUS", user=user, object_type="MachineType", object_id=code, detail=t.status)
    return t


# ------------------------------------------------------------------ Cấp 3: đăng ký mượn máy + lịch bảo trì
def _dates(d: dict) -> None:
    if not d.get("date_from") or not d.get("date_to"):
        raise HTTPException(422, "Cần khoảng ngày (từ – đến)")
    if d["date_from"] > d["date_to"]:
        raise HTTPException(422, "Từ ngày phải trước hoặc bằng đến ngày")


def _known_type(db: Session, code: str) -> None:
    if not db.get(MachineType, code):
        raise HTTPException(422, f"Loại máy {code} chưa có trong danh mục")


def sharing_view(r: MachineSharing) -> dict:
    return {"id": r.id, "machine_type": r.machine_type, "from_factory": r.from_factory, "from_line": r.from_line, "to_factory": r.to_factory, "to_line": r.to_line, "quantity": r.quantity,
            "date_from": r.date_from.isoformat(), "date_to": r.date_to.isoformat(), "reason": r.reason, "status": r.status, "created_by": r.created_by, "status_reason": r.status_reason}


def maint_view(r: MachineMaintenance) -> dict:
    return {"id": r.id, "factory_code": r.factory_code, "line": r.line, "machine_type": r.machine_type, "quantity": r.quantity, "date_from": r.date_from.isoformat(), "date_to": r.date_to.isoformat(),
            "kind": r.kind, "reason": r.reason, "status": r.status, "created_by": r.created_by, "status_reason": r.status_reason}


def _available(db: Session, xn: str, line: str, mtype: str, day: date) -> int:
    """Máy sẵn sàng của một chuyền tại `day` (dùng để không cho mượn vượt số có)."""
    res = Resources(machines={(xn, line, mtype): sum(max(0, c.quantity - c.maintenance_quantity - c.down_quantity) for c in db.query(MachineCapacity).filter(
        MachineCapacity.status == "ACTIVE", MachineCapacity.factory_code == xn, MachineCapacity.line == line, MachineCapacity.machine_type == mtype))},
        machine_adjust=load_machine_adjust(db))
    return res.machine_qty((xn, line, mtype), day)


def save_sharing(db: Session, user: User, d: dict, sid: int | None = None) -> MachineSharing:
    _dates(d)
    if int(d.get("quantity") or 0) < 1:
        raise HTTPException(422, "Số lượng máy phải ≥ 1")
    if not d.get("machine_type") or not d.get("from_factory") or not d.get("to_factory"):
        raise HTTPException(422, "Cần loại máy, xí nghiệp cho mượn và xí nghiệp nhận")
    if d["from_factory"] == d["to_factory"] and (d.get("from_line") or "") == (d.get("to_line") or ""):
        raise HTTPException(422, "Bên cho mượn và bên nhận phải khác nhau")
    _known_type(db, d["machine_type"])
    if d.get("from_line"):
        avail = min(_available(db, d["from_factory"], d["from_line"], d["machine_type"], day) for day in (d["date_from"], d["date_to"]))
        if sid is None and int(d["quantity"]) > avail:
            raise HTTPException(422, f"Chuyền {d['from_factory']}/{d['from_line']} chỉ còn {avail} máy {d['machine_type']} sẵn sàng trong khoảng này")
    fields = ("machine_type", "from_factory", "from_line", "to_factory", "to_line", "quantity", "date_from", "date_to", "reason")
    if sid is None:
        row = MachineSharing(created_by=user.username, **{k: d.get(k, "" if k in ("from_line", "to_line", "reason") else None) for k in fields})
        db.add(row)
        action = "MACHINE_SHARING_CREATE"
    else:
        row = db.get(MachineSharing, sid)
        if row is None:
            raise HTTPException(404, "Không tìm thấy đăng ký mượn máy")
        for k in fields:
            if k in d:
                setattr(row, k, d[k])
        action = "MACHINE_SHARING_UPDATE"
    db.commit()
    write_audit(action, user=user, object_type="MachineSharing", object_id=str(row.id), detail=f"{row.machine_type} x{row.quantity} {row.from_factory}->{row.to_factory}")
    return row


def save_maintenance(db: Session, user: User, d: dict, mid: int | None = None) -> MachineMaintenance:
    _dates(d)
    if int(d.get("quantity") or 0) < 1:
        raise HTTPException(422, "Số lượng máy phải ≥ 1")
    if not d.get("factory_code") or not d.get("line") or not d.get("machine_type"):
        raise HTTPException(422, "Cần xí nghiệp, chuyền và loại máy")
    if d.get("kind", "PLANNED") not in ("PLANNED", "BREAKDOWN", "OTHER"):
        raise HTTPException(422, "Loại bảo trì phải là PLANNED, BREAKDOWN hoặc OTHER")
    _known_type(db, d["machine_type"])
    fields = ("factory_code", "line", "machine_type", "quantity", "date_from", "date_to", "kind", "reason")
    if mid is None:
        row = MachineMaintenance(created_by=user.username, **{k: d[k] for k in fields if k in d})
        db.add(row)
        action = "MACHINE_MAINT_CREATE"
    else:
        row = db.get(MachineMaintenance, mid)
        if row is None:
            raise HTTPException(404, "Không tìm thấy lịch bảo trì")
        for k in fields:
            if k in d:
                setattr(row, k, d[k])
        action = "MACHINE_MAINT_UPDATE"
    db.commit()
    write_audit(action, user=user, object_type="MachineMaintenance", object_id=str(row.id), detail=f"{row.factory_code}/{row.line} {row.machine_type} x{row.quantity}")
    return row


def set_row_status(db: Session, user: User, model, rid: int, active: bool, reason: str = "") -> Any:
    """Ngưng áp dụng / áp dụng lại (không xóa) cho đăng ký mượn máy và lịch bảo trì."""
    row = db.get(model, rid)
    if row is None:
        raise HTTPException(404, "Không tìm thấy bản ghi")
    want = "ACTIVE" if active else "INACTIVE"
    if row.status == want:
        raise HTTPException(409, "Bản ghi đã ở trạng thái này")
    row.status, row.status_changed_by, row.status_reason = want, user.username, (reason or "").strip()[:200]
    db.commit()
    write_audit("MACHINE_STATUS", user=user, object_type=model.__name__, object_id=str(rid), detail=f"{want} {row.status_reason}".strip())
    return row


def load_machine_adjust(db: Session) -> list[dict]:
    """Điều chỉnh số máy theo ngày: bảo trì (âm) và mượn máy (âm bên cho, dương bên nhận) — chỉ bản ghi ACTIVE."""
    out: list[dict] = []
    for r in db.query(MachineSharedPool).filter(MachineSharedPool.status == "ACTIVE"):  # máy dùng chung: mỗi chuyền trong danh sách được dùng tối đa số máy của nhóm
        for ln in r.lines or []:
            out.append({"key": (r.factory_code, str(ln), r.machine_type), "start": r.effective_from or date.min, "end": r.effective_to or date.max, "delta": r.quantity, "kind": "SHARED", "ref": r.id})
    for r in db.query(MachineMaintenance).filter(MachineMaintenance.status == "ACTIVE"):
        out.append({"key": (r.factory_code, r.line, r.machine_type), "start": r.date_from, "end": r.date_to, "delta": -r.quantity, "kind": "MAINTENANCE", "ref": r.id})
    for r in db.query(MachineSharing).filter(MachineSharing.status == "ACTIVE"):
        if r.from_line:
            out.append({"key": (r.from_factory, r.from_line, r.machine_type), "start": r.date_from, "end": r.date_to, "delta": -r.quantity, "kind": "LEND", "ref": r.id})
        if r.to_line:
            out.append({"key": (r.to_factory, r.to_line, r.machine_type), "start": r.date_from, "end": r.date_to, "delta": r.quantity, "kind": "BORROW", "ref": r.id})
    return out


# ------------------------------------------------------------------ Năng suất loại máy theo mã hàng
def style_output_view(r: MachineStyleOutput) -> dict:
    return {"id": r.id, "machine_type": r.machine_type, "style_cc": r.style_cc, "output_per_day": r.output_per_day, "required_quantity": r.required_quantity, "source": r.source, "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "effective_to": r.effective_to.isoformat() if r.effective_to else None, "status": r.status, "note": r.note, "updated_by": r.updated_by or r.created_by}


def save_style_output(db: Session, user: User, d: dict, rid: int | None = None) -> MachineStyleOutput:
    if d.get("effective_from") and d.get("effective_to") and d["effective_from"] > d["effective_to"]:
        raise HTTPException(422, "Hiệu lực từ phải trước hoặc bằng đến")
    if d.get("output_per_day") is not None and not float(d["output_per_day"]) > 0:
        raise HTTPException(422, "Công suất phải > 0")
    if d.get("required_quantity") is not None and int(d["required_quantity"]) < 1:
        raise HTTPException(422, "Số máy cần phải ≥ 1")
    if rid is None:
        code, style = (d.get("machine_type") or "").strip(), (d.get("style_cc") or "").strip().upper()
        if not code or not style or (d.get("output_per_day") is None and d.get("required_quantity") is None):
            raise HTTPException(422, "Cần loại máy, mã hàng và công suất hoặc số máy cần")
        _known_type(db, code)
        if db.query(MachineStyleOutput).filter(MachineStyleOutput.machine_type == code, MachineStyleOutput.style_cc == style, MachineStyleOutput.status == "ACTIVE").first():
            raise HTTPException(409, f"Mã hàng {style} đã có công suất cho loại máy {code} — sửa dòng đó")
        row = MachineStyleOutput(machine_type=code, style_cc=style, output_per_day=(float(d["output_per_day"]) if d.get("output_per_day") is not None else None), required_quantity=d.get("required_quantity"), source=d.get("source", "MANUAL"), effective_from=d.get("effective_from"), effective_to=d.get("effective_to"),
                                 note=d.get("note") or "", created_by=user.username)
        db.add(row)
        action = "MACHINE_STYLE_OUTPUT_CREATE"
    else:
        row = db.get(MachineStyleOutput, rid)
        if row is None:
            raise HTTPException(404, "Không tìm thấy dòng công suất")
        for k in ("output_per_day", "required_quantity", "effective_from", "effective_to", "note"):
            if k in d:
                setattr(row, k, d[k])
        row.updated_by, row.updated_at = user.username, utcnow()
        action = "MACHINE_STYLE_OUTPUT_UPDATE"
    db.commit()
    write_audit(action, user=user, object_type="MachineStyleOutput", object_id=str(row.id), detail=f"{row.machine_type}/{row.style_cc} công suất {row.output_per_day} · cần {row.required_quantity} máy")
    return row


# ------------------------------------------------------------------ Đăng ký dùng chung nhiều chuyền
def pool_view(r: MachineSharedPool) -> dict:
    return {"id": r.id, "factory_code": r.factory_code, "machine_type": r.machine_type, "quantity": r.quantity, "lines": list(r.lines or []), "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "effective_to": r.effective_to.isoformat() if r.effective_to else None, "note": r.note, "status": r.status, "created_by": r.created_by, "status_reason": r.status_reason}


def save_pool(db: Session, user: User, d: dict) -> MachineSharedPool:
    lines = [str(x).strip() for x in d.get("lines") or [] if str(x).strip()]
    if len(set(lines)) != len(lines):
        raise HTTPException(422, "Chuyền bị trùng trong danh sách")
    if len(lines) < 2:
        raise HTTPException(422, "Dùng chung cần từ 2 chuyền trở lên")
    if not d.get("factory_code") or not d.get("machine_type"):
        raise HTTPException(422, "Cần xí nghiệp và loại máy")
    if int(d.get("quantity") or 0) < 1:
        raise HTTPException(422, "Số lượng máy phải ≥ 1")
    if d.get("effective_from") and d.get("effective_to") and d["effective_from"] > d["effective_to"]:
        raise HTTPException(422, "Từ ngày phải trước hoặc bằng đến ngày")
    _known_type(db, d["machine_type"])
    row = MachineSharedPool(factory_code=d["factory_code"], machine_type=d["machine_type"], quantity=int(d["quantity"]), lines=lines, effective_from=d.get("effective_from"),
                            effective_to=d.get("effective_to"), note=d.get("note") or "", created_by=user.username)
    db.add(row)
    db.commit()
    write_audit("MACHINE_SHARED_POOL_CREATE", user=user, object_type="MachineSharedPool", object_id=str(row.id), detail=f"{row.factory_code} {row.machine_type} x{row.quantity} chuyền {','.join(lines)}")
    return row
