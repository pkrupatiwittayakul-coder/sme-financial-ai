"""Financial statement generation endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io
from backend.database import (
    get_db, Period, JournalEntry, JournalLine,
    FinancialStatement, StatementLine,
    ValidationResult, ImportanceScore, Company,
)
from backend.services.statement_generator import (
    generate_income_statement, generate_trial_balance,
    generate_exception_report, generate_balance_sheet,
    generate_pdf_report,
)

router = APIRouter()


@router.post("/generate/{period_id}")
def generate_statements(period_id: int, db: Session = Depends(get_db)):
    """Generate Income Statement and Trial Balance for a period."""
    period = db.query(Period).get(period_id)
    if not period:
        raise HTTPException(404, "Period not found")

    # Fetch journal entries with lines
    entries_orm = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()
    if not entries_orm:
        raise HTTPException(400, "No journal entries. Run /records/process/{period_id} first.")

    entries = []
    for e in entries_orm:
        lines = db.query(JournalLine).filter(JournalLine.entry_id == e.id).all()
        entries.append({
            "id": e.id,
            "source_record_id": e.source_record_id,
            "date": e.date,
            "description": e.description,
            "lines": [{"account_code": l.account_code, "account_name": l.account_name,
                        "debit": l.debit, "credit": l.credit} for l in lines],
        })

    # Generate
    trial_balance = generate_trial_balance(entries)
    income_statement = generate_income_statement(entries, period.label)

    # Fetch exception data
    validations = db.query(ValidationResult).filter(ValidationResult.period_id == period_id).all()
    val_list = [{"validation_type": v.validation_type, "status": v.status,
                  "severity": v.severity, "message": v.message,
                  "business_record_id": v.business_record_id} for v in validations]

    scores = db.query(ImportanceScore).all()
    score_list = [{"object_type": s.object_type, "object_id": s.object_id,
                    "total_score": s.total_score, "level": s.level, "reason": s.reason}
                   for s in scores]

    exception_report = generate_exception_report(val_list, score_list)

    # Persist income statement to DB
    db.query(FinancialStatement).filter(FinancialStatement.period_id == period_id).delete()
    db.commit()

    fs = FinancialStatement(period_id=period_id, statement_type="income_statement")
    db.add(fs)
    db.flush()

    for line in income_statement["lines"]:
        sl = StatementLine(
            statement_id=fs.id,
            line_name=line["line_name"],
            amount=line["amount"],
            account_code=line.get("account_code", ""),
            line_type=line["line_type"],
            evidence_count=line.get("evidence_count", 0),
        )
        db.add(sl)
    db.commit()

    return {
        "period_id": period_id,
        "period_label": period.label,
        "income_statement": income_statement,
        "trial_balance": trial_balance,
        "exception_report": exception_report,
    }


@router.get("/income/{period_id}")
def get_income_statement(period_id: int, db: Session = Depends(get_db)):
    """Retrieve latest income statement."""
    fs = db.query(FinancialStatement).filter(
        FinancialStatement.period_id == period_id,
        FinancialStatement.statement_type == "income_statement"
    ).order_by(FinancialStatement.id.desc()).first()

    if not fs:
        raise HTTPException(404, "No income statement generated yet.")

    lines = db.query(StatementLine).filter(StatementLine.statement_id == fs.id).all()
    return {
        "statement_id": fs.id,
        "period_id": period_id,
        "generated_at": str(fs.generated_at),
        "lines": [
            {"line_name": l.line_name, "amount": l.amount,
             "account_code": l.account_code, "line_type": l.line_type,
             "evidence_count": l.evidence_count}
            for l in lines
        ],
    }


@router.get("/trial-balance/{period_id}")
def get_trial_balance(period_id: int, db: Session = Depends(get_db)):
    """Retrieve trial balance for a period from journal entries."""
    from backend.services.statement_generator import generate_trial_balance
    entries_orm = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()
    if not entries_orm:
        raise HTTPException(404, "No journal entries found. Run the pipeline first.")

    entries = []
    for e in entries_orm:
        lines = db.query(JournalLine).filter(JournalLine.entry_id == e.id).all()
        entries.append({
            "lines": [{"account_code": l.account_code, "account_name": l.account_name,
                       "debit": l.debit, "credit": l.credit} for l in lines]
        })

    tb = generate_trial_balance(entries)
    return {"period_id": period_id, "trial_balance": tb}


@router.get("/exceptions/{period_id}")
def get_exceptions(period_id: int, db: Session = Depends(get_db)):
    """Retrieve validation exceptions sorted by severity."""
    results = db.query(ValidationResult).filter(
        ValidationResult.period_id == period_id
    ).all()
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_results = sorted(results, key=lambda r: severity_order.get(r.severity, 3))
    return [
        {"id": r.id, "validation_type": r.validation_type, "status": r.status,
         "severity": r.s