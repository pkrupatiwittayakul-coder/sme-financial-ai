"""Company management endpoints (scoped per authenticated user)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.database import get_db, Company, Period, Account
from backend.services.accounting_mapper import build_default_accounts
from backend.services.auth_service import get_current_user

router = APIRouter()


class CompanyCreate(BaseModel):
    name: str
    industry: Optional[str] = "Retail"
    currency: Optional[str] = "THB"


# ── Internal helper (no auth, used by upload) ────────────────────────────────

def _get_or_create_period(company_id: int, db: Session) -> Period:
    """Get the single open period for a company, or create one."""
    period = (
        db.query(Period)
        .filter(Period.company_id == company_id, Period.status == "open")
        .order_by(Period.id.desc())
        .first()
    )
    if not period:
        period = Period(
            company_id=company_id,
            label="Auto-detected",
            start_date="",
            end_date="",
            status="open",
        )
        db.add(period)
        db.commit()
        db.refresh(period)
        for acc_data in build_default_accounts(period.id):
            db.add(Account(**acc_data))
        db.commit()
    return period


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/")
def create_company(
    data: CompanyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    company = Company(
        name=data.name,
        industry=data.industry,
        currency=data.currency,
        user_id=current_user.id,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return {"id": company.id, "name": company.name, "industry": company.industry, "currency": company.currency}


@router.get("/")
def list_companies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    companies = db.query(Company).filter(Company.user_id == current_user.id).all()
    return [
        {"id": c.id, "name": c.name, "industry": c.industry, "currency": c.currency}
        for c in companies
    ]


@router.post("/{company_id}/ensure-period")
def ensure_period(
    company_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get or create the single active period for a company. Called automatically on company select."""
    company = db.query(Company).filter(
        Company.id == company_id,
        Company.user_id == current_user.id,
    ).first()
    if not company:
        raise HTTPException(404, "Company not found")
    period = _get_or_create_period(company_id, db)
    return {
        "id": period.id,
        "label": period.label,
        "start_date": period.start_date,
        "end_date": period.end_date,
        "status": period.status,
    }


@router.get("/{company_id}/summary")
def company_summary(
    company_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the latest period + file count + statement summary for a company."""
    from backend.database import File as FileModel, FinancialStatement, StatementLine, Entity
    company = db.query(Company).filter(
        Company.id == company_id,
        Company.user_id == current_user.id,
    ).first()
    if not company:
        raise HTTPException(404, "Company not found")

    period = _get_or_create_period(company_id, db)

    files = db.query(FileModel).filter(FileModel.period_id == period.id).all()
    file_list = [{"id": f.id, "filename": f.filename, "file_type": f.file_type,
                  "row_count": f.row_count} for f in files]

    fs = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.period_id == period.id)
        .order_by(FinancialStatement.id.desc())
        .first()
    )
    income = None
    if fs:
        lines = db.query(StatementLine).filter(StatementLine.statement_id == fs.id).all()
        summary = {l.line_type: l.amount for l in lines}
        income = {
            "revenue": summary.get("revenue", 0),
            "cogs": summary.get("cogs", 0),
            "gross_profit": summary.get("gross_profit", 0),
            "operating_expenses": summary.get("expense", 0),
            "net_profit": summary.get("net_profit", 0),
            "lines": [{"line_name": l.line_name, "amount": l.amount, "line_type": l.line_type,
                       "evidence_count": l.evidence_count} for l in lines],
        }

    # Entity counts
    entity_counts = {}
    entities = db.query(Entity).filter(Entity.period_id == period.id).all()
    for e in entities:
        entity_counts[e.entity_type] = entity_counts.get(e.entity_type, 0) + 1

    return {
        "company": {"id": company.id, "name": company.name, "industry": company.industry, "currency": company.currency},
        "period": {"id": period.id, "label": period.label, "start_date": period.start_date, "end_date": period.end_date},
        "files": file_list,
        "income_statement": income,
        "entity_counts": entity_counts,
    }
