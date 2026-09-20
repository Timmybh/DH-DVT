"""Snapshot lao động lưu riêng cho Dashboard (handoff §26: lịch sử không ghi đè; số liệu Dashboard không phụ thuộc bảng vận hành đổi liên tục)."""

import re
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app.models.labor_snapshot import LaborSnapshot, LaborSnapshotLine

STALE_DAYS = 3  # chuyền có số liệu cũ hơn ngày dữ liệu mới nhất quá số ngày này -> không đưa vào ảnh chụp


def _current(db: Session):
    """Các snapshot lao động, mới nhất trước."""
    return db.query(LaborSnapshot).order_by(LaborSnapshot.as_of_date.desc(), LaborSnapshot.id.desc())


def _pct(present: int, total: int) -> float | None:
    return round(present / total * 100, 1) if total else None


def take_snapshot(db: Session, run_id: int | None, labor_rows: list[dict]) -> LaborSnapshot | None:
    """labor_rows: {factory_code, line, day, total, present}. Lấy số liệu MỚI NHẤT của từng chuyền; trả về ảnh chụp mới (hoặc ảnh chụp trước nếu số liệu không đổi)."""
    latest: dict[tuple[str, str], dict] = {}
    for r in labor_rows:
        key = (r["factory_code"], r["line"])
        if key not in latest or r["day"] > latest[key]["day"]:
            latest[key] = r
    if not latest:
        return None
    as_of: date = max(r["day"] for r in latest.values())
    kept = [r for r in latest.values() if (as_of - r["day"]).days <= STALE_DAYS]
    by_factory: dict[str, dict[str, int]] = defaultdict(lambda: {"lines": 0, "total": 0, "present": 0})
    for r in kept:
        f = by_factory[r["factory_code"]]
        f["lines"] += 1
        f["total"] += int(r["total"] or 0)
        f["present"] += int(r["present"] or 0)
    sig = sorted((r["factory_code"], r["line"], int(r["total"] or 0), int(r["present"] or 0)) for r in kept)

    prev = _current(db).first()
    if prev is not None and prev.as_of_date == as_of:
        prev_sig = sorted((l.factory_code, l.line, l.total, l.present) for l in db.query(LaborSnapshotLine).filter(LaborSnapshotLine.snapshot_id == prev.id))
        if prev_sig == sig:
            return prev  # không đổi -> không tạo ảnh chụp trùng
    snap = LaborSnapshot(
        sync_run_id=run_id, as_of_date=as_of, lines=len(kept), stale_lines=len(latest) - len(kept), total=sum(f["total"] for f in by_factory.values()),
        present=sum(f["present"] for f in by_factory.values()), by_factory={k: dict(v) for k, v in by_factory.items()},
    )
    db.add(snap)
    db.flush()
    for r in kept:
        db.add(LaborSnapshotLine(snapshot_id=snap.id, factory_code=r["factory_code"], line=r["line"], day=r["day"], total=int(r["total"] or 0), present=int(r["present"] or 0)))
    db.flush()
    return snap


def backfill_from_labor_daily(db: Session) -> int:
    """Lần đầu (chưa có ảnh chụp nào): dựng ảnh chụp từng ngày từ số liệu lao động eGMF đã lưu (labor_daily) để Dashboard và xu hướng có dữ liệu ngay,
    không phải chờ lần đồng bộ kế tiếp. Chỉ chạy một lần; sau đó ảnh chụp mới do đồng bộ tạo."""
    from app.models.resources import LaborDaily

    if db.query(LaborSnapshot.id).first() is not None:
        return 0
    by_day: dict[date, list[dict]] = defaultdict(list)
    for r in db.query(LaborDaily).order_by(LaborDaily.day):
        by_day[r.day].append({"factory_code": r.factory_code, "line": r.line, "day": r.day, "total": r.total, "present": r.present})
    n = 0
    for day in sorted(by_day):
        if take_snapshot(db, None, by_day[day]) is not None:
            n += 1
    db.commit()
    return n


def _snap_out(s: LaborSnapshot) -> dict:
    return {"id": s.id, "as_of": s.as_of_date.isoformat(), "taken_at": s.taken_at.isoformat() if s.taken_at else None, "lines": s.lines, "stale_lines": s.stale_lines, "total": s.total,
            "present": s.present, "attendance_pct": _pct(s.present, s.total),
            "by_factory": {k: {**v, "attendance_pct": _pct(v["present"], v["total"])} for k, v in (s.by_factory or {}).items()}}


def dashboard_summary(db: Session, trend_points: int = 14) -> dict | None:
    """Ảnh chụp mới nhất + chênh lệch so với ảnh chụp trước + xu hướng — nguồn duy nhất của số liệu lao động trên Dashboard."""
    snaps = _current(db).limit(trend_points).all()
    if not snaps:
        return None
    cur = _snap_out(snaps[0])
    if len(snaps) > 1:
        prev = snaps[1]
        cur["previous_as_of"] = prev.as_of_date.isoformat()
        cur["delta_present"] = cur["present"] - prev.present
        for code, f in cur["by_factory"].items():
            f["delta_present"] = f["present"] - int((prev.by_factory or {}).get(code, {}).get("present", 0))
    # xu hướng: mỗi ngày dữ liệu lấy ảnh chụp mới nhất của ngày đó
    per_day: dict[str, dict] = {}
    for s in snaps:
        per_day.setdefault(s.as_of_date.isoformat(), {"as_of": s.as_of_date.isoformat(), "present": s.present, "total": s.total})
    cur["trend"] = sorted(per_day.values(), key=lambda p: p["as_of"])
    return cur


def snapshot_lines(db: Session, snapshot_id: int, factory_codes: list[str] | None = None) -> list[LaborSnapshotLine]:
    q = db.query(LaborSnapshotLine).filter(LaborSnapshotLine.snapshot_id == snapshot_id)
    if factory_codes is not None:
        q = q.filter(LaborSnapshotLine.factory_code.in_(factory_codes))
    return sorted(q.all(), key=lambda l: (l.factory_code, [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", l.line)]))
