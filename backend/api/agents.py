"""
Run all 6 process validation agents for a period.
Each agent validates its business process and posts journal entries.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db, JournalEntry, JournalLine
from backend.services.auth_service import get_current_user
from backend.services.ownership import assert_period_owned
from backend.agents import (
    sales_agent, purchase_agent, inventory_agent,
    bank_agent, tax_agent, record_to_report_agent
)

router = APIRouter()


@router.post("/run/{period_id}")
def run_all_agents(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run all 6 process agents sequentially. Returns per-agent results."""
    assert_period_owned(period_id, current_user.id, db)

    # Clear old journal entries for this period before re-running
    old_entries = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()
    for oe in old_entries:
        db.query(JournalLine).filter(JournalLine.entry_id == oe.id).delete()
        db.delete(oe)
    db.commit()

    AGENTS = [
        ("Sales/OtC",         sales_agent),
        ("Procure-to-Pay",    purchase_agent),
        ("Inventory-to-COGS", inventory_agent),
        ("Bank Rec",          bank_agent),
        ("Tax Agent",         tax_agent),
        ("Record-to-Report",  record_to_report_agent),
    ]

    results = []
    for name, agent in AGENTS:
        try:
            result = agent.run(period_id, db)
            results.append({
                "agent":           result.agent_name,
                "status":          result.status,
                "records_checked": result.records_checked,
                "journal_entries": result.journal_entries,
                "exceptions":      len(result.exceptions),
                "summary":         result.summary,
                "top_exceptions":  result.exceptions[:3],
            })
        except Exception as e:
            results.append({
                "agent": name, "status": "error",
                "summary": str(e), "exceptions": 0
            })

    total_exceptions = sum(r.get("exceptions", 0) for r in results)
    total_entries    = sum(r.get("journal_entries", 0) for r in results)

    return {
        "period_id":        period_id,
        "agents_run":       len(AGENTS),
        "total_exceptions": total_exceptions,
        "total_entries":    total_entries,
        "results":          results,
    }


@router.get("/status/{period_id}")
def agent_status(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return journal entry count and validation summary for a period."""
    assert_period_owned(period_id, current_user.id, db)
    from backend.database import ValidationResult
    entries = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).count()
    validations = db.query(ValidationResult).filter(ValidationResult.period_id == period_id).all()
    return {
        "period_id": period_id,
        "journal_entries": entries,
        "passed":   sum(1 for v in validations if v.status == "passed"),
        "warnings": sum(1 for v in validations if v.status == "warning"),
        "failed":   sum(1 for v in validations if v.status == "failed"),
        "critical": sum(1 for v in validations if v.severity == "critical"),
    }
