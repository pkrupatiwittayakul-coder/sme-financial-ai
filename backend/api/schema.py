"""Schema mapping endpoints. Auth required."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from backend.database import get_db, File as FileModel, RawRecord, ColumnMapping
from backend.services.schema_mapper import map_columns_rule_based, map_columns_with_llm, merge_mappings
from backend.services.file_parser import parse_file
from backend.services.auth_service import get_current_user
from backend.services.ownership import assert_file_owned

router = APIRouter()


class MappingApproval(BaseModel):
    mappings: List[dict]  # [{raw_column, standard_field, approved}]


@router.post("/suggest/{file_id}")
def suggest_mapping(
    file_id: int,
    use_llm: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Suggest standard field mappings for raw columns. Skips LLM when rule confidence ≥ 0.90."""
    f = assert_file_owned(file_id, current_user.id, db)

    sample_rows = db.query(RawRecord).filter(RawRecord.file_id == file_id).limit(5).all()
    if not sample_rows:
        raise HTTPException(422, "No raw records found — upload the file first")

    columns = list(sample_rows[0].raw_data.keys()) if sample_rows else []
    sample_data = [r.raw_data for r in sample_rows]

    # Rule-based first
    rule_mappings = map_columns_rule_based(columns)

    # Only call LLM if explicitly requested AND some columns are unmatched
    unmatched = [c for c, m in rule_mappings.items() if m["confidence"] < 0.90]
    if use_llm and unmatched:
        llm_mappings = map_columns_with_llm(columns, sample_data, f.file_type)
        final_mappings = merge_mappings(rule_mappings, llm_mappings)
    else:
        final_mappings = rule_mappings

    # Persist to DB (upsert)
    for raw_col, info in final_mappings.items():
        existing = db.query(ColumnMapping).filter(
            ColumnMapping.file_id == file_id,
            ColumnMapping.raw_column == raw_col
        ).first()
        if existing:
            existing.standard_field = info["standard_field"]
            existing.confidence = info["confidence"]
        else:
            db.add(ColumnMapping(
                file_id=file_id,
                raw_column=raw_col,
                standard_field=info["standard_field"],
                confidence=info["confidence"],
                approved=0,
            ))
    db.commit()

    return {
        "file_id": file_id,
        "llm_used": use_llm and bool(unmatched),
        "mappings": [
            {
                "raw_column": rc,
                "standard_field": info["standard_field"],
                "confidence": round(info["confidence"], 3),
                "approved": 0,
            }
            for rc, info in final_mappings.items()
        ],
    }


@router.post("/confirm/{file_id}")
def confirm_mapping(
    file_id: int,
    data: MappingApproval,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """User confirms or edits column mappings."""
    assert_file_owned(file_id, current_user.id, db)

    updated = 0
    for m in data.mappings:
        existing = db.query(ColumnMapping).filter(
            ColumnMapping.file_id == file_id,
            ColumnMapping.raw_column == m["raw_column"]
        ).first()
        if existing:
            existing.standard_field = m.get("standard_field", existing.standard_field)
            existing.approved = m.get("approved", 1)
            updated += 1
    db.commit()
    return {"file_id": file_id, "mappings_updated": updated}
