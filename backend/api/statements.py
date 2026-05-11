"""Financial statement generation endpoints. Auth required."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import (
    get_db, Period, JournalEntry, JournalLine,
    FinancialStatement, StatementLine, StatementEvidence,
    ValidationResult, ImportanceScore, BusinessRecord
)
from backend.services.statement_generator import (
    generate_income_statement, generate_trial_balance, generate_exception_report
)
from backend.services.validation_engine import validate_debit_credit_balance
from backend.services.auth_service import get_current_user
from backend.services.ownership import assert_period_owned

router = APIRouter()


@router.post("/generate/{period_id}")
def generate_statements(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate Income Statement and Trial Balance. Includes debit/credit balance check."""
    assert_period_owned(period_id, current_user.id, db)

    entries = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()
    if not entries:
        raise HTTPException(422, "No journal entries — run /api/agents/run first")

    # Gather lines
    entry_dicts = []
    for je in entries:
        lines = db.query(JournalLine).filter(JournalLine.entry_id == je.id).all()
        entry_dicts.append({
            "id": je.id,
            "source_record_id": je.source_record_id,
            "date": je.date,
            "description": je.description,
            "lines": [{"account_code": l.account_code, "account_name": l.account_name,
                        "debit": l.debit, "credit": l.credit} for l in lines],
        })

    # Balance check before generating
    balance = validate_debit_credit_balance(entry_dicts)
    if not balance["balanced"]:
        # Log warning but continue — unbalanced is surfaced in exceptions
        pass

    # Delete old statements for this period
    old = db.query(FinancialStatement).filter(FinancialStatement.period_id == period_id).all()
    for o in old:
        db.query(StatementLine).filter(StatementLine.statement_id == o.id).delete()
        db.delete(o)
    db.commit()

    # Income Statement
    is_lines = generate_income_statement(entry_dicts)
    is_stmt = FinancialStatement(period_id=period_id, statement_type="income_statement")
    db.add(is_stmt)
    db.flush()

    for line in is_lines:
        sl = StatementLine(
            statement_id=is_stmt.id,
            line_name=line["line_name"],
            amount=line["amount"],
            account_code=line.get("account_code", ""),
            line_type=line.get("line_type", ""),
            evidence_count=line.get("evidence_count", 0),
        )
        db.add(sl)
        db.flush()
        # Build StatementEvidence rows
        _attach_evidence(db, sl.id, line.get("account_code"), entry_dicts, line["amount"])

    # Trial Balance
    tb_lines = generate_trial_balance(entry_dicts)
    tb_stmt = FinancialStatement(period_id=period_id, statement_type="trial_balance")
    db.add(tb_stmt)
    db.flush()
    for line in tb_lines:
        db.add(StatementLine(
            statement_id=tb_stmt.id,
            line_name=line["account_name"],
            amount=line.get("net", 0),
            account_code=line.get("account_code", ""),
            line_type=line.get("account_type", ""),
            evidence_count=line.get("entry_count", 0),
        ))

    db.commit()

    return {
        "period_id": period_id,
        "income_statement_id": is_stmt.id,
        "trial_balance_id": tb_stmt.id,
        "income_statement_lines": len(is_lines),
        "trial_balance_lines": len(tb_lines),
        "balance_check": balance,
    }


def _attach_evidence(db: Session, line_id: int, account_code: str,
                     entry_dicts: list, line_amount: float):
    """Link a statement line to the journal entries that contributed to it."""
    if not account_code:
        return
    for entry in entry_dicts:
        for jline in entry.get("lines", []):
            if jline.get("account_code") == account_code:
                contrib = jline.get("credit", 0) - jline.get("debit", 0)
                if contrib == 0:
                    contrib = jline.get("debit", 0)
                db.add(StatementEvidence(
                    statement_line_id=line_id,
                    business_record_id=entry.get("source_record_id"),
                    journal_entry_id=entry.get("id"),
                    amount_contribution=round(contrib, 2),
                ))


@router.get("/evidence/{line_id}")
def get_line_evidence(
    line_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return source records that contributed to a specific statement line."""
    evidence = db.query(StatementEvidence).filter(
        StatementEvidence.statement_line_id == line_id
    ).all()
    if not evidence:
        raise HTTPException(404, "No evidence found for this line")

    results = []
    for ev in evidence:
        rec = db.get(BusinessRecord, ev.business_record_id) if ev.business_record_id else None
        results.append({
            "statement_line_id": ev.statement_line_id,
            "business_record_id": ev.business_record_id,
            "journal_entry_id": ev.journal_entry_id,
            "amount_contribution": ev.amount_contribution,
            "record_type": rec.record_type if rec else None,
            "record_date": rec.date if rec else None,
            "normalized_data": rec.normalized_data if rec else None,
        })
    return {"line_id": line_id, "evidence_count": len(results), "evidence": results}


@router.get("/{period_id}")
def get_statements(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retrieve generated statements for a period."""
    assert_period_owned(period_id, current_user.id, db)
    stmts = db.query(FinancialStatement).filter(FinancialStatement.period_id == period_id).all()
    result = {}
    for stmt in stmts:
        lines = db.query(StatementLine).filter(StatementLine.statement_id == stmt.id).all()
        result[stmt.statement_type] = {
            "id": stmt.id,
            "generated_at": stmt.generated_at.isoformat() if stmt.generated_at else None,
            "lines": [
                {"id": l.id, "line_name": l.line_name, "amount": l.amount,
                 "account_code": l.account_code, "line_type": l.line_type,
                 "evidence_count": l.evidence_count}
                for l in lines
            ],
        }
    return {"period_id": period_id, "statements": result}


@router.get("/exceptions/{period_id}")
def get_exceptions(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return all validation exceptions for a period, sorted by severity."""
    assert_period_owned(period_id, current_user.id, db)
    validations = db.query(ValidationResult).filter(
        ValidationResult.period_id == period_id,
        ValidationResult.status.in_(["warning", "failed"])
    ).all()
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_v = sorted(validations, key=lambda v: severity_order.get(v.severity, 3))
    return {
        "period_id": period_id,
        "total": len(sorted_v),
        "exceptions": [
            {"id": v.id, "type": v.validation_type, "status": v.status,
             "severity": v.severity, "message": v.message,
             "record_id": v.business_record_id}
            for v in sorted_v[:50]
        ],
    }


@router.get("/income/{period_id}")
def get_income_statement(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retrieve the latest income statement lines for a period."""
    assert_period_owned(period_id, current_user.id, db)
    fs = db.query(FinancialStatement).filter(
        FinancialStatement.period_id == period_id,
        FinancialStatement.statement_type == "income_statement",
    ).order_by(FinancialStatement.id.desc()).first()
    if not fs:
        raise HTTPException(404, "No income statement yet — run the pipeline first.")
    lines = db.query(StatementLine).filter(StatementLine.statement_id == fs.id).all()
    return {
        "statement_id": fs.id,
        "period_id": period_id,
        "generated_at": fs.generated_at.isoformat() if fs.generated_at else None,
        "lines": [
            {"line_name": l.line_name, "amount": l.amount,
             "account_code": l.account_code, "line_type": l.line_type,
             "evidence_count": l.evidence_count}
            for l in lines
        ],
    }


@router.get("/trial-balance/{period_id}")
def get_trial_balance(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return a trial balance computed live from journal entries."""
    assert_period_owned(period_id, current_user.id, db)
    from backend.services.statement_generator import generate_trial_balance
    entries_orm = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()
    if not entries_orm:
        raise HTTPException(404, "No journal entries — run the pipeline first.")
    entries = []
    for je in entries_orm:
        lines = db.query(JournalLine).filter(JournalLine.entry_id == je.id).all()
        entries.append({
            "lines": [{"account_code": l.account_code, "account_name": l.account_name,
                       "debit": l.debit, "credit": l.credit} for l in lines]
        })
    tb = generate_trial_balance(entries)
    return {"period_id": period_id, "trial_balance": tb}
