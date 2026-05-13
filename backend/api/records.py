"""Record extraction, entity resolution, validation, scoring endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import (
    get_db, File as FileModel, RawRecord, ColumnMapping,
    BusinessRecord, Entity, ValidationResult, ImportanceScore,
    JournalEntry, JournalLine
)
from backend.services.record_extractor import extract_records
from backend.services.entity_resolver import extract_entities_from_records
from backend.services.validation_engine import validate_records, summarize_validations
from backend.services.importance_scorer import score_all_records
from backend.services.accounting_mapper import map_all_records

router = APIRouter()


@router.post("/extract/{file_id}")
def extract_business_records(file_id: int, db: Session = Depends(get_db)):
    """Convert raw rows to business records using approved mappings."""
    f = db.query(FileModel).get(file_id)
    if not f:
        raise HTTPException(404, "File not found")

    mappings = db.query(ColumnMapping).filter(
        ColumnMapping.file_id == file_id,
        ColumnMapping.approved >= 0,
    ).all()
    if not mappings:
        raise HTTPException(400, "No approved mappings. Run /schema/suggest and /schema/confirm first.")

    raw_records = db.query(RawRecord).filter(RawRecord.file_id == file_id).all()
    rows = [r.raw_data for r in raw_records]

    mapping_dicts = [{"raw_column": m.raw_column, "standard_field": m.standard_field} for m in mappings]

    # Extract
    extracted = extract_records(f.file_type, rows, mapping_dicts, file_id)

    # Delete old business records for this file
    old_ids = [br.id for br in db.query(BusinessRecord).filter(BusinessRecord.file_id == file_id).all()]
    if old_ids:
        db.query(ValidationResult).filter(ValidationResult.business_record_id.in_(old_ids)).delete(synchronize_session=False)
        db.query(ImportanceScore).filter(
            ImportanceScore.object_type.in_(["SalesTransaction", "SupplierInvoice", "InventoryMovement", "ChartOfAccount"]),
            ImportanceScore.object_id.in_(old_ids)
        ).delete(synchronize_session=False)
        db.query(JournalEntry).filter(JournalEntry.source_record_id.in_(old_ids)).delete(synchronize_session=False)
    db.query(BusinessRecord).filter(BusinessRecord.file_id == file_id).delete()
    db.commit()

    # Save new records
    saved_records = []
    for rec_data in extracted:
        br = BusinessRecord(
            file_id=rec_data["file_id"],
            record_type=rec_data["record_type"],
            date=rec_data["date"],
            amount=rec_data["amount"],
            normalized_data=rec_data["normalized_data"],
        )
        db.add(br)
        db.flush()
        rec_data["id"] = br.id
        saved_records.append(rec_data)
    db.commit()

    return {
        "file_id": file_id,
        "file_type": f.file_type,
        "records_extracted": len(saved_records),
    }


@router.post("/process/{period_id}")
def full_process_period(period_id: int, db: Session = Depends(get_db)):
    """
    Run the full pipeline for a period:
    validate -> score -> map to journals.
    """
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    all_records = []
    for f in files:
        recs = db.query(BusinessRecord).filter(BusinessRecord.file_id == f.id).all()
        for r in recs:
            all_records.append({
                "id": r.id, "file_id": r.file_id,
                "record_type": r.record_type, "date": r.date,
                "amount": r.amount, "normalized_data": r.normalized_data,
            })

    if not all_records:
        return {"error": "No business records found. Extract records first."}

    # Group records by file type for validation
    file_type_map = {f.id: f.file_type for f in files}

    # Clear old validation results and scores
    db.query(ValidationResult).filter(ValidationResult.period_id == period_id).delete()
    db.query(ImportanceScore).filter(
        ImportanceScore.object_id.in_([r["id"] for r in all_records])
    ).delete(synchronize_session=False)
    # Clear old journal entries
    old_je_ids = [je.id for je in db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()]
    if old_je_ids:
        db.query(JournalLine).filter(JournalLine.entry_id.in_(old_je_ids)).delete(synchronize_session=False)
    db.query(JournalEntry).filter(JournalEntry.period_id == period_id).delete()
    db.commit()

    # Validate
    all_validations = []
    for f in files:
        recs = [r for r in all_records if r["file_id"] == f.id]
        vresults = validate_records(recs, file_type_map[f.id], period_id)
        all_validations.extend(vresults)

    for v in all_validations:
        db.add(ValidationResult(
            period_id=v["period_id"],
            business_record_id=v.get("business_record_id"),
            validation_type=v["validation_type"],
            status=v["status"],
            severity=v["severity"],
            message=v["message"],
        ))
    db.commit()

    # Importance scoring
    scores = score_all_records(all_records, all_validations)
    for s in scores:
        db.add(ImportanceScore(
            object_type=s["object_type"],
            object_id=s["object_id"],
            total_score=s["total_score"],
            level=s["level"],
            reason=s["reason"],
        ))
    db.commit()

    # Journal entries
    journal_entries = map_all_records(all_records, period_id)
    for entry_data in journal_entries:
        je = JournalEntry(
            period_id=entry_data["period_id"],
            source_record_id=entry_data["source_record_id"],
            date=entry_data["date"],
            description=entry_data["description"],
            status=entry_data["status"],
        )
        db.add(je)
        db.flush()
        for line_data in entry_data["lines"]:
            jl = JournalLine(
                entry_id=je.id,
                account_code=line_data["account_code"],
                account_name=line_data["account_name"],
                debit=line_data["debit"],
                credit=line_data["credit"],
            )
            db.add(jl)
    db.commit()

    val_summary = summarize_validations(all_validations)

    return {
        "period_id": period_id,
        "records_processed": len(all_records),
        "journal_entries_created": len(journal_entries),
        "validation_summary": val_summary,
        "importance_scores_created": len(scores),
    }


@router.get("/list/{period_id}")
def list_records(period_id: int, record_type: str = None, db: Session = Depends(get_db)):
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    file_ids = [f.id for f in files]
    q = db.query(BusinessRecord).filter(BusinessRecord.file_id.in_(file_ids))
    if record_type:
        q = q.filter(BusinessRecord.record_type == record_type)
    recs = q.limit(200).all()
    return [
        {"id": r.id, "record_type": r.record_type, "date": r.date,
         "amount": r.amount, "data": r.normalized_data}
        for r in recs
    ]


@router.get("/validations/{period_id}")
def get_validations(period_id: int, status: str = None, db: Session = Depends(get_db)):
    q = db.query(ValidationResult).filter(ValidationResult.period_id == period_id)
    if status:
        q = q.filter(ValidationResult.status == status)
    results = q.limit(500).all()
    return [
        {"id": r.id, "validation_type": r.validation_type, "status": r.status,
         "severity": r.severity, "message": r.message, "record_id": r.business_record_id}
        for r in results
    ]
