"""User registration and login endpoints."""
import os
import secrets
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.database import get_db, User
from backend.services.auth_service import (
    hash_password, verify_password, create_access_token, get_current_user
)

router = APIRouter()


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    credential: str   # Google ID token (JWT)


def _token_response(user: User) -> dict:
    """Shared helper — always returns access_token field."""
    token = create_access_token(user.id, user.email)
    return {"access_token": token, "name": user.name, "email": user.email, "id": user.id}


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    existing = db.query(User).filter(User.email == data.email.lower()).first()
    if existing:
        raise HTTPException(400, "Email already registered")
    user = User(
        name=data.name,
        email=data.email.lower(),
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """JSON login — accepts {email, password}."""
    user = db.query(User).filter(User.email == data.email.lower()).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return _token_response(user)


@router.post("/token")
def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 form login — used by swagger UI and any form-encoded clients."""
    user = db.query(User).filter(User.email == form_data.username.lower()).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    resp = _token_response(user)
    # OAuth2 spec requires token_type field
    resp["token_type"] = "bearer"
    return resp


@router.post("/google")
def google_login(data: GoogleAuthRequest, db: Session = Depends(get_db)):
    """Verify a Google ID token and return / create an account."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(400, "Google login is not configured on this server. Please set GOOGLE_CLIENT_ID.")

    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as grequests
        idinfo = id_token.verify_oauth2_token(
            data.credential,
            grequests.Request(),
            client_id,
            clock_skew_in_seconds=10,
        )
        email = idinfo["email"]
        name  = idinfo.get("name") or email.split("@")[0]
    except Exception as exc:
        raise HTTPException(401, f"Invalid Google token: {exc}")

    user = db.query(User).filter(User.email == email.lower()).first()
    if not user:
        user = User(
            name=name,
            email=email.lower(),
            password_hash=hash_password(secrets.token_hex(32)),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return _token_response(user)


@router.get("/google-config")
def google_config():
    """Return Google client_id so the frontend can initialise GSI without hardcoding."""
    return {"client_id": os.getenv("GOOGLE_CLIENT_ID", "")}


@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return {"id": current_user.id, "name": current_user.name, "email": current_user.email}
