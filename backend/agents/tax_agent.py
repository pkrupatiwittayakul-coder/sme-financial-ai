"""
Tax Agent
Validates: missing VAT, zero-tax on taxable lines, WHT, abnormal VAT rates.
"""
from sqlalchemy.orm import Session
from backend.database import BusinessRecord, ValidationResult, File as FileModel
from backend.services.validation_engine import validate_tax_records
from backend.agents.base_agent import AgentResult


def run(period_id: int, db: Session) -> AgentResult:
    # Collect all records across sales + purchase files
    files = db.query(FileModel).filter(
        FileModel.period_id == period_id,
        FileModel.file_type.in_(["sales", "purchase"])
    ).all()
    if not files:
        return AgentResult("Tax Agent", "skipped", summary="No taxable files found")

    all_records, exceptions = [], []
    for f in files:
        records = db.query(BusinessRecord).filter(BusinessRecord.file_id == f.id).all()
        rec_dicts = [{"id": r.id, "record_type": r.record_type, "date": r.date,
                      "amount": r.amount, "normalized_data": r.normalized_data} for r in records]
        all_records.extend(rec_dicts)

        results = validate_tax_records(rec_dicts, period_id)
        for res in results:
            db.add(ValidationResult(**res))
            if res["status"] in ("warning", "failed"):
                exceptions.append(res)

    db.commit()
    status = "warning" if exceptions else "done"
    return AgentResult(
        "Tax Agent", status,
        records_checked=len(all_records),
        exceptions=exceptions[:10],
        summary=f"Tax-checked {len(all_records)} records. {len(exceptions)} VAT/WHT exceptions."
    )
