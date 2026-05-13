"""Schema mapping endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from backend.database import get_db, File as FileModel, RawRecord, ColumnMapping
from backend.services.schema_mapper import (
    map_columns_rule_based, map_columns_with_llm, merge_mappings
)
from backend.services.file_parser import parse_file

router = APIRouter()


class MappingApproval(BaseModel):
    mappings: List[dict]  # [{raw_column, standard_field, approved}]


@router.post("/suggest/{file_id}")
def suggest_mapping(file_id: int, use_llm: bool = False, db: Session = Depends(get_db)):
    """Suggest column mappings for a file."""
    f = db.query(FileModel).get(file_id)
    if not f:
        raise HTTPException(404, "File not found")

    # Get columns from raw records
    sample = db.query(RawRecord).filter(RawRecord.file_id == file_id).limit(5).all()
    if not sample:
        raise HTTPException(400, "No raw records found. Upload file first.")

    columns = list(sample[0].raw_data.keys())
    sample_rows = [r.raw_data for r in sample]

    # Rule-based mapping
    rule_mappings = map_columns_rule_based(f.file_type, columns)

    # LLM mapping for low-confidence columns
    llm_mappings = []
    low_conf_cols = [m["raw_column"] for m in rule_mappings if m["confidence"] < 0.6]
    if use_llm and low_conf_cols:
        llm_mappings = map_columns_with_llm(f.file_type, low_conf_cols, sample_rows)

    final = merge_mappings(rule_mappings, llm_mappings)

    # Save suggestions to DB (unapproved)
    db.query(ColumnMapping).filter(ColumnMapping.file_id == file_id).delete()
    for m in final:
        cm = ColumnMapping(
            file_id=file_id,
            raw_column=m["raw_column"],
            standard_field=m["standard_field"],
            confidence=m["confidence"],
            approved=0,
        )
        db.add(cm)
    db.commit()

    return {
        "file_id": file_id,
        "file_type": f.file_type,
        "mappings": final,
        "sample_rows": sample_rows[:3],
    }


@router.post("/confirm/{file_id}")
def confirm_mapping(
    file_id: int,
    data: MappingApproval,
    db: Session = Depends(get_db),
):
    """User confirms/edits the column mappings."""
    f = db.query(FileModel).get(file_id)
    if not f:
        raise HTTPException(404, "File not found")

    # Clear existing
    db.query(ColumnMapping).filter(ColumnMapping.file_id == file_id).delete()

    for m in data.mappings:
        cm = ColumnMapping(
            file_id=file_id,
            raw_column=m["raw_column"],
            standard_field=m.get("standard_field", "unknown"),
            confidence=m.get("confidence", 1.0),
            approved=1 if m.get("approved", True) else -1,
        )
        db.add(cm)
    db.commit()

    return {"file_id": file_id, "mappings_saved": len(data.mappings), "status": "confirmed"}


@router.get("/mappings/{file_id}")
def get_mappings(file_id: int, db: Session = Depends(get_db)):
    mappings = db.query(ColumnMapping).filter(ColumnMapping.file_id == file_id).all()
    return [
        {
            "id": m.id,
            "raw_column": m.raw_column,
            "standard_field": m.standard_field,
            "confidence": m.confidence,
            "approved": m.approved,
        }
        for m in mappings
    ]
