"""Evidence-backed chat endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.database import (
    get_db, Period, ChatSession, ChatMessage,
    JournalEntry, JournalLine, ValidationResult, ImportanceScore,
    FinancialStatement, StatementLine
)
from backend.services.chat_agent import ask_chat, build_context
from backend.services.statement_generator import generate_trial_balance

router = APIRouter()


class ChatRequest(BaseModel):
    period_id: Optional[int] = None
    session_id: Optional[int] = None
    message: str
    history: Optional[list] = None


@router.post("/")
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    period = db.query(Period).get(data.period_id)
    if not period:
        raise HTTPException(404, "Period not found")

    # Get or create session
    if data.session_id:
        session = db.query(ChatSession).get(data.session_id)
    else:
        session = ChatSession(period_id=data.period_id)
        db.add(session)
        db.commit()
        db.refresh(session)

    # Build context from DB
    entries_orm = db.query(JournalEntry).filter(JournalEntry.period_id == data.period_id).all()
    entries = []
    for e in entries_orm:
        lines = db.query(JournalLine).filter(JournalLine.entry_id == e.id).all()
        entries.append({
            "id": e.id,
            "source_record_id": e.source_record_id,
            "lines": [{"account_code": l.account_code, "account_name": l.account_name,
                        "debit": l.debit, "credit": l.credit} for l in lines],
        })

    trial_balance = generate_trial_balance(entries) if entries else []

    # Income statement summary from DB
    fs = db.query(FinancialStatement).filter(
        FinancialStatement.period_id == data.period_id
    ).order_by(FinancialStatement.id.desc()).first()

    income_statement = None
    if fs:
        stmt_lines = db.query(StatementLine).filter(StatementLine.statement_id == fs.id).all()
        summary = {}
        for l in stmt_lines:
            summary[l.line_type] = l.amount
        income_statement = {
            "summary": {
                "revenue": summary.get("revenue", 0),
                "cogs": summary.get("cogs", 0),
                "gross_profit": summary.get("gross_profit", 0),
                "gross_margin_pct": (
                    summary.get("gross_profit", 0) / summary.get("revenue", 1) * 100
                    if summary.get("revenue", 0) > 0 else 0
                ),
                "operating_expenses": summary.get("expense", 0),
                "waste": 0,
                "net_profit": summary.get("net_profit", 0),
            }
        }

    validations = db.query(ValidationResult).filter(
        ValidationResult.period_id == data.period_id
    ).all()
    val_list = [{"status": v.status, "severity": v.severity, "message": v.message,
                  "business_record_id": v.business_record_id} for v in validations]

    scores = db.query(ImportanceScore).all()
    score_list = [{"object_type": s.object_type, "object_id": s.object_id,
                    "total_score": s.total_score, "level": s.level, "reason": s.reason}
                   for s in scores]

    context = build_context(income_statement, trial_balance, val_list, score_list, period.label)

    # Get conversation history
    history = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.id
    ).order_by(ChatMessage.id).all()
    history_list = [{"role": m.role, "content": m.content} for m in history]

    # Call Claude
    result = ask_chat(data.message, history_list, context)

    # Save messages
    user_msg = ChatMessage(session_id=session.id, role="user", content=data.message, evidence=[])
    db.add(user_msg)
    ai_msg = ChatMessage(
        session_id=session.id, role="assistant",
        content=result["answer"],
        evidence=result["evidence_summary"],
    )
    db.add(ai_msg)
    db.commit()

    return {
        "session_id": session.id,
        "answer": result["answer"],
        "evidence": result["evidence_summary"],
        "model": result["model_used"],
    }


@router.post("/{period_id}")
def chat_by_period(period_id: int, data: ChatRequest, db: Session = Depends(get_db)):
    """Convenience: POST /api/chat/{period_id} with {message, history} body."""
    merged = ChatRequest(
        period_id=period_id,
        session_id=data.session_id,
        message=data.message,
        history=data.history,
    )
    return chat(merged, db)


@router.get("/history/{session_id}")
def get_history(session_id: int, db: Session = Depends(get_db)):
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.id).all()
    return [{"role": m.role, "content": m.content, "evidence": m.evidence,
             "timestamp": str(m.created_at)} for m in messages]
