from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_perm
from app.db.session import get_db
from app.models.core import User
from app.models.planning import FormulaDefinition, PlanColumn
from app.services import formula_service as svc
from app.services.audit import write_audit

router = APIRouter(prefix="/planning", tags=["formulas"])

View = Depends(require_perm("planning.view"))
Manage = Depends(require_perm("formula.manage"))


@router.get("/columns")
def list_columns(db: Session = Depends(get_db), _: User = View):
    return svc.columns_view(db)


class ColumnPatch(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=80)
    list_source: str | None = Field(None, max_length=60)
    is_visible: bool | None = None


@router.put("/columns/{code}")
def patch_column(code: str, body: ColumnPatch, db: Session = Depends(get_db), user: User = Manage):
    col = db.get(PlanColumn, code)
    if col is None:
        raise HTTPException(404, "Không có cột này")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(col, k, v)
    db.commit()
    write_audit("PLAN_COLUMN_UPDATE", user=user, object_type="PlanColumn", object_id=code, detail=str(body.model_dump(exclude_none=True)))
    return next(c for c in svc.columns_view(db) if c["code"] == code)


@router.get("/columns/{code}/explain")
def explain_column(code: str, db: Session = Depends(get_db), _: User = View):
    return svc.explain(db, code)


class ExprBody(BaseModel):
    column_code: str
    expression: str = Field(..., min_length=1, max_length=2000)


@router.post("/formulas/validate")
def validate(body: ExprBody, db: Session = Depends(get_db), _: User = View):
    return svc.validate_expression(db, body.column_code, body.expression)


class PreviewBody(BaseModel):
    expression: str = Field(..., min_length=1, max_length=2000)
    inputs: dict[str, Any] = {}
    prev: dict[str, Any] | None = None
    manual: Any = None


@router.post("/formulas/preview")
def preview(body: PreviewBody, _: User = View):
    return svc.preview(body.expression, body.inputs, body.prev, body.manual)


class DraftBody(BaseModel):
    column_code: str
    expression: str = Field(..., min_length=1, max_length=2000)
    description: str = ""
    workbook_formula: str = ""
    cases: list[dict[str, Any]] = []


@router.post("/formulas")
def create_draft(body: DraftBody, db: Session = Depends(get_db), user: User = Manage):
    return svc.defn_view(svc.create_draft(db, user, body.column_code, body.expression, body.description, body.cases, body.workbook_formula))


@router.get("/formulas/{formula_id}")
def get_formula(formula_id: int, db: Session = Depends(get_db), _: User = View):
    d = db.get(FormulaDefinition, formula_id)
    if d is None:
        raise HTTPException(404, "Không tìm thấy công thức")
    return svc.defn_view(d, with_cases=True)


@router.post("/formulas/{formula_id}/publish")
def publish(formula_id: int, db: Session = Depends(get_db), user: User = Manage):
    return svc.defn_view(svc.publish(db, user, formula_id), with_cases=True)
