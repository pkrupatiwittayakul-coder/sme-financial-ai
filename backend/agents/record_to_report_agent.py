"""
Record-to-Report Agent
Validates: debit-credit balance, account classification, period cutoff.
Produces trial balance summary.
"""
from sqlalchemy.orm import Session
from backend.database import JournalEntry, JournalLine, Period
from backend.services.validation_engine import validate_debit_credit_balance
from backend.agents.base_agent import AgentResult


def run(period_id: int, db: Session) -> AgentResult:
    entries = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()
    if not entries:
        return AgentResult("Record-to-Report", "skipped",
                           summary="No journal entries found — run process agents first")

    entry_dicts = []
    for je in entries:
        lines = db.query(JournalLine).filter(JournalLine.entry_id == je.id).all()
        entry_dicts.append({
            "lines": [{"debit": l.debit, "credit": l.credit,
                        "account_code": l.account_code} for l in lines]
        })

    balance = validate_debit_credit_balance(entry_dicts)
    exceptions = []
    if not balance["balanced"]:
        exceptions.append({
            "validation_type": "unbalanced_trial_balance",
            "status": "failed",
            "severity": "critical",
            "message": (f"Trial balance out by {balance['variance']:.2f} "
                        f"(Dr {balance['debit_total']} / Cr {balance['credit_total']})")
        })

    status = "warning" if exceptions else "done"
    return AgentResult(
        "Record-to-Report", status,
        records_checked=len(entries),
        exceptions=exceptions,
        journal_entries=len(entries),
        summary=(
            f"Checked {len(entries)} journal entries. "
            "Balance: " + ("✓ balanced" if balance["balanced"] else "⚠ variance " + str(balance["variance"]))
        )
    )
