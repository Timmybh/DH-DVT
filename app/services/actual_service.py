"""Phase 5 — Actual / Mapping (handoff §25, §26, §28).

- Khóa nghiệp vụ ổn định (fingerprint): PO + Style/CC + Khách hàng đã chuẩn hóa. KHÔNG dùng ID nội bộ eGMF, KHÔNG dùng số lượng.
- Lịch sử thực tế: mỗi lần đồng bộ chỉ ghi quan sát MỚI hoặc THAY ĐỔI; trạng thái tại lần chạy N dựng lại được.
- Mapping Actual -> dòng kế hoạch: tự động theo độ tin cậy, người dùng xác nhận / sửa tay / bỏ qua; mapping tay không bị đồng bộ ghi đè.
- Plan-vs-Actual: may xong và nhập kho thành phẩm là hai mốc hoàn thành tách biệt.
"""

import re
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.actual import ActualMapping, ActualMappingHistory, ActualObservation
from app.models.planning import PlanningVersion, PlanningVersionRow

TRACKED = ("qty", "sewn_qty", "fg_qty", "due_date", "sewn_done_date", "fg_done_date", "customer", "style")


# --------------------------------------------------------------------------- khóa nghiệp vụ
def norm(value) -> str:
    """Chuẩn hóa để so khớp: hoa, bỏ khoảng trắng thừa, bỏ đuôi ".0" do Excel/số."""
    s = re.sub(r"\s+", " ", str(value if value is not None else "")).strip().upper()
    return re.sub(r"\.0+$", "", s)


def fingerprint(po, style, customer) -> str:
    return "|".join([norm(po), norm(style), norm(customer)])


def actual_key(po, factory_code, line) -> str:
    return "|".join([norm(po), norm(factory_code), norm(line)])


# --------------------------------------------------------------------------- quan sát / lịch sử
def diff_observation(prev: dict | None, cur: dict) -> dict:
    """{} = không đổi. Quan sát đầu tiên -> {"_new": True}. Ngược lại {trường: [cũ, mới]}."""
    if prev is None:
        return {"_new": True}
    out = {}
    for f in TRACKED:
        a, b = prev.get(f), cur.get(f)
        if isinstance(a, (date, datetime)):
            a = a.isoformat()
        if isinstance(b, (date, datetime)):
            b = b.isoformat()
        if (a or None) != (b or None):
            out[f] = [a, b]
    return out


def _obs_dict(o: ActualObservation) -> dict:
    return {
        "id": o.id, "actual_key": o.actual_key, "fingerprint": o.fingerprint, "sync_run_id": o.sync_run_id, "observed_at": o.observed_at.isoformat() if o.observed_at else None,
        "po": o.po, "style": o.style, "customer": o.customer, "factory_code": o.factory_code, "line": o.line, "qty": o.qty, "sewn_qty": o.sewn_qty, "fg_qty": o.fg_qty,
        "due_date": o.due_date.isoformat() if o.due_date else None, "sewn_done_date": o.sewn_done_date.isoformat() if o.sewn_done_date else None,
        "fg_done_date": o.fg_done_date.isoformat() if o.fg_done_date else None, "last_seen": o.last_seen.isoformat() if o.last_seen else None,
        "is_new": o.is_new, "changes": o.changes or {},
    }


def latest_observations(db: Session, upto_run_id: int | None = None) -> list[ActualObservation]:
    """Trạng thái mới nhất của từng khóa (hoặc trạng thái tại lần đồng bộ `upto_run_id`)."""
    q = db.query(ActualObservation.actual_key, func.max(ActualObservation.sync_run_id).label("m"))
    if upto_run_id is not None:
        q = q.filter(ActualObservation.sync_run_id <= upto_run_id)
    sub = q.group_by(ActualObservation.actual_key).subquery()
    return db.query(ActualObservation).join(sub, and_(ActualObservation.actual_key == sub.c.actual_key, ActualObservation.sync_run_id == sub.c.m)).all()


def record_observations(db: Session, run_id: int, rows: list[dict], source_ref: str = "Report_BaoCaoMayRa") -> dict:
    """rows: dict có po, style, customer, factory_code, line + qty/sewn_qty/fg_qty/due_date/sewn_done_date/fg_done_date/last_seen.
    Chỉ ghi khi mới hoặc thay đổi so với quan sát gần nhất (không ghi đè lịch sử)."""
    latest = {o.actual_key: o for o in latest_observations(db)}
    have_this_run = {k for (k,) in db.query(ActualObservation.actual_key).filter(ActualObservation.sync_run_id == run_id)}
    new = changed = unchanged = 0
    seen: set[str] = set()
    for r in rows:
        key = actual_key(r["po"], r["factory_code"], r["line"])
        if key in seen or key in have_this_run:
            continue
        seen.add(key)
        prev = latest.get(key)
        ch = diff_observation(_obs_dict(prev) if prev else None, r)
        if prev is not None and not ch:
            unchanged += 1
            continue
        db.add(ActualObservation(
            actual_key=key, fingerprint=fingerprint(r["po"], r.get("style"), r.get("customer")), sync_run_id=run_id, source_ref=source_ref,
            po=str(r["po"]).strip(), style=(r.get("style") or "").strip(), customer=(r.get("customer") or "").strip(), factory_code=r["factory_code"], line=str(r["line"]).strip(),
            qty=int(r.get("qty") or 0), sewn_qty=int(r.get("sewn_qty") or 0), fg_qty=int(r.get("fg_qty") or 0), due_date=r.get("due_date"),
            sewn_done_date=r.get("sewn_done_date"), fg_done_date=r.get("fg_done_date"), last_seen=r.get("last_seen"), is_new=prev is None, changes=ch,
        ))
        if prev is None:
            new += 1
        else:
            changed += 1
    db.flush()
    return {"new": new, "changed": changed, "unchanged": unchanged, "keys": len(seen)}


# --------------------------------------------------------------------------- mapping
CONF_FULL, CONF_STYLE, CONF_PO = 1.0, 0.9, 0.7


CONF_STYLE_WINDOW = 0.6
WINDOW_TOLERANCE_DAYS = 14  # thực tế lệch cửa sổ kế hoạch <= 14 ngày vẫn gán (độ tin cậy thấp), xa hơn -> cần xem lại


def _ref_date(actual: dict) -> date | None:
    for k in ("last_seen", "sewn_done_date", "fg_done_date", "due_date"):
        v = actual.get(k)
        if isinstance(v, str):
            v = date.fromisoformat(v)
        if v:
            return v
    return None


def _window_gap(row: dict, ref: date) -> int:
    lo = row.get("begin_prod_date") or row.get("end_prod_date")
    hi = row.get("end_prod_date") or row.get("begin_prod_date")
    if lo is None or hi is None:
        return 10**6
    return 0 if lo <= ref <= hi else min(abs((ref - lo).days), abs((ref - hi).days))


def match_by_style(actual: dict, style_rows: list[dict], horizon_start: date | None) -> dict:
    """Kế hoạch hiện tại phần lớn là dòng dự báo (FCAST WEEK.., PRE SELECTION) không có PO thật -> khớp theo Style/CC + xí nghiệp + chuyền + cửa sổ thời gian."""
    out = {"status": "UNMATCHED", "method": "AUTO_STYLE_WINDOW", "confidence": 0.0, "reason": "", "row_uid": None, "candidates": []}
    ref = _ref_date(actual)
    if horizon_start and ref and ref < horizon_start:
        out.update(status="OUT_OF_PLAN", method="", reason=f"Thực tế cuối {ref:%d/%m/%Y} thuộc kỳ trước kế hoạch hiện hành (từ {horizon_start:%d/%m/%Y})")
        return out
    if not style_rows:
        out["method"] = ""
        out["reason"] = "PO và Style/CC không có trong kế hoạch"
        return out
    fac = norm(actual.get("factory_code"))
    line = norm(actual.get("line"))
    same_fac = [r for r in style_rows if norm(r["factory_code"]) == fac]
    if not same_fac:
        out.update(status="REVIEW", confidence=0.2, candidates=[r["row_uid"] for r in style_rows][:20],
                   reason=f"Style/CC có trong kế hoạch nhưng ở xí nghiệp khác ({', '.join(sorted({r['factory_code'] for r in style_rows}))})")
        return out
    on_line = [r for r in same_fac if line in {norm(x) for x in (r.get("line_assignments") or [r.get("primary_line")])} or norm(r.get("primary_line")) == line]
    pool, on_line_ok = (on_line, True) if on_line else (same_fac, False)
    if ref is None:
        out.update(status="REVIEW", confidence=0.3, candidates=[r["row_uid"] for r in pool][:20], reason="Thực tế không có ngày tham chiếu để chọn dòng kế hoạch")
        return out
    ranked = sorted(pool, key=lambda r: (_window_gap(r, ref), r.get("sequence", 0)))
    best = ranked[0]
    gap = _window_gap(best, ref)
    tied = [r for r in ranked if _window_gap(r, ref) == gap]
    if on_line_ok:
        # Khớp đủ khóa nghiệp vụ: cùng xí nghiệp + chuyền + Style/CC (ERP đã có XN/chuyền/mã hàng) -> liên kết luôn dòng kế hoạch gần ngày nhất;
        # nhiều dòng cùng khóa thì lấy dòng gần ngày nhất (hòa thì dòng đứng trước), ghi chú để người dùng rà lại khi cần.
        notes = []
        if gap:
            notes.append(f"chọn dòng gần nhất, lệch {gap} ngày")
        if len(tied) > 1:
            notes.append(f"{len(tied)} dòng cùng khóa, lấy dòng đứng trước")
        out.update(status="MATCHED", row_uid=best["row_uid"], confidence=CONF_STYLE_WINDOW - (0.1 if notes else 0), candidates=[r["row_uid"] for r in ranked[:5]] if notes else [])
        out["reason"] = "Khớp XN + chuyền + Style/CC" + ("; " + "; ".join(notes) if notes else "")
        return out
    if gap > WINDOW_TOLERANCE_DAYS:
        out.update(status="REVIEW", confidence=0.3, candidates=[r["row_uid"] for r in ranked[:5]], reason=f"Không có dòng kế hoạch trong ±{WINDOW_TOLERANCE_DAYS} ngày quanh {ref:%d/%m/%Y}")
        return out
    if len(tied) > 1:
        out.update(status="REVIEW", confidence=0.4, candidates=[r["row_uid"] for r in tied][:20], reason=f"{len(tied)} dòng kế hoạch cùng Style/chuyền/thời gian — cần chọn dòng tương ứng")
        return out
    notes = []
    if not on_line_ok:
        notes.append(f"chuyền thực tế {actual.get('line')} khác chuyền kế hoạch ({best.get('primary_line')})")
    if gap:
        notes.append(f"lệch cửa sổ {gap} ngày")
    out.update(row_uid=best["row_uid"], confidence=CONF_STYLE_WINDOW - (0.2 if not on_line_ok else 0) - (0.1 if gap else 0), candidates=[best["row_uid"]] if notes else [])
    out["status"] = "REVIEW" if notes else "MATCHED"
    out["reason"] = "Khớp theo Style/CC + xí nghiệp + chuyền + thời gian" + ("; " + "; ".join(notes) if notes else "")
    return out


def match_actual(actual: dict, plan_rows: list[dict], style_rows: list[dict] | None = None, horizon_start: date | None = None) -> dict:
    """plan_rows: các dòng kế hoạch CÙNG PO (đã lọc theo PO chuẩn hóa). Không có -> khớp theo Style (style_rows).
    Trả {status, method, confidence, reason, row_uid, candidates}."""
    if not plan_rows:
        return match_by_style(actual, style_rows or [], horizon_start)
    out = {"status": "UNMATCHED", "method": "", "confidence": 0.0, "reason": "", "row_uid": None, "candidates": []}

    cands, method, conf, notes = plan_rows, "AUTO_PO", CONF_PO, []
    style = norm(actual.get("style"))
    by_style = [r for r in cands if norm(r.get("style_cc")) == style] if style else []
    if by_style:
        cands, method, conf = by_style, "AUTO_STYLE", CONF_STYLE
        cust = norm(actual.get("customer"))
        by_cust = [r for r in cands if norm(r.get("customer")) == cust] if cust else []
        if by_cust:
            cands, method, conf = by_cust, "AUTO_FULL", CONF_FULL
    elif style:
        notes.append("Style/CC khác kế hoạch")

    fac = norm(actual.get("factory_code"))
    same_fac = [r for r in cands if norm(r["factory_code"]) == fac]
    if not same_fac:
        out.update(status="REVIEW", method=method, confidence=round(conf - 0.4, 2), candidates=[r["row_uid"] for r in cands][:20],
                   reason=f"PO có trong kế hoạch nhưng ở xí nghiệp khác ({', '.join(sorted({r['factory_code'] for r in cands}))}) — thực tế chạy ở {actual.get('factory_code')}")
        if len(cands) == 1:
            out["row_uid"] = cands[0]["row_uid"]
        return out

    line = norm(actual.get("line"))
    on_line = [r for r in same_fac if line in {norm(x) for x in (r.get("line_assignments") or [r.get("primary_line")])} or norm(r.get("primary_line")) == line]
    if len(on_line) == 1:
        r = on_line[0]
        out.update(status="MATCHED" if not notes else "REVIEW", method=method, confidence=conf, row_uid=r["row_uid"], reason="; ".join(notes) or "Khớp PO / xí nghiệp / chuyền")
        if notes:
            out["candidates"] = [r["row_uid"]]
        return out
    if len(on_line) > 1:
        out.update(status="REVIEW", method=method, confidence=round(conf - 0.2, 2), candidates=[r["row_uid"] for r in on_line][:20],
                   reason=f"{len(on_line)} dòng kế hoạch cùng PO và chuyền — cần chọn dòng tương ứng")
        return out
    # cùng PO + xí nghiệp nhưng chuyền thực tế khác chuyền kế hoạch
    if len(same_fac) == 1:
        r = same_fac[0]
        out.update(status="REVIEW", method=method, confidence=round(conf - 0.1, 2), row_uid=r["row_uid"], candidates=[r["row_uid"]],
                   reason=f"Chuyền thực tế {actual.get('line')} khác chuyền kế hoạch ({r.get('primary_line')})" + ("; " + "; ".join(notes) if notes else ""))
        return out
    out.update(status="REVIEW", method=method, confidence=round(conf - 0.3, 2), candidates=[r["row_uid"] for r in same_fac][:20],
               reason=f"{len(same_fac)} dòng kế hoạch cùng PO/xí nghiệp, không dòng nào chạy chuyền {actual.get('line')}")
    return out


def reference_version(db: Session) -> PlanningVersion | None:
    """Phiên bản dùng để đối soát: bản ISSUED mới nhất, nếu chưa có thì bản mới nhất."""
    v = db.query(PlanningVersion).filter(PlanningVersion.status == "ISSUED").order_by(PlanningVersion.id.desc()).first()
    return v or db.query(PlanningVersion).order_by(PlanningVersion.id.desc()).first()


def _plan_rows(db: Session, version_id: int) -> list[dict]:
    return [
        {"row_uid": r.row_uid, "source_key": r.source_key, "po_number": r.po_number, "style_cc": r.style_cc, "customer": r.customer, "factory_code": r.factory_code,
         "primary_line": r.primary_line, "line_assignments": r.line_assignments or [], "quantity": r.quantity, "end_prod_date": r.end_prod_date, "warehouse_date": r.warehouse_date,
         "begin_prod_date": r.begin_prod_date, "line_raw": r.line_raw, "description": r.description, "sequence": r.sequence, "so_id": r.so_id}
        for r in db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == version_id)
    ]


def _apply(m: ActualMapping, res: dict, version_id: int | None, rows_by_uid: dict[str, dict], who: str) -> None:
    m.status, m.method, m.confidence, m.reason, m.candidates = res["status"], res["method"], res["confidence"], res["reason"], res["candidates"]
    m.mapped_row_uid = res["row_uid"]
    m.mapped_so_id = rows_by_uid[res["row_uid"]].get("so_id") if res["row_uid"] in rows_by_uid else None
    m.mapped_version_id = version_id if res["row_uid"] else None
    m.mapped_source_key = rows_by_uid[res["row_uid"]]["source_key"] if res["row_uid"] in rows_by_uid else ""
    m.reconciled_at, m.reconciled_by = utcnow(), who


def reconcile(db: Session, who: str = "system") -> dict:
    """Khớp lại toàn bộ thực tế mới nhất với phiên bản tham chiếu. Mapping TAY và IGNORED được giữ nguyên (chỉ cập nhật ảnh chụp nguồn)."""
    ver = reference_version(db)
    obs = latest_observations(db)
    plan = _plan_rows(db, ver.id) if ver else []
    by_po: dict[str, list[dict]] = defaultdict(list)
    by_style: dict[str, list[dict]] = defaultdict(list)
    for r in plan:
        by_po[norm(r["po_number"])].append(r)
        by_style[norm(r["style_cc"])].append(r)
    starts = [d for r in plan for d in (r.get("begin_prod_date") or r.get("end_prod_date"),) if d]
    horizon = min(starts) if starts else None
    rows_by_uid = {r["row_uid"]: r for r in plan}
    existing = {m.actual_key: m for m in db.query(ActualMapping)}
    counts: dict[str, int] = defaultdict(int)
    for o in obs:
        snap = _obs_dict(o)
        m = existing.get(o.actual_key)
        if m is None:
            m = ActualMapping(actual_key=o.actual_key, source_system="EGMF", source_id=o.source_ref)
            db.add(m)
            existing[o.actual_key] = m
        m.fingerprint, m.po, m.style, m.customer, m.factory_code, m.line = o.fingerprint, o.po, o.style, o.customer, o.factory_code, o.line
        m.attrs = {k: snap[k] for k in ("qty", "sewn_qty", "fg_qty", "due_date", "sewn_done_date", "fg_done_date", "last_seen")}
        m.source_snapshot = snap
        if m.method == "MANUAL":
            if m.mapped_row_uid in rows_by_uid:
                m.mapped_version_id = ver.id if ver else None
                m.mapped_source_key = rows_by_uid[m.mapped_row_uid]["source_key"]
            else:  # dòng đã được đặt tay không còn trong phiên bản tham chiếu -> cần xác nhận lại
                m.status, m.reason = "REVIEW", "Dòng kế hoạch đã chọn tay không còn trong phiên bản tham chiếu"
        elif m.method != "IGNORED":
            _apply(m, match_actual(snap, by_po.get(norm(o.po), []), by_style.get(norm(o.style), []), horizon), ver.id if ver else None, rows_by_uid, who)
        counts[m.status] += 1
    db.flush()
    return {"version": ver.code if ver else None, "version_id": ver.id if ver else None, "actuals": len(obs), **{k: counts.get(k, 0) for k in ("MATCHED", "REVIEW", "UNMATCHED", "OUT_OF_PLAN", "IGNORED")}, "horizon_start": horizon.isoformat() if horizon else None}


def record_and_reconcile(db: Session, run_id: int, rows: list[dict]) -> dict:
    rec = record_observations(db, run_id, rows)
    return {**rec, **reconcile(db, "sync")}


def _need_reason(reason: str) -> str:
    r = (reason or "").strip()
    if len(r) < 3:
        raise ValueError("Cần nhập lý do (tối thiểu 3 ký tự)")
    return r[:300]


def _log(db: Session, m: ActualMapping, action: str, old: tuple, reason: str, who: str) -> None:
    db.add(ActualMappingHistory(mapping_id=m.id, action=action, old_row_uid=old[0], new_row_uid=m.mapped_row_uid, old_so_id=old[1], new_so_id=m.mapped_so_id,
                                old_status=old[2], new_status=m.status, reason=reason, changed_by=who))


def _snap(m: ActualMapping) -> tuple:
    return (m.mapped_row_uid, m.mapped_so_id, m.status)


def set_manual(db: Session, mapping_id: int, row_uid: str, who: str, reason: str = "") -> ActualMapping:
    """Gán tay vào BẤT KỲ dòng kế hoạch của phiên bản tham chiếu (không còn ép cùng PO — PO chỉ là một tín hiệu; spec §29). Bắt buộc có lý do, lưu lịch sử."""
    m = db.get(ActualMapping, mapping_id)
    if m is None:
        raise LookupError("Không có bản ghi mapping")
    reason = _need_reason(reason)
    ver = reference_version(db)
    row = db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == (ver.id if ver else -1), PlanningVersionRow.row_uid == row_uid).first()
    if row is None:
        raise ValueError("Dòng kế hoạch không thuộc phiên bản tham chiếu")
    old = _snap(m)
    m.status, m.method, m.confidence, m.reason, m.candidates = "MATCHED", "MANUAL", 1.0, f"Gán tay bởi {who}: {reason}", []
    m.mapped_row_uid, m.mapped_version_id, m.mapped_source_key, m.mapped_so_id = row_uid, ver.id, row.source_key, row.so_id
    m.reconciled_at, m.reconciled_by = utcnow(), who
    _log(db, m, "MAP", old, reason, who)
    return m


def set_ignored(db: Session, mapping_id: int, who: str, reason: str) -> ActualMapping:
    m = db.get(ActualMapping, mapping_id)
    if m is None:
        raise LookupError("Không có bản ghi mapping")
    reason = _need_reason(reason)
    old = _snap(m)
    m.status, m.method, m.confidence, m.reason, m.candidates = "IGNORED", "IGNORED", 0.0, f"Loại khỏi mapping bởi {who}: {reason}", []
    m.mapped_row_uid, m.mapped_version_id, m.mapped_source_key, m.mapped_so_id = None, None, "", None
    m.reconciled_at, m.reconciled_by = utcnow(), who
    _log(db, m, "IGNORE", old, reason, who)
    return m


def reset_mapping(db: Session, mapping_id: int, who: str = "", reason: str = "") -> ActualMapping:
    """Bỏ mapping tay / bỏ qua để lần đối soát sau tự khớp lại."""
    m = db.get(ActualMapping, mapping_id)
    if m is None:
        raise LookupError("Không có bản ghi mapping")
    reason = _need_reason(reason)
    old = _snap(m)
    m.method, m.status, m.mapped_row_uid, m.mapped_so_id, m.reason = "", "UNMATCHED", None, None, "Đã bỏ mapping tay — chờ đối soát lại"
    _log(db, m, "RESET", old, reason, who)
    return m


def mapping_history(db: Session, mapping_id: int) -> list[dict]:
    rows = db.query(ActualMappingHistory).filter(ActualMappingHistory.mapping_id == mapping_id).order_by(ActualMappingHistory.id.desc()).all()
    return [{"id": h.id, "action": h.action, "old_row_uid": h.old_row_uid, "new_row_uid": h.new_row_uid, "old_so_id": h.old_so_id, "new_so_id": h.new_so_id, "old_status": h.old_status,
             "new_status": h.new_status, "reason": h.reason, "changed_by": h.changed_by, "changed_at": h.changed_at.isoformat() if h.changed_at else None} for h in rows]


def match_grade(m: ActualMapping) -> str:
    """Nhãn gợi ý thay cho % tin cậy (spec §30): EXACT | STRONG | POSSIBLE | CONFIRM."""
    if m.status == "MATCHED":
        return "EXACT" if m.method in ("AUTO_FULL", "MANUAL") else "STRONG"
    if m.status == "REVIEW":
        return "POSSIBLE" if (m.confidence or 0) >= 0.3 else "CONFIRM"
    return "CONFIRM" if m.status == "UNMATCHED" else ""


def candidate_rows(db: Session, m: ActualMapping, q: str = "", limit: int = 60) -> list[dict]:
    """Ứng viên gán tay: tìm theo PO/Style/Customer/SO trong phiên bản tham chiếu, kèm lý do gợi ý (✓ cùng Style/Customer/XN/chuyền, chênh ngày)."""
    from app.models.so import PlanningSO

    ver = reference_version(db)
    if ver is None:
        return []
    qs = db.query(PlanningVersionRow).filter(PlanningVersionRow.version_id == ver.id)
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        so_ids = [x for (x,) in db.query(PlanningSO.id).filter(PlanningSO.so_number.ilike(like) | PlanningSO.description.ilike(like)).limit(500)]
        cond = PlanningVersionRow.po_number.ilike(like) | PlanningVersionRow.style_cc.ilike(like) | PlanningVersionRow.customer.ilike(like)
        if so_ids:
            cond = cond | PlanningVersionRow.so_id.in_(so_ids)
        qs = qs.filter(cond)
    else:
        # Không gõ gì: gợi ý theo PO / Style / Customer của thực tế
        cond = None
        for col, val in ((PlanningVersionRow.po_number, m.po), (PlanningVersionRow.style_cc, m.style)):
            if val:
                c = func.upper(col) == norm(val)
                cond = c if cond is None else (cond | c)
        if cond is None:
            return []
        qs = qs.filter(cond)
    ref = _ref_date(m.attrs or {})
    out = []
    for r in qs.limit(400).all():
        why = []
        if norm(r.po_number) == norm(m.po) and m.po:
            why.append("Cùng PO")
        if norm(r.style_cc) == norm(m.style) and m.style:
            why.append("Cùng Style")
        if norm(r.customer) == norm(m.customer) and m.customer:
            why.append("Cùng Customer")
        if r.factory_code == m.factory_code:
            why.append("Cùng XN")
        if str(r.primary_line or "") == str(m.line or ""):
            why.append("Cùng chuyền")
        gap = None
        if ref and r.begin_prod_date and r.end_prod_date:
            gap = 0 if r.begin_prod_date <= ref <= r.end_prod_date else min(abs((ref - r.begin_prod_date).days), abs((ref - r.end_prod_date).days))
        out.append({"row_uid": r.row_uid, "po": r.po_number, "style": r.style_cc, "customer": r.customer, "factory_code": r.factory_code, "line": r.line_raw or r.primary_line, "quantity": r.quantity,
                    "begin": r.begin_prod_date.isoformat() if r.begin_prod_date else None, "end": r.end_prod_date.isoformat() if r.end_prod_date else None,
                    "so_id": r.so_id, "reasons": why, "date_gap_days": gap})
    out.sort(key=lambda x: (-len(x["reasons"]), x["date_gap_days"] if x["date_gap_days"] is not None else 10**6))
    return out[:limit]


# --------------------------------------------------------------------------- Plan vs Actual
def plan_row_status(planned_qty: float, sewn: int, fg: int, has_actual: bool, planned_end: date | None, sewn_done: date | None, fg_done: date | None, planned_wh: date | None, today: date) -> dict:
    """Hai mốc hoàn thành tách biệt: may xong (SEWN) và nhập kho thành phẩm (FG). Trễ tính theo số lượng thực tế, không chỉ ngày kế hoạch."""
    if not has_actual:
        status = "NO_ACTUAL"
    elif planned_qty > 0 and fg >= planned_qty:
        status = "FG_COMPLETE"
    elif planned_qty > 0 and sewn >= planned_qty:
        status = "SEWN_COMPLETE"
    elif sewn > 0 or fg > 0:
        status = "IN_PROGRESS"
    else:
        status = "NOT_STARTED"
    sewn_delay = (sewn_done - planned_end).days if sewn_done and planned_end else None
    fg_delay = (fg_done - planned_wh).days if fg_done and planned_wh else None
    overdue = bool(planned_end and planned_end < today and status in ("NO_ACTUAL", "NOT_STARTED", "IN_PROGRESS"))
    return {
        "status": status, "sewn_pct": round(min(sewn / planned_qty, 9.99) * 100, 1) if planned_qty else None, "fg_pct": round(min(fg / planned_qty, 9.99) * 100, 1) if planned_qty else None,
        "sewn_delay_days": sewn_delay, "fg_delay_days": fg_delay, "overdue": overdue,
    }


def plan_vs_actual(db: Session, today: date, version_id: int | None = None) -> dict:
    ver = db.get(PlanningVersion, version_id) if version_id else reference_version(db)
    if ver is None:
        return {"version": None, "rows": [], "unmapped": 0}
    plan = _plan_rows(db, ver.id)
    maps = defaultdict(list)
    for m in db.query(ActualMapping).filter(ActualMapping.mapped_row_uid.isnot(None), ActualMapping.status.in_(("MATCHED", "REVIEW"))):
        maps[m.mapped_row_uid].append(m)
    out = []
    for r in plan:
        ms = maps.get(r["row_uid"], [])
        sewn = sum(int((m.attrs or {}).get("sewn_qty") or 0) for m in ms)
        fg = sum(int((m.attrs or {}).get("fg_qty") or 0) for m in ms)
        pick = lambda k: max((date.fromisoformat(m.attrs[k]) for m in ms if (m.attrs or {}).get(k)), default=None)  # noqa: E731
        sewn_done, fg_done = pick("sewn_done_date"), pick("fg_done_date")
        st = plan_row_status(r["quantity"] or 0, sewn, fg, bool(ms), r["end_prod_date"], sewn_done, fg_done, r["warehouse_date"], today)
        out.append({
            "row_uid": r["row_uid"], "po": r["po_number"], "style": r["style_cc"], "customer": r["customer"], "factory_code": r["factory_code"], "line": r["line_raw"] or r["primary_line"],
            "planned_qty": r["quantity"], "sewn_qty": sewn, "fg_qty": fg, "planned_end": r["end_prod_date"].isoformat() if r["end_prod_date"] else None,
            "planned_warehouse": r["warehouse_date"].isoformat() if r["warehouse_date"] else None, "sewn_done_date": sewn_done.isoformat() if sewn_done else None,
            "fg_done_date": fg_done.isoformat() if fg_done else None, "mappings": len(ms), "review": any(m.status == "REVIEW" for m in ms), **st,
        })
    return {"version": {"id": ver.id, "code": ver.code, "status": ver.status}, "rows": out}


# --------------------------------------------------------------------------- truy vấn lịch sử
def history(db: Session, po: str, factory: str | None = None, line: str | None = None) -> list[dict]:
    q = db.query(ActualObservation).filter(func.upper(ActualObservation.po) == norm(po))
    if factory:
        q = q.filter(ActualObservation.factory_code == factory)
    if line:
        q = q.filter(ActualObservation.line == line)
    return [_obs_dict(o) for o in q.order_by(ActualObservation.actual_key, ActualObservation.sync_run_id)]


def run_changes(db: Session, run_id: int, limit: int = 500) -> dict:
    q = db.query(ActualObservation).filter(ActualObservation.sync_run_id == run_id)
    total = q.count()
    return {"run_id": run_id, "total": total, "new": q.filter(ActualObservation.is_new.is_(True)).count(), "rows": [_obs_dict(o) for o in q.order_by(ActualObservation.po).limit(limit)]}


def state_at(db: Session, run_id: int, po: str | None = None) -> list[dict]:
    rows = [_obs_dict(o) for o in latest_observations(db, run_id)]
    if po:
        rows = [r for r in rows if norm(r["po"]) == norm(po)]
    return sorted(rows, key=lambda r: (r["po"], r["factory_code"], r["line"]))
