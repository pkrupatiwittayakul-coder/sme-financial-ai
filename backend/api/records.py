"""Record extraction, entity resolution, validation, scoring endpoints. Auth required."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import (
    get_db, File as FileModel, RawRecord, ColumnMapping,
    BusinessRecord, Entity, Relationship, ValidationResult, ImportanceScore,
    JournalEntry, JournalLine
)
from backend.services.record_extractor import extract_records
from backend.services.entity_resolver import extract_entities_from_records
from backend.services.graph_builder import build_graph
from backend.services.validation_engine import validate_records, summarize_validations
from backend.services.importance_scorer import score_all_records
from backend.services.accounting_mapper import map_all_records
from backend.services.auth_service import get_current_user
from backend.services.ownership import assert_file_owned, assert_period_owned

router = APIRouter()


@router.post("/extract/{file_id}")
def extract_business_records(
    file_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Convert raw rows to typed BusinessRecord objects."""
    f = assert_file_owned(file_id, current_user.id, db)

    approved = db.query(ColumnMapping).filter(
        ColumnMapping.file_id == file_id,
        ColumnMapping.approved >= 0
    ).all()
    if not approved:
        raise HTTPException(422, "No column mappings found — run /schema/suggest first")

    mapping = {m.raw_column: m.standard_field for m in approved}
    raw_rows = db.query(RawRecord).filter(RawRecord.file_id == file_id).all()
    raw_dicts = [{"id": r.id, "row_number": r.row_number, **r.raw_data} for r in raw_rows]

    records = extract_records(raw_dicts, mapping, f.file_type)

    # Persist
    db.query(BusinessRecord).filter(BusinessRecord.file_id == file_id).delete()
    for rec in records:
        db.add(BusinessRecord(
            file_id=file_id,
            raw_record_id=rec.get("raw_record_id"),
            record_type=rec.get("record_type"),
            date=rec.get("date"),
            amount=rec.get("amount", 0),
            normalized_data=rec.get("normalized_data", {}),
        ))
    db.commit()

    return {"file_id": file_id, "records_extracted": len(records)}


@router.post("/graph/{period_id}")
def build_period_graph(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Build entity graph for all records in a period."""
    assert_period_owned(period_id, current_user.id, db)

    # Get all business records for the period via file→period join
    from backend.database import Period, File as F
    period = db.get(Period, period_id)
    file_ids = [f.id for f in period.files]
    records = db.query(BusinessRecord).filter(BusinessRecord.file_id.in_(file_ids)).all()
    rec_dicts = [{"id": r.id, "record_type": r.record_type, "date": r.date,
                  "amount": r.amount, "normalized_data": r.normalized_data} for r in records]

    # Resolve entities
    entities = extract_entities_from_records(rec_dicts)
    db.query(Entity).filter(Entity.period_id == period_id).delete()
    entity_map = {}
    for e in entities:
        obj = Entity(period_id=period_id, entity_type=e["type"],
                     entity_name=e["name"], attributes=e.get("attributes", {}))
        db.add(obj)
        db.flush()
        entity_map[e["key"]] = obj.id

    # Build relationships
    db.query(Relationship).filter(Relationship.source_entity_id.in_(
        [eid for eid in entity_map.values()]
    )).delete(synchronize_session=False)
    edges = build_graph(rec_dicts, entity_map)
    for edge in edges:
        db.add(Relationship(
            source_entity_id=edge["source"],
            relationship_type=edge["type"],
            target_entity_id=edge["target"],
            evidence=edge.get("evidence", ""),
            business_record_id=edge.get("record_id"),
        ))
    db.commit()

    return {"period_id": period_id, "entities": len(entities), "relationships": len(edges)}


@router.post("/validate/{file_id}")
def run_validation(
    file_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run deterministic validation checks on all business records."""
    f = assert_file_owned(file_id, current_user.id, db)

    records = db.query(BusinessRecord).filter(BusinessRecord.file_id == file_id).all()
    if not records:
        raise HTTPException(422, "No business records found — run /extract first")

    rec_dicts = [{"id": r.id, "record_type": r.record_type, "normalized_data": r.normalized_data,
                  "amount": r.amount} for r in records]
    results = validate_records(rec_dicts, f.file_type, f.period_id)

    db.query(ValidationResult).filter(
        ValidationResult.business_record_id.in_([r.id for r in records])
    ).delete(synchronize_session=False)
    for res in results:
        db.add(ValidationResult(**res))
    db.commit()

    return {"file_id": file_id, **summarize_validations(results), "total": len(results)}


@router.post("/score/{file_id}")
def run_scoring(
    file_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Calculate importance/risk scores for all business records."""
    assert_file_owned(file_id, current_user.id, db)

    records = db.query(BusinessRecord).filter(BusinessRecord.file_id == file_id).all()
    validations = db.query(ValidationResult).filter(
        ValidationResult.business_record_id.in_([r.id for r in records])
    ).all()

    rec_dicts = [{"id": r.id, "record_type": r.record_type, "normalized_data": r.normalized_data,
                  "amount": r.amount} for r in records]
    val_dicts = [{"business_record_id": v.business_record_id, "status": v.status,
                  "severity": v.severity} for v in validations]

    scores = score_all_records(rec_dicts, val_dicts)
    db.query(ImportanceScore).filter(
        ImportanceScore.object_id.in_([r.id for r in records]),
        ImportanceScore.object_type == "record"
    ).delete(synchronize_session=False)
    for s in scores:
        db.add(ImportanceScore(
            object_type="record",
            object_id=s["record_id"],
            total_score=s["total_score"],
            level=s["level"],
            reason=s["reason"],
        ))
    db.commit()

    critical = sum(1 for s in scores if s["level"] == "Critical")
    high = sum(1 for s in scores if s["level"] == "High")
    return {"file_id": file_id, "scored": len(scores), "critical": critical, "high": high}


@router.post("/journal/{file_id}")
def create_journal_entries(
    file_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Map validated business records to double-entry journal entries."""
    f = assert_file_owned(file_id, current_user.id, db)

    records = db.query(BusinessRecord).filter(BusinessRecord.file_id == file_id).all()
    if not records:
        raise HTTPException(422, "No business records — run /extract first")

    rec_dicts = [{"id": r.id, "record_type": r.record_type, "date": r.date,
                  "amount": r.amount, "normalized_data": r.normalized_data} for r in records]
    entries = map_all_records(rec_dicts, f.period_id)

    # Delete old entries for this file
    old_entries = db.query(JournalEntry).filter(
        JournalEntry.source_record_id.in_([r.id for r in records])
    ).all()
    for oe in old_entries:
        db.query(JournalLine).filter(JournalLine.entry_id == oe.id).delete()
        db.delete(oe)
    db.commit()

    for entry in entries:
        je = JournalEntry(
            period_id=f.period_id,
            source_record_id=entry["source_record_id"],
            date=entry["date"],
            description=entry["description"],
            status=entry["status"],
        )
        db.add(je)
        db.flush()
        for line in entry["lines"]:
            db.add(JournalLine(
                entry_id=je.id,
                account_code=line["account_code"],
                account_name=line["account_name"],
                debit=line["debit"],
                credit=line["credit"],
            ))
    db.commit()
    return {"file_id": file_id, "journal_entries_created": len(entries)}
