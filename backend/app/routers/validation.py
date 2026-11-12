"""FastAPI router for Data Integrity Validation."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.validators.data_validator import run_validation


router = APIRouter(prefix="/api/validation", tags=["Validation"])

_LATEST_REPORT: dict | None = None


@router.post("/run")
def execute_validation(db: Session = Depends(get_db)):
    global _LATEST_REPORT
    _LATEST_REPORT = run_validation(db, write_markdown_report=False)
    return _LATEST_REPORT


@router.get("/report")
def get_validation_report(db: Session = Depends(get_db)):
    if _LATEST_REPORT is not None:
        return _LATEST_REPORT
    return run_validation(db, write_markdown_report=False)

