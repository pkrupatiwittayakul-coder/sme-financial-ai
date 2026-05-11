"""Ownership verification helpers — ensure the logged-in user owns the resource."""
from fastapi import HTTPException
from sqlalchemy.orm import Session
from backend.database import Company, Period, File as FileModel


def assert_period_owned(period_id: int, user_id: int, db: Session) -> Period:
    period = db.get(Period, period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    company = db.get(Company, period.company_id)
    if not company or company.user_id != user_id:
        raise HTTPException(403, "Access denied")
    return period


def assert_file_owned(file_id: int, user_id: int, db: Session) -> FileModel:
    f = db.get(FileModel, file_id)
    if not f:
        raise HTTPException(404, "File not found")
    assert_period_owned(f.period_id, user_id, db)
    return f
