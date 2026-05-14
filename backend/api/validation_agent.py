"""
SQ3 — Validation Agent API
==========================
  POST   /api/validate/{period_id}/run      Run the SQ3 native validation agent
  GET    /api/validate/{period_id}          List findings + summary for a period
  PATCH  /api/validate/finding/{finding_id} Acknowledge / dismiss / mark fixed
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db, Period, AgentValidation
from backend.services.validation_agent import run_validation_agent

router = APIRouter()


def _check_period(db: Session, period_id: int) -> Period:
    period = db.query(Period).get(period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    return period


@router.post("/{period_id}/run")
def run_validation(period_id: int, db: Session = Depends(get_db)):
    """Run SQ3 over the period and return the summary + findings."""
    _check_period(db, period_id)
    result = run_validation_agent(db, period_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    result["findings"] = _list_findings(db, period_id)
    return result


@router.get("/{period_id}")
def get_validation(period_id: int, db: Session = Depends(get_db)):
    """Return persisted SQ3 findings + a recomputed summary for a period."""
    _check_period(db, period_id)
    findings = _list_findings(db, period_id)
    return {
        "period_id": period_id,
        "findings_total": len(findings),
        "summary": _summary(findings),
        "findings": findings,
    }


class FindingPatch(BaseModel):
    ack_status: Optional[str] = None   # open / acknowledged / dismissed / fixed
    user_notes: Optional[str] = None


@router.patch("/finding/{finding_id}")
def patch_finding(finding_id: int, patch: FindingPatch, db: Session = Depends(get_db)):
    f = db.query(AgentValidation).get(finding_id)
    if not f:
        raise HTTPException(404, "Finding not found")
    fields = patch.model_dump(exclude_unset=True)
    if "ack_status" in fields:
        if fields["ack_status"] not in ("open", "acknowledged", "dismissed", "fixed"):
            raise HTTPException(400, "Invalid ack_status")
        f.ack_status = fields["ack_status"]
    if "user_notes" in fields:
        f.user_notes = fields["user_notes"]
    db.commit()
    db.refresh(f)
    return {"id": f.id, "ack_status": f.ack_status, "updated": True}


# ── helpers ─────────────────────────────────────────────────────────────────
def _list_findings(db: Session, period_id: int):
    rows = (
        db.query(AgentValidation)
        .filter(AgentValidation.period_id == period_id)
        .order_by(AgentValidation.id.asc())
        .all()
    )
    # Sort: fails first, then warnings, then passes; agent before rule within tier
    sev_rank = {"fail": 0, "warning": 1, "pass": 2}
    rows.sort(key=lambda r: (sev_rank.get(r.status, 3), 0 if r.source == "agent" else 1))
    return [{
        "id": r.id,
        "sequence": r.sequence,
        "standard": r.standard,
        "section_ref": r.section_ref,
        "rule_code": r.rule_code,
        "rule_name": r.rule_name,
        "category": r.category,
        "status": r.status,
        "severity": r.severity,
        "finding": r.finding,
        "recommendation": r.recommendation,
        "affected_entities": r.affected_entities or [],
        "evidence": r.evidence or {},
        "confidence": round(float(r.confidence or 0), 2),
        "source": r.source,
        "ack_status": r.ack_status,
        "user_notes": r.user_notes or "",
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


def _summary(findings):
    from collections import defaultdict
    by_status = defaultdict(int)
    by_severity = defaultdict(int)
    by_category = defaultdict(int)
    open_count = 0
    for f in findings:
        by_status[f["status"]] += 1
        by_severity[f["severity"]] += 1
        by_category[f["category"]] += 1
        if f["ack_status"] == "open":
            open_count += 1
    fails = by_status.get("fail", 0)
    warns = by_status.get("warning", 0)
    passes = by_status.get("pass", 0)
    total = max(1, fails + warns + passes)
    score = round((passes + 0.5 * warns) / total * 100, 1)
    return {
        "by_status": dict(by_status),
        "by_severity": dict(by_severity),
        "by_category": dict(by_category),
        "open_count": open_count,
        "compliance_score": score,
        "verdict": "blocked" if fails else ("review" if warns else "clean"),
    }
