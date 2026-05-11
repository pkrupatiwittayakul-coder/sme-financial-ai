"""
Sales / Order-to-Cash Agent
Validates: branch exists, SKU exists, revenue mapping, discount anomaly, cash/card split.
"""
from sqlalchemy.orm import Session
from backend.database import (
    BusinessRecord, ValidationResult, JournalEntry, JournalLine, File as FileModel
)
from backend.services.validation_engine import validate_records, summarize_validations
from backend.services.accounting_mapper import map_all_records
from backend.agents.base_agent import AgentResult


def run(period_id: int, db: Session) -> AgentResult:
    files = db.query(FileModel).filter(
        FileModel.period_id == period_id, FileModel.file_type == "sales"
    ).all()
    if not files:
        return AgentResult("Sales/OtC", "skipped", summary="No sales files uploaded")

    all_records, exceptions, entries_created = [], [], 0

    for f in files:
        records = db.query(BusinessRecord).filter(BusinessRecord.file_id == f.id).all()
        rec_dicts = [{"id": r.id, "record_type": r.record_type, "date": r.date,
                      "amount": r.amount, "normalized_data": r.normalized_data} for r in records]
        all_records.extend(rec_dicts)

        # Validate
        results = validate_records(rec_dicts, "sales", period_id)
        for res in results:
            db.add(ValidationResult(**res))
            if res["status"] in ("warning", "failed"):
                exceptions.append(res)

        # Journal entries
        entries = map_all_records(rec_dicts, period_id)
        for entry in entries:
            je = JournalEntry(
                period_id=period_id, source_record_id=entry["source_record_id"],
                date=entry["date"], description=entry["description"], status="posted"
            )
            db.add(je)
            db.flush()
            for line in entry["lines"]:
                db.add(JournalLine(entry_id=je.id, **{k: line[k] for k in
                    ("account_code","account_name","debit","credit")}))
            entries_created += 1

    db.commit()
    status = "warning" if exceptions else "done"
    return AgentResult(
        "Sales/OtC", status,
        records_checked=len(all_records),
        exceptions=exceptions[:10],
        journal_entries=entries_created,
        summary=f"Validated {len(all_records)} sales records. {len(exceptions)} exceptions."
    )
