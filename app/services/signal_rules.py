"""Bảng đăng ký Tin tốt / Tin xấu (Dashboard).

Mỗi quy tắc gắn với một CHỈ SỐ ĐO LƯỜNG (metric) và có nhiều CẤP ĐỘ: khoảng giá trị → vùng (Tin tốt / Cảnh báo), mức độ, nhãn ("Tin nóng"...) và LỜI GHÉP (mẫu câu có {xn}, {value}...).
Ví dụ: Hiệu suất hôm nay ≥ 95% → Tin tốt · nhãn "Tin nóng" · "{xn} hôm nay hiệu suất cao ngút trời ({value}%)".
Không xóa quy tắc, chỉ Ngưng áp dụng. Cấp độ được xét theo thứ tự; cấp đầu tiên khớp thì thắng.
"""

from __future__ import annotations

import string
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import Factory, User
from app.models.dashboard_cfg import SignalRule, SignalRuleLevel
from app.services.audit import write_audit

OPS = (">=", ">", "<=", "<", "BETWEEN")
ZONES = ("GOOD", "WARN")
SEVERITIES = ("INFO", "WARNING", "CRITICAL")
PLACEHOLDERS = ("xn", "factory", "value", "tag", "metric", "unit")
SCOPES = ("PER_FACTORY",)  # mỗi xí nghiệp một tin


# ------------------------------------------------------------------ danh mục chỉ số đo lường
def _hardcoded(targets: dict[str, float]):
    return lambda db, factories, today: {f.code: targets.get(f.code) for f in factories}


def _output_actual(db: Session, factories: list[Factory], today: date) -> dict[str, float | None]:
    from app.models.data import FactoryOutputDaily

    got = {r.factory_id: r for r in db.query(FactoryOutputDaily).filter(FactoryOutputDaily.day == today)}
    return {f.code: (round(got[f.id].sewn_qty / got[f.id].target_qty * 100, 1) if f.id in got and got[f.id].target_qty else None) for f in factories}


def _revenue(db: Session, factories: list[Factory], today: date, gap: bool) -> dict[str, float | None]:
    from app.services.dashboard import revenue_overview

    rev = revenue_overview(db, factories, today.year, today.month, today)
    out: dict[str, float | None] = {}
    for row in rev["by_factory"]:
        pct = row["month_pct"] if row["month_declared"] else None
        out[row["code"]] = (round(pct - rev["elapsed_pct"], 1) if gap and pct is not None else None) if gap else pct
    return out


def metric_catalog() -> dict[str, dict]:
    from app.services.dashboard import EFFICIENCY_TARGETS, RFT_TARGETS

    return {
        "EFFICIENCY_TODAY": {"name": "Hiệu suất hôm nay", "unit": "%", "note": "Hiện là số cố định theo XN (sẽ tính từ sản lượng × SAM)", "fn": _hardcoded(EFFICIENCY_TARGETS)},
        "RFT_TODAY": {"name": "RFT hôm nay", "unit": "%", "note": "Hiện là số cố định theo XN (sẽ lấy từ DB hiPro)", "fn": _hardcoded(RFT_TARGETS)},
        "OUTPUT_ACTUAL_PCT": {"name": "Sản lượng may ra / kế hoạch ngày", "unit": "%", "note": "May ra hôm nay (ERP) ÷ kế hoạch may trong ngày (OMM_KeHoachThang)", "fn": _output_actual},
        "REVENUE_MONTH_PCT": {"name": "Doanh thu tháng đạt so với kế hoạch", "unit": "%", "note": "Thực hiện ÷ kế hoạch doanh thu tháng (ERP)", "fn": lambda db, f, t: _revenue(db, f, t, False)},
        "REVENUE_PACE_GAP": {"name": "Doanh thu so với tiến độ thời gian", "unit": "điểm %", "note": "% đạt kế hoạch tháng trừ % thời gian đã qua (âm = chậm)", "fn": lambda db, f, t: _revenue(db, f, t, True)},
    }


# ------------------------------------------------------------------ hiển thị
def level_view(l: SignalRuleLevel) -> dict:
    return {"id": l.id, "order_no": l.order_no, "name": l.name, "zone": l.zone, "severity": l.severity, "tag": l.tag, "op": l.op, "value_from": l.value_from, "value_to": l.value_to, "template": l.template}


def rule_view(db: Session, r: SignalRule) -> dict:
    lv = db.query(SignalRuleLevel).filter(SignalRuleLevel.rule_id == r.id).order_by(SignalRuleLevel.order_no, SignalRuleLevel.id).all()
    m = metric_catalog().get(r.metric_code)
    return {"id": r.id, "code": r.code, "name": r.name, "metric_code": r.metric_code, "metric_name": m["name"] if m else r.metric_code, "unit": m["unit"] if m else "", "scope": r.scope,
            "status": r.status, "display_order": r.display_order, "note": r.note, "updated_by": r.updated_by, "levels": [level_view(x) for x in lv]}


# ------------------------------------------------------------------ kiểm tra / lưu
def _placeholders(template: str) -> set[str]:
    return {name.split(".")[0].split("[")[0] for _, name, _, _ in string.Formatter().parse(template) if name}


def _validate(d: dict) -> None:
    if d.get("metric_code") not in metric_catalog():
        raise HTTPException(422, f"Chỉ số đo lường '{d.get('metric_code')}' không có trong danh mục")
    if not (d.get("name") or "").strip():
        raise HTTPException(422, "Cần tên quy tắc")
    levels = d.get("levels") or []
    if not levels:
        raise HTTPException(422, "Cần ít nhất một cấp độ")
    for i, l in enumerate(levels, start=1):
        if l.get("zone") not in ZONES or l.get("severity") not in SEVERITIES or l.get("op") not in OPS:
            raise HTTPException(422, f"Cấp độ {i}: vùng/mức độ/phép so sánh không hợp lệ")
        if l.get("value_from") is None or (l["op"] == "BETWEEN" and (l.get("value_to") is None or l["value_to"] < l["value_from"])):
            raise HTTPException(422, f"Cấp độ {i}: khoảng giá trị không hợp lệ")
        tpl = (l.get("template") or "").strip()
        if not tpl:
            raise HTTPException(422, f"Cấp độ {i}: cần lời ghép")
        bad = _placeholders(tpl) - set(PLACEHOLDERS)
        if bad:
            raise HTTPException(422, f"Cấp độ {i}: biến không hỗ trợ {sorted(bad)} (dùng: {', '.join('{' + p + '}' for p in PLACEHOLDERS)})")
        if l["zone"] == "GOOD" and l["severity"] != "INFO":
            raise HTTPException(422, f"Cấp độ {i}: Tin tốt chỉ có mức INFO")


def _replace_levels(db: Session, rule: SignalRule, levels: list[dict]) -> None:
    db.query(SignalRuleLevel).filter(SignalRuleLevel.rule_id == rule.id).delete()
    for n, l in enumerate(levels, start=1):
        db.add(SignalRuleLevel(rule_id=rule.id, order_no=n, name=(l.get("name") or "")[:80], zone=l["zone"], severity=l["severity"], tag=(l.get("tag") or "")[:30], op=l["op"],
                               value_from=float(l["value_from"]), value_to=(float(l["value_to"]) if l.get("value_to") is not None else None), template=l["template"].strip()[:300]))


def save_rule(db: Session, user: User, d: dict, rid: int | None = None) -> SignalRule:
    if rid is not None:
        cur = db.get(SignalRule, rid)
        if cur is None:
            raise HTTPException(404, "Không tìm thấy quy tắc")
        d = {"metric_code": cur.metric_code, "name": cur.name, **d}
    _validate(d)
    if rid is None:
        code = (d.get("code") or "").strip().upper()
        if not code:
            raise HTTPException(422, "Cần mã quy tắc")
        if db.query(SignalRule).filter(SignalRule.code == code).first():
            raise HTTPException(409, "Mã quy tắc đã tồn tại")
        rule = SignalRule(code=code, created_by=user.username)
        db.add(rule)
        action = "SIGNAL_RULE_CREATE"
    else:
        rule, action = cur, "SIGNAL_RULE_UPDATE"
    rule.name, rule.metric_code, rule.note = d["name"].strip(), d["metric_code"], (d.get("note") or "")[:300]
    rule.display_order = int(d.get("display_order") or rule.display_order or 0)
    rule.updated_by, rule.updated_at = user.username, utcnow()
    db.flush()
    _replace_levels(db, rule, d["levels"])
    db.commit()
    write_audit(action, user=user, object_type="SignalRule", object_id=rule.code, detail=f"{rule.name} · {len(d['levels'])} cấp độ")
    return rule


def set_status(db: Session, user: User, rid: int, active: bool) -> SignalRule:
    r = db.get(SignalRule, rid)
    if r is None:
        raise HTTPException(404, "Không tìm thấy quy tắc")
    r.status, r.updated_by, r.updated_at = ("ACTIVE" if active else "INACTIVE"), user.username, utcnow()
    db.commit()
    write_audit("SIGNAL_RULE_STATUS", user=user, object_type="SignalRule", object_id=r.code, detail=r.status)
    return r


# ------------------------------------------------------------------ tính tin
def _matches(l: SignalRuleLevel | dict, v: float) -> bool:
    g = (lambda k: l[k]) if isinstance(l, dict) else (lambda k: getattr(l, k))
    op, a, b = g("op"), g("value_from"), g("value_to")
    return (op == ">=" and v >= a) or (op == ">" and v > a) or (op == "<=" and v <= a) or (op == "<" and v < a) or (op == "BETWEEN" and a <= v <= b)


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def render(template: str, ctx: dict) -> str:
    return string.Formatter().vformat(template, (), {k: ctx.get(k, "") for k in PLACEHOLDERS})


def evaluate(db: Session, factories: list[Factory], today: date | None = None, values: dict[str, dict[str, float | None]] | None = None) -> list[dict]:
    """Danh sách tín hiệu do các quy tắc ACTIVE sinh ra cho các xí nghiệp trong `factories`."""
    from app.services.dashboard import today_local

    today = today or today_local()
    cat = metric_catalog()
    signals: list[dict] = []
    cache: dict[str, dict[str, float | None]] = values if values is not None else {}
    for r in db.query(SignalRule).filter(SignalRule.status == "ACTIVE").order_by(SignalRule.display_order, SignalRule.id):
        m = cat.get(r.metric_code)
        if m is None:
            continue
        if r.metric_code not in cache:
            try:
                cache[r.metric_code] = m["fn"](db, factories, today)
            except Exception:  # noqa: BLE001 - một chỉ số lỗi không làm hỏng các tin khác
                cache[r.metric_code] = {}
        levels = db.query(SignalRuleLevel).filter(SignalRuleLevel.rule_id == r.id).order_by(SignalRuleLevel.order_no, SignalRuleLevel.id).all()
        for f in factories:
            v = cache[r.metric_code].get(f.code)
            if v is None:
                continue
            for l in levels:
                if _matches(l, v):
                    msg = render(l.template, {"xn": f.code, "factory": f.name, "value": _fmt(v), "tag": l.tag, "metric": m["name"], "unit": m["unit"]})
                    signals.append({"id": f"rule.{r.code}.{f.code}", "zone": l.zone, "severity": l.severity, "title": f"{l.tag}: {msg}" if l.tag else msg, "tag": l.tag,
                                    "detail": f"{m['name']}: {_fmt(v)}{'' if m['unit'] == 'điểm %' else m['unit']}" + (f" · {l.name}" if l.name else ""), "drill": None})
                    break
    return signals


# ------------------------------------------------------------------ gieo mẫu (chỉ khi bảng trống)
SEED = [
    ("HIEU_SUAT", "Hiệu suất hôm nay", "EFFICIENCY_TODAY", [
        ("Cực cao", "GOOD", "INFO", "Tin nóng", ">=", 95, None, "{xn} hôm nay hiệu suất cao ngút trời ({value}%)"),
        ("Cao", "GOOD", "INFO", "Tin tốt", ">=", 90, None, "{xn} giữ hiệu suất tốt hôm nay ({value}%)"),
        ("Thấp", "WARN", "WARNING", "Cảnh báo", "<", 85, None, "{xn} hiệu suất hôm nay thấp ({value}%)"),
        ("Rất thấp", "WARN", "CRITICAL", "Báo động", "<", 75, None, "{xn} hiệu suất tụt sâu ({value}%) — cần xử lý ngay"),
    ]),
    ("RFT", "RFT hôm nay", "RFT_TODAY", [
        ("Xuất sắc", "GOOD", "INFO", "Tin nóng", ">=", 98, None, "{xn} hôm nay RFT xuất sắc ({value}%)"),
        ("Tốt", "GOOD", "INFO", "Tin tốt", ">=", 96, None, "{xn} RFT đạt mức tốt ({value}%)"),
        ("Thấp", "WARN", "WARNING", "Cảnh báo", "<", 95, None, "{xn} RFT thấp hôm nay ({value}%)"),
    ]),
    ("SAN_LUONG", "Sản lượng may ra so với kế hoạch ngày", "OUTPUT_ACTUAL_PCT", [
        ("Vượt kế hoạch", "GOOD", "INFO", "Tin nóng", ">=", 100, None, "{xn} hôm nay may ra vượt kế hoạch ngày ({value}%)"),
        ("Chậm", "WARN", "WARNING", "Cảnh báo", "<", 60, None, "{xn} hôm nay may ra mới đạt {value}% kế hoạch ngày"),
        ("Rất chậm", "WARN", "CRITICAL", "Báo động", "<", 30, None, "{xn} hôm nay may ra chỉ đạt {value}% kế hoạch ngày"),
    ]),
]


def seed_signal_rules(db: Session) -> int:
    if db.query(SignalRule).count():
        return 0
    for n, (code, name, metric, levels) in enumerate(SEED, start=1):
        r = SignalRule(code=code, name=name, metric_code=metric, display_order=n, created_by="system", updated_by="system", note="Quy tắc mẫu — chỉnh hoặc ngưng tùy ý")
        db.add(r)
        db.flush()
        _replace_levels(db, r, [dict(name=a, zone=b, severity=c, tag=d, op=e, value_from=f, value_to=g, template=h) for a, b, c, d, e, f, g, h in levels])
    db.commit()
    return len(SEED)
