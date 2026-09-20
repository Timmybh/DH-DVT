"""Quản lý Column Configuration + Formula Definition: seed v1 (đã đối chiếu workbook), validate, preview, publish, giải thích."""

import json
import logging
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.core import User
from app.models.planning import FormulaDefinition, PlanColumn
from app.services import formula_defs as defs
from app.services import formula_runtime as fx
from app.services.audit import write_audit
from app.services.formula import FormulaError, compile_expression, detect_cycle, run_case

log = logging.getLogger(__name__)
CANONICAL_PATH = Path(__file__).resolve().parents[1] / "data" / "formula_canonical.json"


def _canonical() -> dict:
    try:
        return json.loads(CANONICAL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cases": {}, "verification": {}}


# ------------------------------------------------------------------ ca chuẩn
def run_cases(defn: FormulaDefinition) -> list[dict]:
    """Chạy toàn bộ ca chuẩn của một định nghĩa bằng bộ tính hiện tại và so với kết quả kỳ vọng từ workbook."""
    node, _ = compile_expression(defn.expression, set(fx.BUILTIN_COLUMNS))
    out = []
    for c in defn.canonical_cases or []:
        try:
            actual = run_case(node, c.get("inputs") or {}, c.get("prev"), c.get("manual"))
            actual = None if actual is None else actual
        except FormulaError as exc:
            actual = f"#ERR {exc}"
        expected = c.get("expected")
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
            ok = abs(actual - expected) <= (defn.tolerance or 1e-4)
        else:
            ok = (actual if actual is not None else "") == (expected if expected is not None else "")
        out.append({"kind": c.get("kind", ""), "ok": ok, "expected": expected, "actual": actual, "inputs": c.get("inputs"), "prev": c.get("prev"),
                    "source_row": c.get("source_row"), "synthetic": bool(c.get("synthetic"))})
    return out


# ------------------------------------------------------------------ validate / preview
def validate_expression(db: Session, column_code: str, expression: str) -> dict:
    """Cú pháp, tham chiếu cột, kiểu hàm, vòng phụ thuộc (so với các công thức đang Publish)."""
    errors: list[str] = []
    deps = None
    if column_code not in fx.BUILTIN_COLUMNS:
        errors.append(f"Cột '{column_code}' không có trong danh mục cột")
    try:
        _node, deps = compile_expression(expression, set(fx.BUILTIN_COLUMNS))
    except FormulaError as exc:
        errors.append(str(exc))
    if deps is not None and not errors:
        graph = {
            f.column_code: set((f.dependencies or {}).get("columns", []))
            for f in db.query(FormulaDefinition).filter(FormulaDefinition.status == "PUBLISHED", FormulaDefinition.column_code != column_code)
        }
        graph[column_code] = set(deps.columns)
        cyc = detect_cycle(graph)
        if cyc:
            errors.append("Vòng phụ thuộc: " + " → ".join(cyc))
    return {"ok": not errors, "errors": errors, "dependencies": deps.as_json() if deps else None}


def preview(expression: str, inputs: dict, prev: dict | None, manual) -> dict:
    try:
        node, deps = compile_expression(expression, set(fx.BUILTIN_COLUMNS))
        result = run_case(node, {k.upper(): v for k, v in (inputs or {}).items()}, {k.upper(): v for k, v in (prev or {}).items()} if prev else None, manual)
        return {"ok": True, "result": result, "dependencies": deps.as_json()}
    except FormulaError as exc:
        return {"ok": False, "error": str(exc)}


# ------------------------------------------------------------------ seed
def seed_columns_and_formulas(db: Session) -> None:
    """Idempotent: danh mục cột + công thức v1 (Publish khi ca chuẩn từ workbook đều đạt) + bản nháp chưa xác minh."""
    existing = {c.code for c in db.query(PlanColumn.code).all()}
    for i, (code, label, header, vtype, itype, lsrc, source) in enumerate(defs.COLUMNS, start=1):
        if code not in existing:
            db.add(PlanColumn(code=code, label=label, workbook_header=header, value_type=vtype, input_type=itype, list_source=lsrc, source=source, sort_order=i))

    canon = _canonical()
    have = {(f.column_code, f.version): f for f in db.query(FormulaDefinition).all()}
    ver_stats = canon.get("verification", {})
    for group, spec_map in (("V1", defs.V1), ("DRAFT", defs.DRAFTS)):
        for code, spec in spec_map.items():
            cur = have.get((code, 1))
            if cur is not None and not (cur.status == "DRAFT" and group == "V1"):
                continue  # đã tồn tại (bản Publish là bất biến); chỉ làm mới bản nháp v1 vừa được xác minh
            node, deps = compile_expression(spec["expression"], set(fx.BUILTIN_COLUMNS))
            cases = (canon.get("cases") or {}).get(code, [])
            v = dict(ver_stats.get(code, {}))
            if group == "DRAFT":
                v["note"] = "Chưa publish: quy tắc chưa được xác minh trọn vẹn với workbook."
            fields = dict(
                expression=spec["expression"], result_type=spec["result_type"], rounding_policy=spec["rounding"], calendar_policy=spec["calendar"],
                description=spec["description"], workbook_formula=spec["workbook_formula"], source_document=canon.get("source_document", ""),
                source_sheet=canon.get("source_sheet", ""), source_columns=spec["source_columns"], dependencies=deps.as_json(), canonical_cases=cases,
                tolerance=canon.get("tolerance", 1e-4), verification=v,
            )
            if cur is not None:
                for k, val in fields.items():
                    setattr(cur, k, val)
                defn = cur
            else:
                defn = FormulaDefinition(column_code=code, version=1, status="DRAFT", created_by="system", **fields)
                db.add(defn)
            db.flush()
            if group == "V1" and cases and all(r["ok"] for r in run_cases(defn)):
                defn.status, defn.published_by, defn.published_at = "PUBLISHED", "system (đối chiếu workbook)", utcnow()
            elif group == "V1":
                log.warning("Công thức %s v1 KHÔNG đạt ca chuẩn — để ở trạng thái DRAFT", code)
    db.commit()


def load_active(db: Session) -> fx.FormulaSet:
    rows = db.query(FormulaDefinition).filter(FormulaDefinition.status == "PUBLISHED").order_by(FormulaDefinition.version).all()
    best = {r.column_code: (r.version, r.expression) for r in rows}  # bản cao nhất thắng
    if not best:
        return fx.builtin_set()
    try:
        return fx.build_set(best)
    except FormulaError as exc:
        log.error("Không nạp được công thức từ DB (%s) — dùng bộ dựng sẵn", exc)
        return fx.builtin_set()


def refresh_active(db: Session) -> fx.FormulaSet:
    fs = load_active(db)
    fx.set_active(fs)
    return fs


# ------------------------------------------------------------------ API helpers
def defn_view(d: FormulaDefinition, with_cases: bool = False) -> dict:
    out = {
        "id": d.id, "column_code": d.column_code, "version": d.version, "status": d.status, "expression": d.expression, "result_type": d.result_type,
        "rounding_policy": d.rounding_policy, "calendar_policy": d.calendar_policy, "description": d.description, "workbook_formula": d.workbook_formula,
        "source_document": d.source_document, "source_sheet": d.source_sheet, "source_columns": d.source_columns, "dependencies": d.dependencies or {},
        "tolerance": d.tolerance, "verification": d.verification or {}, "created_by": d.created_by, "created_at": d.created_at.isoformat(),
        "published_by": d.published_by, "published_at": d.published_at.isoformat() if d.published_at else None, "case_count": len(d.canonical_cases or []),
    }
    if with_cases:
        out["cases"] = run_cases(d)
    return out


def columns_view(db: Session) -> list[dict]:
    pub = {}
    for d in db.query(FormulaDefinition).filter(FormulaDefinition.status == "PUBLISHED").order_by(FormulaDefinition.version):
        pub[d.column_code] = d
    drafts = {d.column_code for d in db.query(FormulaDefinition).filter(FormulaDefinition.status == "DRAFT")}
    out = []
    for c in db.query(PlanColumn).order_by(PlanColumn.sort_order).all():
        f = pub.get(c.code)
        sample = None
        if f and f.canonical_cases:
            first = next((x for x in run_cases(f) if not x["synthetic"] and x["ok"]), None)
            sample = first["actual"] if first else None
        out.append({
            "code": c.code, "label": c.label, "workbook_header": c.workbook_header, "value_type": c.value_type,
            "input_type": "CALCULATED" if f else c.input_type, "list_source": c.list_source, "source": c.source, "is_visible": c.is_visible,
            "formula": f.expression if f else None, "formula_id": f.id if f else None, "formula_version": f.version if f else None,
            "has_draft": c.code in drafts, "sample": sample,
        })
    return out


def explain(db: Session, code: str) -> dict:
    col = db.get(PlanColumn, code)
    if col is None:
        raise HTTPException(404, "Không có cột này")
    versions = db.query(FormulaDefinition).filter(FormulaDefinition.column_code == code).order_by(FormulaDefinition.version.desc()).all()
    current = next((v for v in versions if v.status == "PUBLISHED"), None)
    return {
        "column": {"code": col.code, "label": col.label, "workbook_header": col.workbook_header, "input_type": "CALCULATED" if current else col.input_type,
                   "list_source": col.list_source, "value_type": col.value_type},
        "current": defn_view(current, with_cases=True) if current else None,
        "versions": [defn_view(v) for v in versions],
    }


def create_draft(db: Session, user: User, code: str, expression: str, description: str, cases: list[dict], workbook_formula: str) -> FormulaDefinition:
    check = validate_expression(db, code, expression)
    if not check["ok"]:
        raise HTTPException(422, "; ".join(check["errors"]))
    latest = db.query(FormulaDefinition).filter(FormulaDefinition.column_code == code).order_by(FormulaDefinition.version.desc()).first()
    base = latest
    d = FormulaDefinition(
        column_code=code, version=(latest.version + 1) if latest else 1, status="DRAFT", expression=expression, description=description or (base.description if base else ""),
        result_type=(base.result_type if base else fx.BUILTIN_COLUMNS[code].value_type), rounding_policy=base.rounding_policy if base else "",
        calendar_policy=base.calendar_policy if base else "", workbook_formula=workbook_formula or (base.workbook_formula if base else ""),
        source_document=base.source_document if base else "", source_sheet=base.source_sheet if base else "", source_columns=base.source_columns if base else "",
        dependencies=check["dependencies"] or {}, canonical_cases=cases or [], tolerance=base.tolerance if base else 1e-4, verification={}, created_by=user.username,
    )
    db.add(d)
    db.commit()
    write_audit("FORMULA_DRAFT", user=user, object_type="FormulaDefinition", object_id=f"{code}.v{d.version}", detail=expression)
    return d


def publish(db: Session, user: User, formula_id: int) -> FormulaDefinition:
    d = db.get(FormulaDefinition, formula_id)
    if d is None:
        raise HTTPException(404, "Không tìm thấy công thức")
    if d.status != "DRAFT":
        raise HTTPException(409, f"Chỉ Publish được bản DRAFT (hiện là {d.status}) — bản đã Publish là bất biến")
    check = validate_expression(db, d.column_code, d.expression)
    if not check["ok"]:
        raise HTTPException(422, "Validate không đạt: " + "; ".join(check["errors"]))
    if not d.canonical_cases:
        raise HTTPException(422, "Chưa có ca chuẩn (canonical case) từ workbook — không được Publish công thức chỉ có biểu thức")
    results = run_cases(d)
    failed = [r for r in results if not r["ok"]]
    if failed:
        raise HTTPException(422, f"{len(failed)}/{len(results)} ca chuẩn không đạt (ví dụ '{failed[0]['kind']}': kỳ vọng {failed[0]['expected']}, nhận {failed[0]['actual']}) — không Publish")
    for old in db.query(FormulaDefinition).filter(FormulaDefinition.column_code == d.column_code, FormulaDefinition.status == "PUBLISHED"):
        old.status = "RETIRED"
    d.status, d.published_by, d.published_at, d.effective_from = "PUBLISHED", user.username, utcnow(), date.today()
    d.verification = {**(d.verification or {}), "last_run": {"cases": len(results), "passed": len(results), "at": utcnow().isoformat()}}
    db.commit()
    refresh_active(db)
    write_audit("FORMULA_PUBLISH", user=user, object_type="FormulaDefinition", object_id=f"{d.column_code}.v{d.version}", detail=d.expression)
    return d
