"""
Sequence 3 — Native Validation Agent
=====================================
Once SQ1 has designed the entities and SQ2 has assembled the ontology graph,
SQ3's job is to *verify and validate* the period's data by reasoning across
that whole structure against an accounting standard.

The standard used here is **TFRS / IFRS for SMEs** (Thai Financial Reporting
Standards for Small and Medium Entities — closely aligned with the IFRS for
SMEs standard).  The agent runs two layers:

  1. Deterministic rule checks (`source="rule"`) — fast, repeatable checks
     mapped to specific TFRS-for-SMEs sections (revenue recognition, inventory
     valuation, cut-off, completeness, classification).

  2. A native LLM reasoning layer (`source="agent"`) — the SQ2 graph
     (entities + their objectives + relationships) plus a digest of the
     deterministic findings is handed to Claude, which reasons about
     structural / standard-level compliance issues a flat rule check would
     miss, and assigns a confidence score to each.

If no API key is configured the agent still returns the full deterministic
layer, so the pipeline never blocks.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Any, Optional

import anthropic
from sqlalchemy.orm import Session

from backend.config import ANTHROPIC_API_KEY, LLM_MODEL
from backend.database import (
    Period, File as FileModel, BusinessRecord,
    JournalEntry, JournalLine, StatementLine, FinancialStatement,
    EntityDesign, EntityRelationDesign, AgentValidation,
)

STANDARD = "TFRS for SMEs"


# ── Public entry point ──────────────────────────────────────────────────────
def run_validation_agent(db: Session, period_id: int) -> Dict[str, Any]:
    """
    Run SQ3 over a period.  Persists AgentValidation rows and returns a
    summary dict.  Existing un-acknowledged findings for the period are
    cleared first so a re-run is idempotent.
    """
    period = db.query(Period).get(period_id)
    if not period:
        return {"period_id": period_id, "error": "Period not found", "findings": []}

    ctx = _load_context(db, period_id)

    # Layer 1 — deterministic rule checks
    findings: List[Dict] = []
    findings += _check_revenue_recognition(ctx)
    findings += _check_inventory_valuation(ctx)
    findings += _check_cutoff(ctx, period)
    findings += _check_completeness(ctx)
    findings += _check_classification(ctx)

    rule_count = len(findings)

    # Layer 2 — native LLM agent reasoning over the graph
    agent_findings: List[Dict] = []
    if ANTHROPIC_API_KEY:
        try:
            agent_findings = _llm_agent_pass(ctx, findings)
        except Exception as exc:  # noqa: BLE001
            print(f"[validation_agent] LLM pass failed: {exc}")
    findings += agent_findings

    # Persist — wipe previous open/agent findings, keep user-acknowledged ones
    db.query(AgentValidation).filter(
        AgentValidation.period_id == period_id,
        AgentValidation.ack_status.in_(["open"]),
    ).delete(synchronize_session=False)
    db.commit()
    db.expire_all()  # drop stale identities so re-runs don't warn

    for f in findings:
        db.add(AgentValidation(
            period_id=period_id,
            sequence=3,
            standard=f.get("standard", STANDARD),
            section_ref=f.get("section_ref", ""),
            rule_code=f.get("rule_code", ""),
            rule_name=f.get("rule_name", ""),
            category=f.get("category", "general"),
            status=f.get("status", "warning"),
            severity=f.get("severity", "warning"),
            finding=f.get("finding", ""),
            recommendation=f.get("recommendation", ""),
            affected_entities=f.get("affected_entities", []),
            evidence=f.get("evidence", {}),
            confidence=float(f.get("confidence", 0.8)),
            source=f.get("source", "rule"),
            ack_status="open",
            created_at=datetime.utcnow(),
        ))
    db.commit()

    return {
        "period_id": period_id,
        "standard": STANDARD,
        "findings_total": len(findings),
        "rule_findings": rule_count,
        "agent_findings": len(agent_findings),
        "summary": _summarize(findings),
        "llm_used": bool(agent_findings),
    }


# ── Context loader ──────────────────────────────────────────────────────────
def _load_context(db: Session, period_id: int) -> Dict[str, Any]:
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    file_ids = [f.id for f in files]
    file_type = {f.id: f.file_type for f in files}

    records: List[Dict] = []
    if file_ids:
        for r in db.query(BusinessRecord).filter(BusinessRecord.file_id.in_(file_ids)).all():
            records.append({
                "id": r.id, "file_id": r.file_id,
                "file_type": file_type.get(r.file_id, "unknown"),
                "record_type": r.record_type, "date": r.date,
                "amount": r.amount or 0.0,
                "nd": r.normalized_data or {},
            })

    journals = []
    for je in db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all():
        lines = db.query(JournalLine).filter(JournalLine.entry_id == je.id).all()
        journals.append({
            "id": je.id, "date": je.date, "description": je.description,
            "source_record_id": je.source_record_id,
            "lines": [{"account_code": l.account_code, "account_name": l.account_name,
                       "debit": l.debit or 0.0, "credit": l.credit or 0.0} for l in lines],
        })

    designs = db.query(EntityDesign).filter(EntityDesign.period_id == period_id).all()
    relations = db.query(EntityRelationDesign).filter(
        EntityRelationDesign.period_id == period_id
    ).all()

    stmt_lines = []
    for fs in db.query(FinancialStatement).filter(FinancialStatement.period_id == period_id).all():
        for sl in db.query(StatementLine).filter(StatementLine.statement_id == fs.id).all():
            stmt_lines.append({
                "statement_type": fs.statement_type,
                "line_name": sl.line_name, "amount": sl.amount or 0.0,
                "account_code": sl.account_code, "line_type": sl.line_type,
            })

    return {
        "period_id": period_id,
        "records": records,
        "journals": journals,
        "designs": designs,
        "relations": relations,
        "statement_lines": stmt_lines,
        "file_types": set(file_type.values()),
    }


# ── Layer 1: deterministic TFRS-for-SMEs rule checks ────────────────────────
def _f(rule_code, rule_name, section_ref, category, status, severity,
       finding, recommendation="", affected=None, evidence=None, conf=0.95):
    return {
        "standard": STANDARD, "section_ref": section_ref,
        "rule_code": rule_code, "rule_name": rule_name, "category": category,
        "status": status, "severity": severity,
        "finding": finding, "recommendation": recommendation,
        "affected_entities": affected or [], "evidence": evidence or {},
        "confidence": conf, "source": "rule",
    }


def _check_revenue_recognition(ctx) -> List[Dict]:
    """TFRS for SMEs Section 23 — Revenue.  Revenue is recognised when the
    significant risks and rewards have transferred and the amount can be
    measured reliably."""
    out = []
    sales = [r for r in ctx["records"] if r["record_type"] == "SalesTransaction"]
    if not sales:
        return out

    # 23.a — every sale must carry a recognition date
    no_date = [r["id"] for r in sales if not r.get("date")]
    if no_date:
        out.append(_f(
            "REV_NO_DATE", "Sales without a recognition date",
            "Section 23 Revenue", "revenue", "fail", "critical",
            f"{len(no_date)} sales record(s) have no transaction date, so the "
            f"period in which revenue should be recognised cannot be determined.",
            "Add a transaction/recognition date to every sales row before posting.",
            affected=["SalesTxn"], evidence={"record_ids": no_date[:25], "count": len(no_date)},
        ))

    # 23.b — zero / negative amounts cannot be reliably-measured revenue
    bad_amt = [r["id"] for r in sales
               if (r["nd"].get("sales_amount", r["amount"]) or 0) <= 0]
    if bad_amt:
        out.append(_f(
            "REV_NON_POSITIVE", "Sales with zero or negative amount",
            "Section 23 Revenue", "revenue", "fail", "critical",
            f"{len(bad_amt)} sales record(s) have a zero or negative amount — "
            f"revenue cannot be measured reliably.",
            "Investigate these rows; reclassify refunds/returns as contra-revenue.",
            affected=["SalesTxn"], evidence={"record_ids": bad_amt[:25], "count": len(bad_amt)},
        ))

    # 23.c — every recognised sale should generate a journal entry
    sale_ids = {r["id"] for r in sales}
    journaled = {j["source_record_id"] for j in ctx["journals"] if j["source_record_id"]}
    unposted = sorted(sale_ids - journaled)
    if unposted:
        out.append(_f(
            "REV_UNPOSTED", "Recognised sales not posted to the ledger",
            "Section 23 Revenue", "completeness", "fail", "critical",
            f"{len(unposted)} sales record(s) were extracted but no journal "
            f"entry was created — revenue is understated.",
            "Re-run the mapping stage; confirm the accounting mapper handles "
            "every sales record type.",
            affected=["SalesTxn", "Journal"],
            evidence={"record_ids": unposted[:25], "count": len(unposted)},
        ))
    else:
        out.append(_f(
            "REV_POSTED_OK", "All recognised sales are posted",
            "Section 23 Revenue", "completeness", "pass", "info",
            f"All {len(sales)} sales records have a corresponding journal entry.",
            conf=0.99,
        ))
    return out


def _check_inventory_valuation(ctx) -> List[Dict]:
    """TFRS for SMEs Section 13 — Inventories.  Measured at the lower of cost
    and estimated selling price less costs to complete and sell (NRV)."""
    out = []
    inv = [r for r in ctx["records"] if r["record_type"] == "InventoryMovement"]
    sales = [r for r in ctx["records"] if r["record_type"] == "SalesTransaction"]

    # 13.a — lower of cost and NRV: flag SKUs whose unit cost exceeds the
    # observed unit selling price
    sell_price: Dict[str, float] = {}
    for s in sales:
        nd = s["nd"]
        sku = nd.get("sku_id")
        qty = nd.get("quantity_sold") or 0
        amt = nd.get("sales_amount") or 0
        if sku and qty:
            sell_price.setdefault(sku, amt / qty)
    cost_gt_nrv = []
    for r in inv:
        nd = r["nd"]
        sku = nd.get("sku_id")
        ucost = nd.get("unit_cost") or 0
        if sku and ucost and sku in sell_price and ucost > sell_price[sku] > 0:
            cost_gt_nrv.append({"sku": sku, "unit_cost": ucost,
                                "sell_price": round(sell_price[sku], 2)})
    if cost_gt_nrv:
        out.append(_f(
            "INV_NRV", "Inventory carried above net realisable value",
            "Section 13 Inventories", "inventory", "warning", "warning",
            f"{len(cost_gt_nrv)} SKU(s) have a unit cost higher than their "
            f"observed selling price — TFRS for SMEs requires a write-down to NRV.",
            "Record an inventory write-down for these SKUs so they are carried "
            "at the lower of cost and NRV.",
            affected=["SKU", "Inventory"],
            evidence={"items": cost_gt_nrv[:20], "count": len(cost_gt_nrv)},
        ))

    # 13.b — costing consistency: same SKU should not show wildly varying cost
    cost_by_sku: Dict[str, list] = defaultdict(list)
    for r in inv:
        nd = r["nd"]
        sku, uc = nd.get("sku_id"), nd.get("unit_cost")
        if sku and uc:
            cost_by_sku[sku].append(uc)
    inconsistent = []
    for sku, costs in cost_by_sku.items():
        if len(costs) >= 2:
            lo, hi = min(costs), max(costs)
            if lo > 0 and hi / lo > 1.5:
                inconsistent.append({"sku": sku, "min_cost": lo, "max_cost": hi})
    if inconsistent:
        out.append(_f(
            "INV_COST_CONSISTENCY", "Inconsistent unit costs for the same SKU",
            "Section 13 Inventories", "inventory", "warning", "warning",
            f"{len(inconsistent)} SKU(s) show unit costs varying by more than "
            f"50% within the period — the cost formula (FIFO / weighted average) "
            f"may be applied inconsistently.",
            "Pick one cost formula (TFRS for SMEs allows FIFO or weighted "
            "average) and apply it consistently to all items of similar nature.",
            affected=["SKU", "Inventory"],
            evidence={"items": inconsistent[:20], "count": len(inconsistent)},
        ))

    # 13.c — negative ending stock is impossible
    neg = []
    for r in inv:
        end = r["nd"].get("ending_stock")
        if end is not None and end < 0:
            neg.append({"sku": r["nd"].get("sku_id"), "ending_stock": end})
    if neg:
        out.append(_f(
            "INV_NEGATIVE", "Negative ending inventory",
            "Section 13 Inventories", "inventory", "fail", "critical",
            f"{len(neg)} inventory line(s) report negative ending stock — "
            f"physically impossible and corrupts COGS.",
            "Reconcile opening stock, receipts, issues and waste for these SKUs.",
            affected=["SKU", "Inventory"],
            evidence={"items": neg[:20], "count": len(neg)},
        ))
    if inv and not (cost_gt_nrv or inconsistent or neg):
        out.append(_f(
            "INV_OK", "Inventory valuation checks passed",
            "Section 13 Inventories", "inventory", "pass", "info",
            f"All {len(inv)} inventory movements pass the lower-of-cost-and-NRV, "
            f"costing-consistency and non-negativity checks.",
            conf=0.97,
        ))
    return out


def _check_cutoff(ctx, period) -> List[Dict]:
    """Period cut-off — transactions must be recorded in the period in which
    they occur (TFRS for SMEs Section 2 accrual basis)."""
    out = []
    start, end = period.start_date, period.end_date
    if not start or not end:
        return out
    outside = []
    future = []
    for r in ctx["records"]:
        d = (r.get("date") or "")[:10]
        if not d:
            continue
        if d < start or d > end:
            outside.append({"id": r["id"], "type": r["record_type"], "date": d})
        if d > end:
            future.append(r["id"])
    if future:
        out.append(_f(
            "CUTOFF_FUTURE", "Transactions dated after the period end",
            "Section 2 Accrual basis", "cutoff", "fail", "critical",
            f"{len(future)} transaction(s) are dated after the period end "
            f"({end}) yet were included — this overstates the current period.",
            "Move post-period transactions to the next period; only events "
            "occurring within {0}–{1} belong here.".format(start, end),
            affected=["SalesTxn", "Purchase", "Inventory"],
            evidence={"record_ids": future[:25], "count": len(future),
                      "period_end": end},
        ))
    elif outside:
        out.append(_f(
            "CUTOFF_OUTSIDE", "Transactions dated outside the period window",
            "Section 2 Accrual basis", "cutoff", "warning", "warning",
            f"{len(outside)} transaction(s) fall outside the detected period "
            f"window {start}–{end}. Confirm the period boundaries are correct.",
            "Verify the reporting period; re-date or re-assign stray rows.",
            affected=["SalesTxn", "Purchase", "Inventory"],
            evidence={"samples": outside[:20], "count": len(outside),
                      "period": f"{start} - {end}"},
        ))
    else:
        out.append(_f(
            "CUTOFF_OK", "Period cut-off is clean",
            "Section 2 Accrual basis", "cutoff", "pass", "info",
            f"Every transaction falls within the reporting window {start}–{end}.",
            conf=0.98,
        ))
    return out


def _check_completeness(ctx) -> List[Dict]:
    """Double-entry completeness — every journal entry must balance and the
    trial balance as a whole must balance (TFRS for SMEs Section 2)."""
    out = []
    journals = ctx["journals"]
    if not journals:
        out.append(_f(
            "COMPLETE_NO_JOURNALS", "No journal entries for the period",
            "Section 2 Accrual basis", "completeness", "fail", "critical",
            "The period has data but no journal entries were posted — no "
            "financial statements can be produced.",
            "Run the full pipeline; check the accounting mapper.",
            affected=["Journal"],
        ))
        return out

    unbalanced = []
    total_debit = total_credit = 0.0
    for j in journals:
        d = sum(l["debit"] for l in j["lines"])
        c = sum(l["credit"] for l in j["lines"])
        total_debit += d
        total_credit += c
        if abs(d - c) > 0.01:
            unbalanced.append({"entry_id": j["id"], "debit": round(d, 2),
                               "credit": round(c, 2)})
    if unbalanced:
        out.append(_f(
            "COMPLETE_UNBALANCED_ENTRY", "Unbalanced journal entries",
            "Section 2 Accrual basis", "completeness", "fail", "critical",
            f"{len(unbalanced)} journal entry(ies) do not balance (debit != "
            f"credit) — the books cannot be relied upon.",
            "Fix the accounting mapping for the affected source records.",
            affected=["Journal", "Account"],
            evidence={"entries": unbalanced[:20], "count": len(unbalanced)},
        ))
    if abs(total_debit - total_credit) > 0.01:
        out.append(_f(
            "COMPLETE_TB_IMBALANCE", "Trial balance does not balance",
            "Section 2 Accrual basis", "completeness", "fail", "critical",
            f"Total debits ({total_debit:,.2f}) do not equal total credits "
            f"({total_credit:,.2f}); difference {total_debit - total_credit:,.2f}.",
            "Resolve the unbalanced entries above; the trial balance must net "
            "to zero before statements are issued.",
            affected=["Account", "Journal"],
            evidence={"total_debit": round(total_debit, 2),
                      "total_credit": round(total_credit, 2),
                      "difference": round(total_debit - total_credit, 2)},
        ))
    else:
        out.append(_f(
            "COMPLETE_TB_OK", "Trial balance balances",
            "Section 2 Accrual basis", "completeness", "pass", "info",
            f"Total debits equal total credits ({total_debit:,.2f}); "
            f"double-entry integrity holds across {len(journals)} entries.",
            conf=0.99,
        ))
    return out


def _check_classification(ctx) -> List[Dict]:
    """Statement classification — every posted account must land on a
    statement (TFRS for SMEs Section 3-8 presentation)."""
    out = []
    posted_codes = set()
    for j in ctx["journals"]:
        for l in j["lines"]:
            if l["account_code"]:
                posted_codes.add(l["account_code"])
    classified = {sl["account_code"] for sl in ctx["statement_lines"] if sl["account_code"]}
    unclassified = sorted(c for c in posted_codes if c and c not in classified)
    # Only meaningful once statements exist
    if ctx["statement_lines"] and unclassified:
        out.append(_f(
            "CLASS_UNMAPPED", "Posted accounts missing from the statements",
            "Section 3 Financial statement presentation", "classification",
            "warning", "warning",
            f"{len(unclassified)} account code(s) appear in journal lines but "
            f"on no financial statement line — they are silently dropped.",
            "Map every GL account to a statement category (asset / liability / "
            "equity / income / expense).",
            affected=["Account"],
            evidence={"account_codes": unclassified[:30], "count": len(unclassified)},
        ))
    elif ctx["statement_lines"]:
        out.append(_f(
            "CLASS_OK", "All posted accounts are classified",
            "Section 3 Financial statement presentation", "classification",
            "pass", "info",
            "Every account code used in the ledger appears on a financial "
            "statement line.",
            conf=0.96,
        ))
    return out


# ── Layer 2: native LLM agent reasoning over the SQ2 graph ──────────────────
_AGENT_PROMPT = """You are a Thai SME accounting reviewer. You are given the
ENTITY GRAPH a previous step designed for one accounting period, plus a digest
of deterministic checks already run. Reason ACROSS the graph structure and
flag compliance issues with TFRS for SMEs (Thai Financial Reporting Standards
for Small and Medium Entities) that a flat per-row rule check would miss —
e.g. missing entity types the business clearly needs, relationships that imply
un-recorded transactions, revenue/expense matching problems, or presentation
gaps.

ENTITY GRAPH (entities with their objective + department + key attributes):
{entities}

RELATIONSHIPS:
{relations}

PERIOD DATA DIGEST:
{digest}

DETERMINISTIC FINDINGS ALREADY RAISED (do not repeat these):
{rule_digest}

Return STRICT JSON (no prose, no fences):
{{
  "findings": [
    {{
      "rule_code": "SHORT_UPPER_SNAKE",
      "rule_name": "short human label",
      "section_ref": "Section NN <topic>",
      "category": "revenue | inventory | cutoff | completeness | classification | structure",
      "status": "pass | warning | fail",
      "severity": "info | warning | critical",
      "finding": "1-3 sentences: what is wrong or notable, grounded in the graph/digest",
      "recommendation": "1-2 sentences: the concrete fix",
      "affected_entities": ["EntityKey", ...],
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Max 6 findings. Only include things that genuinely matter.
- Ground every finding in the supplied graph or digest — no speculation.
- confidence reflects how sure you are given only this structured view.
"""


def _llm_agent_pass(ctx, rule_findings: List[Dict]) -> List[Dict]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    entities = [{
        "entity_key": d.entity_key, "label": d.label, "category": d.category,
        "objective": d.objective, "department": d.department,
        "attributes": [a.get("k") for a in (d.attributes or [])][:8],
    } for d in ctx["designs"]]
    relations = [{
        "from": r.from_key, "to": r.to_key, "label": r.label,
        "cardinality": r.cardinality,
    } for r in ctx["relations"]]

    rec_types = defaultdict(int)
    for r in ctx["records"]:
        rec_types[r["record_type"]] += 1
    digest = {
        "record_counts": dict(rec_types),
        "journal_entries": len(ctx["journals"]),
        "statement_lines": len(ctx["statement_lines"]),
        "file_types": sorted(ctx["file_types"]),
    }
    rule_digest = [
        {"rule_code": f["rule_code"], "status": f["status"],
         "finding": f["finding"][:160]}
        for f in rule_findings
    ]

    prompt = _AGENT_PROMPT.format(
        entities=json.dumps(entities, ensure_ascii=False, indent=1),
        relations=json.dumps(relations, ensure_ascii=False, indent=1),
        digest=json.dumps(digest, ensure_ascii=False, indent=1),
        rule_digest=json.dumps(rule_digest, ensure_ascii=False, indent=1),
    )
    msg = client.messages.create(
        model=LLM_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    parsed = json.loads(text[start:end + 1])
    out = []
    for f in parsed.get("findings", [])[:6]:
        out.append({
            "standard": STANDARD,
            "section_ref": f.get("section_ref", ""),
            "rule_code": f.get("rule_code", "AGENT_FINDING"),
            "rule_name": f.get("rule_name", "Agent finding"),
            "category": f.get("category", "structure"),
            "status": f.get("status", "warning"),
            "severity": f.get("severity", "warning"),
            "finding": (f.get("finding") or "").strip(),
            "recommendation": (f.get("recommendation") or "").strip(),
            "affected_entities": f.get("affected_entities", []),
            "evidence": {},
            "confidence": float(f.get("confidence", 0.6)),
            "source": "agent",
        })
    return out


# ── Summary helper ──────────────────────────────────────────────────────────
def _summarize(findings: List[Dict]) -> Dict[str, Any]:
    by_status = defaultdict(int)
    by_severity = defaultdict(int)
    by_category = defaultdict(int)
    for f in findings:
        by_status[f.get("status", "warning")] += 1
        by_severity[f.get("severity", "warning")] += 1
        by_category[f.get("category", "general")] += 1
    fails = by_status.get("fail", 0)
    warns = by_status.get("warning", 0)
    passes = by_status.get("pass", 0)
    total_checks = max(1, fails + warns + passes)
    # Compliance score: passes count full, warnings half, fails zero
    score = round((passes + 0.5 * warns) / total_checks * 100, 1)
    return {
        "by_status": dict(by_status),
        "by_severity": dict(by_severity),
        "by_category": dict(by_category),
        "compliance_score": score,
        "verdict": (
            "blocked" if fails else
            "review" if warns else
            "clean"
        ),
    }
