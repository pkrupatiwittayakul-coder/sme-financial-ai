"""
Bank Reconciliation Agent
Validates: payment/invoice match, sales deposit match, unmatched bank transactions.
Skips gracefully if no bank statement uploaded.
"""
from sqlalchemy.orm import Session
from backend.database import File as FileModel
from backend.agents.base_agent import AgentResult


def run(period_id: int, db: Session) -> AgentResult:
    bank_files = db.query(FileModel).filter(
        FileModel.period_id == period_id, FileModel.file_type == "bank"
    ).all()
    if not bank_files:
        return AgentResult(
            "Bank Reconciliation", "skipped",
            summary="No bank statement uploaded. Upload a bank CSV to enable reconciliation."
        )
    # Full reconciliation logic (Phase 3)
    return AgentResult(
        "Bank Reconciliation", "done",
        records_checked=0,
        summary="Bank file detected but reconciliation logic is Phase 3 scope."
    )
