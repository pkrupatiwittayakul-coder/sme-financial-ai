"""File upload endpoint — requires authentication."""
import os
import shutil
from fastapi import APIRouter, UploadFile, File as FastFile, Depends, Form, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db, File as FileModel, RawRecord
from backend.config import UPLOAD_DIR
from backend.services.file_parser import parse_file
from backend.services.file_classifier import classify_file
from backend.services.auth_service import get_current_user
from backend.services.ownership import assert_period_owned
import json

router = APIRouter()


@router.post("/")
async def upload_file(
    period_id: int = Form(...),
    file: UploadFile = FastFile(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload a raw SME file (Excel / CSV / ODS / TSV). Auth required."""
    # Ownership check
    assert_period_owned(period_id, current_user.id, db)

    # Save to disk
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(UPLOAD_DIR, f"p{period_id}_{file.filename}")
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)

    # Parse
    try:
        rows, columns = parse_file(dest)
    except Exception as e:
        raise HTTPException(422, f"Could not parse file: {e}")

    # Classify
    file_type, business_process, confidence = classify_file(file.filename, columns, rows[:20])

    # Persist file metadata
    db_file = FileModel(
        period_id=period_id,
        filename=file.filename,
        path=dest,
        file_type=file_type,
        business_process=business_process,
        classification_confidence=confidence,
        row_count=len(rows),
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    # Persist raw records
    for i, row in enumerate(rows):
        rr = RawRecord(file_id=db_file.id, row_number=i + 1, raw_data=row)
        db.add(rr)
    db.commit()

    return {
        "file_id": db_file.id,
        "filename": file.filename,
        "file_type": file_type,
        "business_process": business_process,
        "classification_confidence": round(confidence, 3),
        "row_count": len(rows),
        "columns": columns,
    }
