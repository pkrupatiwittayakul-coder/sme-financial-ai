"""Reclassify a file (user override)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from backend.database import get_db, File as FileModel

router = APIRouter()


class ClassifyOverride(BaseModel):
    file_type: str
    business_process: str


@router.post("/{file_id}")
def override_classification(
    file_id: int,
    data: ClassifyOverride,
    db: Session = Depends(get_db),
):
    f = db.query(FileModel).get(file_id)
    if not f:
        raise HTTPException(404, "File not found")
    f.file_type = data.file_type
    f.business_process = data.business_process
    f.classification_confidence = 1.0   # User confirmed
    db.commit()
    return {"file_id": file_id, "file_type": f.file_type, "status": "updated"}
