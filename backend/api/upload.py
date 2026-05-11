"""File upload endpoint."""
import os
import shutil
from fastapi import APIRouter, UploadFile, File as FastFile, Depends, Form
from sqlalchemy.orm import Session
from backend.database import get_db, File as FileModel, RawRecord
from backend.config import UPLOAD_DIR
from backend.services.file_parser import parse_file
from backend.services.file_classifier import classify_file
import json

router = APIRouter()


@router.post("/")
async def upload_file(
    period_id: int = Form(...),
    file: UploadFile = FastFile(...),
    db: Session = Depends(get_db),
):
    # Save the file to disk
    dest_path = os.path.join(UPLOAD_DIR, f"p{period_id}_{file.filename}")
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Parse
    try:
        rows, columns, row_count = parse_file(dest_path)
    except Exception as e:
        return {"error": str(e), "filename": file.filename}

    # Classify
    file_type, business_process, confidence = classify_file(file.filename, columns)

    # Save file metadata
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

    # Save raw records
    for i, row in enumerate(rows):
        raw = RawRecord(file_id=db_file.id, row_number=i, raw_data=row)
        db.add(raw)
    db.commit()

    return {
        "file_id": db_file.id,
        "filename": file.filename,
        "file_type": file_type,
        "business_process": business_process,
        "classification_confidence": confidence,
        "row_count": row_count,
        "columns": columns,
        "sample_rows": rows[:3],
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
