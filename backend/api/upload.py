"""File upload endpoints."""
import os
import shutil
from fastapi import APIRouter, UploadFile, File as FastFile, Depends, Form, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db, File as FileModel, RawRecord, Company
from backend.config import UPLOAD_DIR
from backend.services.file_parser import parse_file
from backend.services.file_classifier import classify_file

router = APIRouter()


def _parse_and_save_file(company_id: int, period_id: int, file, db: Session):
    """Parse uploaded file, store raw records, return (db_file, rows, columns)."""
    dest_path = os.path.join(UPLOAD_DIR, f"c{company_id}_p{period_id}_{file.filename}")
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        rows, columns, row_count = parse_file(dest_path)
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")

    file_type, business_process, confidence = classify_file(file.filename, columns)

    db_file = FileModel(
        period_id=period_id,
        filename=file.filename,
        path=dest_path,
        file_type=file_type,
        business_process=business_process,
        classification_confidence=confidence,
        row_count=row_count,
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    for i, row in enumerate(rows):
        db.add(RawRecord(file_id=db_file.id, row_number=i, raw_data=row))
    db.commit()

    return db_file, rows, columns


@router.post("/auto")
async def upload_and_process(
    company_id: int = Form(...),
    file: UploadFile = FastFile(...),
    db: Session = Depends(get_db),
):
    """
    All-in-one upload endpoint.
    1. Ensure period exists for company
    2. Parse file + save raw records
    3. Auto-map schema columns
    4. Run full pipeline (extract → validate → journal → statements → ontology)
    Returns complete results — no manual steps needed.
    """
    # Verify company exists
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(404, "Company not found")

    # Get or create period
    from backend.api.companies import _get_or_create_period
    period = _get_or_create_period(company_id, db)
    period_id = period.id

    # Parse and save file
    db_file, rows, columns = _parse_and_save_file(company_id, period_id, file, db)

    # Auto-map schema
    from backend.database import ColumnMapping
    from backend.services.schema_mapper import map_columns_rule_based, map_columns_with_llm, merge_mappings

    rule_mappings = map_columns_rule_based(db_file.file_type, columns)
    low_conf = [m["raw_column"] for m in rule_mappings if m["confidence"] < 0.70]
    llm_mappings = []
    if low_conf:
        sample_rows = rows[:5]
        try:
            llm_mappings = map_columns_with_llm(db_file.file_type, low_conf, sample_rows)
        except Exception:
            pass

    final = merge_mappings(rule_mappings, llm_mappings)
    db.query(ColumnMapping).filter(ColumnMapping.file_id == db_file.id).delete()
    for m in final:
        db.add(ColumnMapping(
            file_id=db_file.id,
            raw_column=m["raw_column"],
            standard_field=m["standard_field"],
            confidence=m["confidence"],
            approved=1,
        ))
    db.commit()

    # Run full pipeline
    from backend.api.pipeline import run_pipeline_internal
    result = run_pipeline_internal(period_id, db)

    return {
        "file_id": db_file.id,
        "filename": db_file.filename,
        "file_type": db_file.file_type,
        "row_count": db_file.row_count,
        "period_id": period_id,
        "period_label": result.get("period_label", period.label),
        **result,
    }


@router.get("/files/{period_id}")
def list_files(period_id: int, db: Session = Depends(get_db)):
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    return [
        {
            "id": f.id,
            "filename": f.filename,
            "file_type": f.file_type,
            "business_process": f.business_process,
            "classification_confidence": f.classification_confidence,
            "row_count": f.row_count,
        }
        for f in files
    ]
