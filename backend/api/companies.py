"""Company and Period management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from backend.database import get_db, Company, Period
from backend.services.accounting_mapper import build_default_accounts
from backend.database import Account

router = APIRouter()


class CompanyCreate(BaseModel):
    name: str
    industry: Optional[str] = "Retail"
    currency: Optional[str] = "THB"


class PeriodCreate(BaseModel):
    company_id: int
    label: str
    start_date: str
    end_date: str


@router.post("/")
def create_company(data: CompanyCreate, db: Session = Depends(get_db)):
    company = Company(name=data.name, industry=data.industry, currency=data.currency)
    db.add(company)
    db.commit()
    db.refresh(company)
    return {"id": company.id, "name": company.name}


@router.get("/")
def list_companies(db: Session = Depends(get_db)):
    companies = db.query(Company).all()
    return [{"id": c.id, "name": c.name, "industry": c.industry, "currency": c.currency}
            for c in companies]


@router.post("/periods")
def create_period(data: PeriodCreate, db: Session = Depends(get_db)):
    period = Period(
        company_id=data.company_id,
        label=data.label,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    db.add(period)
    db.commit()
    db.refresh(period)

    # Seed default chart of accounts
    for acc_data in build_default_accounts(period.id):
        acc = Account(**acc_data)
        db.add(acc)
    db.commit()

    return {"id": period.id, "label": period.label, "company_id": period.company_id}


@router.get("/periods/{company_id}")
def list_periods(company_id: int, db: Session = Depends(get_db)):
    periods = db.query(Period).filter(Period.company_id == company_id).all()
    return [{"id": p.id, "label": p.label, "start_date": p.start_date,
             "end_date": p.end_date, "status": p.status} for p in periods]
