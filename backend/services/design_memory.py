"""
Design Memory layer
====================
A small backend system that keeps the entity-design step accurate and cheap.

For every uploaded file we compute a *fingerprint* of (file_type + sorted
columns).  When the LLM returns a clean design and the user approves it,
we persist the design under that fingerprint.  On the next upload that
matches the fingerprint we return the cached design instantly — no API
call, no drift, no hallucinated entity names.

This is the "backend system to keep accuracy" referenced in the spec.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import List, Dict, Optional

from sqlalchemy.orm import Session
from backend.database import DesignMemory


def _fingerprint(file_type: str, columns: List[str]) -> str:
    sig_cols = sorted([str(c).strip().lower() for c in columns if c])
    raw = f"{(file_type or '').lower()}|{'|'.join(sig_cols)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def lookup(
    db: Session, file_type: str, columns: List[str], user_id: Optional[int] = None
) -> Optional[Dict]:
    """Return cached design payload if a matching fingerprint exists."""
    fp = _fingerprint(file_type, columns)
    q = db.query(DesignMemory).filter(DesignMemory.fingerprint == fp)
    if user_id is not None:
        # Prefer the user's own cache hits; fall back to global ones.
        own = q.filter(DesignMemory.user_id == user_id).first()
        if own:
            own.hit_count = (own.hit_count or 0) + 1
            own.last_used = datetime.utcnow()
            db.commit()
            return _decorate(own)
    row = q.order_by(DesignMemory.hit_count.desc()).first()
    if not row:
        return None
    row.hit_count = (row.hit_count or 0) + 1
    row.last_used = datetime.utcnow()
    db.commit()
    return _decorate(row)


def remember(
    db: Session,
    file_type: str,
    columns: List[str],
    payload: Dict,
    user_id: Optional[int] = None,
) -> DesignMemory:
    """Persist (or update) an approved design under the input's fingerprint."""
    fp = _fingerprint(file_type, columns)
    cols_sig = json.dumps(sorted([str(c).strip().lower() for c in columns if c]))
    row = (
        db.query(DesignMemory)
        .filter(DesignMemory.fingerprint == fp, DesignMemory.user_id == user_id)
        .first()
    )
    if row:
        row.payload = payload
        row.columns_signature = cols_sig
        row.last_used = datetime.utcnow()
        row.hit_count = (row.hit_count or 0) + 1
    else:
        row = DesignMemory(
            user_id=user_id,
            fingerprint=fp,
            file_type=file_type or "unknown",
            columns_signature=cols_sig,
            payload=payload,
            hit_count=1,
            last_used=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def stats(db: Session, user_id: Optional[int] = None) -> Dict:
    q = db.query(DesignMemory)
    if user_id is not None:
        q = q.filter(DesignMemory.user_id == user_id)
    rows = q.all()
    return {
        "entries": len(rows),
        "total_hits": sum((r.hit_count or 0) for r in rows),
        "file_types": sorted({r.file_type for r in rows}),
    }


def _decorate(row: DesignMemory) -> Dict:
    return {
        "fingerprint": row.fingerprint,
        "file_type": row.file_type,
        "payload": row.payload,
        "hit_count": row.hit_count or 0,
        "last_used": row.last_used.isoformat() if row.last_used else None,
        "source": "memory",
    }
