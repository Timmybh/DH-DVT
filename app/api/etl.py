from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.importjob import ImportJob, ImportJobConfig
from app.models.user import User
from app.schemas.importjob import ImportJobConfigOut, ImportJobConfigUpdate, ImportJobOut
from app.services.etl import run_sync

router = APIRouter(prefix="/admin/etl", tags=["admin-etl"], dependencies=[Depends(require_admin)])


def _get_or_create_config(db: Session) -> ImportJobConfig:
    cfg = db.query(ImportJobConfig).first()
    if cfg is None:
        cfg = ImportJobConfig()
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


@router.post("/run", response_model=ImportJobOut)
def run_now(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    job = run_sync(db, triggered_by=user.username, job_type="MANUAL")
    return job


@router.get("/jobs", response_model=list[ImportJobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(ImportJob).order_by(ImportJob.started_at.desc()).limit(20).all()


@router.get("/config", response_model=ImportJobConfigOut)
def get_config(db: Session = Depends(get_db)):
    return _get_or_create_config(db)


@router.put("/config", response_model=ImportJobConfigOut)
def update_config(payload: ImportJobConfigUpdate, db: Session = Depends(get_db)):
    cfg = _get_or_create_config(db)
    cfg.is_enabled = payload.is_enabled
    cfg.scheduled_time = payload.scheduled_time
    db.commit()
    db.refresh(cfg)
    return cfg
