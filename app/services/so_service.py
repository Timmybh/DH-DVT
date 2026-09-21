"""SO — danh tính nghiệp vụ bền vững (Master Review Spec §11–16, §48).

Số SO: SO/YY/NNNNNN, sinh tự động, bất biến, không mã hóa XN/PO. Cấp ngay từ Unplanned. PO chỉ là bí danh (PlanningSOExternalIdentity).
"""

import re
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.core import Factory
from app.models.data import PlanImportBatch, PlanRow
from app.models.planning import PlanningVersionRow
from app.models.so import PlanningSO, PlanningSOExternalIdentity, SOSequence
from app.services.audit import write_audit
from app.services.planning_engine import source_key

SO_RE = re.compile(r"^SO/\d{2}/\d{6}$")


def format_so(year2: int, seq: int) -> str:
    return f"SO/{year2 % 100:02d}/{seq:06d}"


def _year2(today=None) -> int:
    if today is None:
        from app.services.dashboard import today_local

        today = today_local()
    return today.year % 100


def next_seq(db: Session, year2: int) -> int:
    """Cấp số kế tiếp trong năm (reset theo năm); khóa dòng bộ đếm để không trùng khi nhiều phiên cùng cấp."""
    row = db.query(SOSequence).filter(SOSequence.year2 == year2).with_for_update().first()
    if row is None:
        row = SOSequence(year2=year2, last_seq=0)
        db.add(row)
        db.flush()
    row.last_seq += 1
    db.flush()
    return row.last_seq


def classify_po(po: str) -> str:
    p = (po or "").strip()
    if re.fullmatch(r"\d{6,}", p):
        return "ERP_PO"
    if p.upper().startswith(("PO_TEMP", "TEMP")):
        return "TEMP_PO"
    return "PLAN_NOTE"  # FCAST WEEK 42, PRE SELECTION, ...


def default_description(customer: str, model: str, description: str, style: str, season: str) -> str:
    """Ví dụ: "NIKE Pegasus / A100 / FW26" — giúp nhận diện SO khi chỉ có số SO thì không đủ."""
    head = " ".join(x for x in ((customer or "").strip(), ((model or "").strip() or (description or "").strip()[:40])) if x)
    return " / ".join(x for x in (head, (style or "").strip(), (season or "").strip()) if x)[:300]


def issue_so(db: Session, *, customer="", style="", model="", season="", sport="", qty=0.0, factory="", po="", note="", description="", source="IMPORT", identity_key="",
             created_by="system", window_from=None, window_to=None, today=None) -> PlanningSO:
    y2 = _year2(today)
    seq = next_seq(db, y2)
    po = (po or "").strip()
    kind = classify_po(po)
    so = PlanningSO(
        so_number=format_so(y2, seq), year2=y2, seq=seq, description=description or default_description(customer, model, "", style, season), customer=customer or "", style_cc=style or "",
        model_code=model or "", season=season or "", sport=sport or "", planned_qty=float(qty or 0), origin_factory=factory or "", current_factory=factory or "", window_from=window_from,
        window_to=window_to, current_po=po if kind == "ERP_PO" else "", temp_po=po if kind == "TEMP_PO" else "", note=(note or (po if kind == "PLAN_NOTE" else ""))[:400], source=source,
        identity_key=identity_key, created_by=created_by,
    )
    db.add(so)
    db.flush()
    if po:
        db.add(PlanningSOExternalIdentity(planning_so_id=so.id, source_system="PLAN", identity_type=kind, identity_value=po[:120], reason="PO/ghi chú trong file kế hoạch khi cấp SO"))
    return so


# --------------------------------------------------------------------------- cấp SO cho Unplanned / Planned
def _ident(pr_like, counter: dict) -> str:
    key = source_key(pr_like.po_number or "", pr_like.style_cc or "", pr_like.model_code or "", pr_like.customer or "", float(pr_like.quantity or 0))
    counter[key] += 1
    return f"{key}#{counter[key]}"


def assign_for_batch(db: Session, batch_id: int, username: str = "system", source: str = "IMPORT") -> dict:
    """Mọi dòng của batch (Unplanned lẫn Planned) đều có SO. Cùng business item (khóa nhận diện) thì dùng lại SO, không cấp lại."""
    fmap = {f.id: f.code for f in db.query(Factory)}
    known = {s.identity_key: s for s in db.query(PlanningSO).filter(PlanningSO.identity_key != "")}
    counter: dict[str, int] = defaultdict(int)
    new = reused = 0
    for pr in db.query(PlanRow).filter(PlanRow.batch_id == batch_id).order_by(PlanRow.id):
        ident = _ident(pr, counter)
        if pr.so_id is not None:
            continue
        so = known.get(ident)
        if so is None:
            so = issue_so(db, customer=pr.customer, style=pr.style_cc, model=pr.model_code, season=pr.season, sport=pr.sport, qty=pr.quantity, factory=fmap.get(pr.factory_id, ""), po=pr.po_number,
                          note=pr.note, description=default_description(pr.customer, pr.model_code, pr.description, pr.style_cc, pr.season), source=source, identity_key=ident, created_by=username,
                          window_from=pr.begin_prod_date, window_to=pr.end_prod_date)
            known[ident] = so
            new += 1
        else:
            reused += 1
        pr.so_id = so.id
    db.flush()
    return {"batch_id": batch_id, "issued": new, "reused": reused}


def backfill_version_rows(db: Session, username: str = "system") -> dict:
    """Dòng phiên bản kế hoạch chưa có SO: dùng lại SO theo row_uid (đã có ở phiên bản khác) → theo dòng nguồn → theo khóa nhận diện (cùng business item với Unplanned/Planned hiện có) → cấp SO mới."""
    uid_so: dict[str, int] = {}
    for uid, so_id in db.query(PlanningVersionRow.row_uid, PlanningVersionRow.so_id).filter(PlanningVersionRow.so_id.isnot(None)):
        uid_so.setdefault(uid, so_id)
    plan_so = {pid: sid for pid, sid in db.query(PlanRow.id, PlanRow.so_id).filter(PlanRow.so_id.isnot(None))}
    known = {s.identity_key: s.id for s in db.query(PlanningSO).filter(PlanningSO.identity_key != "")}
    updates, issued, linked = [], 0, 0
    counters: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in db.query(PlanningVersionRow).order_by(PlanningVersionRow.version_id, PlanningVersionRow.source_plan_row_id, PlanningVersionRow.id):
        key = source_key(r.po_number or "", r.style_cc or "", r.model_code or "", r.customer or "", float(r.quantity or 0))
        counters[r.version_id][key] += 1
        if r.so_id is not None:
            continue
        ident = f"{key}#{counters[r.version_id][key]}"
        so_id = uid_so.get(r.row_uid) or (plan_so.get(r.source_plan_row_id) if r.source_plan_row_id else None) or known.get(ident)
        if so_id is None:
            so = issue_so(db, customer=r.customer, style=r.style_cc, model=r.model_code, season=r.season, sport=r.sport, qty=r.quantity, factory=r.factory_code, po=r.po_number, note=r.note,
                          description=default_description(r.customer, r.model_code, r.description, r.style_cc, r.season), source="BULK_TEMP", identity_key=ident, created_by=username,
                          window_from=r.begin_prod_date, window_to=r.end_prod_date)
            so_id = so.id
            known[ident] = so_id
            issued += 1
        else:
            linked += 1
        uid_so[r.row_uid] = so_id
        updates.append({"id": r.id, "so_id": so_id})
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(PlanningVersionRow, updates[i:i + 2000])
    db.flush()
    return {"rows": len(updates), "linked": linked, "issued": issued}


def bulk_issue_current(db: Session, username: str = "system") -> dict:
    """Cấp SO TẠM hàng loạt cho dữ liệu hiện có (UAT): mọi dòng Unplanned + Planned của batch hiện hành và mọi dòng phiên bản. Chạy lại an toàn (không cấp lại)."""
    batch = db.query(PlanImportBatch).filter(PlanImportBatch.is_current.is_(True)).order_by(PlanImportBatch.id.desc()).first()
    out = {"plan_rows": None, "version_rows": None}
    if batch is not None:
        out["plan_rows"] = assign_for_batch(db, batch.id, username, "BULK_TEMP")
    out["version_rows"] = backfill_version_rows(db, username)
    db.commit()
    if out["plan_rows"] and (out["plan_rows"]["issued"] or (out["version_rows"] or {}).get("issued")):
        write_audit("SO_BULK_ISSUE", username=username, object_type="PlanningSO", detail=str(out))
    return out


# --------------------------------------------------------------------------- hiển thị
def attach_so(db: Session, dicts: list[dict]) -> list[dict]:
    """Gắn so_number / so_description cho các dòng (dict có so_id) — chỉ đọc."""
    ids = {d.get("so_id") for d in dicts if d.get("so_id")}
    if not ids:
        return dicts
    info = {i: (n, ds) for i, n, ds in db.query(PlanningSO.id, PlanningSO.so_number, PlanningSO.description).filter(PlanningSO.id.in_(ids))}
    for d in dicts:
        n = info.get(d.get("so_id"))
        if n:
            d["so_number"], d["so_description"] = n
    return dicts


def so_view(s: PlanningSO) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"id": s.id, "so_number": s.so_number, "description": s.description, "customer": s.customer, "style_cc": s.style_cc, "model_code": s.model_code, "season": s.season, "sport": s.sport,
            "planned_qty": s.planned_qty, "origin_factory": s.origin_factory, "current_factory": s.current_factory, "window_from": iso(s.window_from), "window_to": iso(s.window_to),
            "current_po": s.current_po, "temp_po": s.temp_po, "status": s.status, "note": s.note, "source": s.source, "created_at": iso(s.created_at), "created_by": s.created_by}


def list_sos(db: Session, q: str = "", factory: str = "", status: str = "", limit: int = 100, offset: int = 0) -> dict:
    query = db.query(PlanningSO)
    if q.strip():
        like = f"%{q.strip()}%"
        alias = db.query(PlanningSOExternalIdentity.planning_so_id).filter(PlanningSOExternalIdentity.identity_value.ilike(like))
        query = query.filter(or_(PlanningSO.so_number.ilike(like), PlanningSO.description.ilike(like), PlanningSO.customer.ilike(like), PlanningSO.style_cc.ilike(like),
                                 PlanningSO.model_code.ilike(like), PlanningSO.id.in_(alias)))
    if factory:
        query = query.filter(PlanningSO.current_factory == factory)
    if status:
        query = query.filter(PlanningSO.status == status)
    total = query.count()
    rows = query.order_by(PlanningSO.year2.desc(), PlanningSO.seq.desc()).offset(offset).limit(limit).all()
    return {"total": total, "rows": [so_view(s) for s in rows]}


def so_detail(db: Session, so_id: int) -> dict:
    s = db.get(PlanningSO, so_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy SO")
    ids = db.query(PlanningSOExternalIdentity).filter(PlanningSOExternalIdentity.planning_so_id == so_id).order_by(PlanningSOExternalIdentity.id).all()
    return {**so_view(s), "identities": [{"id": i.id, "type": i.identity_type, "value": i.identity_value, "source_system": i.source_system, "status": i.status, "reason": i.reason} for i in ids],
            "unplanned_rows": db.query(PlanRow).filter(PlanRow.so_id == so_id).count(), "version_rows": db.query(PlanningVersionRow).filter(PlanningVersionRow.so_id == so_id).count()}


def update_description(db: Session, so_id: int, description: str, user) -> PlanningSO:
    """Chỉ SO Description được chỉnh; SO Number, XN, PO không sửa trực tiếp (bất biến / có sổ cái riêng)."""
    s = db.get(PlanningSO, so_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy SO")
    description = (description or "").strip()
    if not description or len(description) > 300:
        raise HTTPException(422, "SO Description 1–300 ký tự")
    old, s.description = s.description, description
    db.commit()
    write_audit("SO_DESCRIPTION", user=user, object_type="PlanningSO", object_id=s.so_number, detail=f"'{old}' -> '{description}'")
    return s
