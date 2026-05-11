"""Evidence-backed chat agent using Claude Haiku."""
from typing import List, Dict, Any, Optional
import json
import anthropic
from backend.config import ANTHROPIC_API_KEY, LLM_MODEL


def build_context(
    income_statement: Optional[Dict],
    trial_balance: Optional[List[Dict]],
    validations: Optional[List[Dict]],
    importance_scores: Optional[List[Dict]],
    period_label: str,
) -> str:
    """Build a compact context string for the LLM."""
    parts = [f"## Reporting Period: {period_label}\n"]

    if income_statement:
        s = income_statement.get("summary", {})
        parts.append("## Income Statement Summary")
        parts.append(f"- Revenue: {s.get('revenue', 0):,.2f}")
        parts.append(f"- Cost of Goods Sold: {s.get('cogs', 0):,.2f}")
        parts.append(f"- Gross Profit: {s.get('gross_profit', 0):,.2f} ({s.get('gross_margin_pct', 0):.1f}% margin)")
        parts.append(f"- Operating Expenses: {s.get('operating_expenses', 0):,.2f}")
        parts.append(f"- Waste: {s.get('waste', 0):,.2f}")
        parts.append(f"- Net Profit: {s.get('net_profit', 0):,.2f}\n")

    if trial_balance:
        parts.append("## Trial Balance (top accounts by activity)")
        for row in sorted(trial_balance, key=lambda x: -abs(x.get("net_balance", 0)))[:8]:
            parts.append(
                f"  [{row['account_code']}] {row['account_name']}: "
                f"Dr {row['total_debit']:,.0f} / Cr {row['total_credit']:,.0f} "
                f"(Net {row['net_balance']:,.0f}, {row['entry_count']} entries)"
            )
        parts.append("")

    if validations:
        critical = [v for v in validations if v.get("severity") == "critical"]
        warnings = [v for v in validations if v.get("status") == "warning"]
        parts.append(f"## Validation Summary: {len(critical)} critical issues, {len(warnings)} warnings")
        for v in critical[:5]:
            parts.append(f"  ⚠ CRITICAL: {v['message']}")
        parts.append("")

    if importance_scores:
        top = sorted(importance_scores, key=lambda x: -x.get("total_score", 0))[:5]
        parts.append("## Top Risk Records")
        for s in top:
            parts.append(f"  - {s['object_type']} #{s['object_id']}: score={s['total_score']} ({s['level']}) — {s['reason'][:80]}")
        parts.append("")

    return "\n".join(parts)


SYSTEM_PROMPT = """You are an AI financial analyst assistant for a Thai SME.
You help business owners and accountants understand their financial data.

Rules:
- Only answer based on the provided financial context. Do not invent numbers.
- If the context does not contain enough data to answer, say so clearly.
- Always cite which data supports your answer (e.g., "Based on the Income Statement...")
- Speak in plain English. Avoid accounting jargon unless explaining it.
- If there are validation issues or risks relevant to the question, mention them.
- Be concise but complete. Use bullet points for lists of findings.
"""


def ask_chat(
    user_message: str,
    conversation_history: List[Dict],
    context: str,
) -> Dict:
    """
    Send a message to Claude Haiku with financial context.
    Returns {answer, evidence_summary, model_used}
    """
    if not ANTHROPIC_API_KEY:
        return {
            "answer": "⚠️ No Anthropic API key configured. Please add ANTHROPIC_API_KEY to your .env file.",
            "evidence_summary": [],
            "model_used": "none",
        }

    # Build message history
    messages = []
    for msg in conversation_history[-10:]:   # last 10 turns for context
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Add context as a system-like user message if first turn
    full_user_message = user_message
    if not conversation_history:
        full_user_message = (
            f"Here is the current financial data context:\n\n{context}\n\n"
            f"User question: {user_message}"
        )
    else:
        # Append context reminder for subsequent turns
        full_user_message = (
            f"[Context refreshed]\n{context}\n\nUser: {user_message}"
        )

    messages.append({"role": "user", "content": full_user_message})

    try:
        import httpx, os, ssl
        # Use HTTP proxy if set; disable SSL verify when proxy uses self-signed cert (dev/sandbox only)
        http_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if http_proxy:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            http_client = httpx.Client(proxy=http_proxy, verify=False)
        else:
            http_client = None
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=http_client)
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        answer = response.content[0].text

        # Simple evidence extraction (what the answer references)
        evidence = []
        evidence_keywords = ["revenue", "cogs", "gross profit", "validation",
                             "critical", "warnin