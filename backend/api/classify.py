"""Reclassify a file (user override). Auth required."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from backend.database import get_db, File as FileModel
from backend.services.auth_service import get_current_user
from backend.services.ownership import assert_file_owned

router = APIRouter()


class ClassifyOverride(BaseModel):
    file_type: str
    business_process: str


@router.post("/{file_id}")
def override_classification(
    file_id: int,
    data: ClassifyOverride,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    f = assert_file_owned(file_id, current_user.id, db)
    f.file_type = data.file_type
    f.business_process = data.business_process
    f.classification_confidence = 1.0   # user-confirmed
    db.commit()
    return {"file_id": file_id, "file_type": f.file_type, "business_process": f.business_process}
