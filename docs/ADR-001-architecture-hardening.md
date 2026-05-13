# ADR-001: Architecture Hardening — SME Financial AI

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** Tin K.

---

## Context

The Phase 2 MVP is deployed and the landing page is live. The codebase has the correct skeleton but contains **critical gaps** versus the PDF implementation spec that make the outputs unreliable, insecure, and incomplete. This ADR documents every gap found and the decisions made to close them.

---

## Gap Analysis (current code vs PDF spec)

### CRITICAL — Correctness

| # | Gap | Where | Risk |
|---|-----|--------|------|
| C1 | No auth guard on `upload`, `classify`, `records`, `schema`, `statements` endpoints | 5 API files | Any anonymous user can upload to any period and read any statement |
| C2 | Missing Tax/VAT accounts in `accounting_mapper.py` — no 2200 VAT Payable, 1400 VAT Input, 7100 WHT | accounting_mapper.py | Tax agent and Tax checks produce no journal entries |
| C3 | `validation_engine.py` has no Tax Agent checks (missing VAT, WHT amounts) | validation_engine.py | Tax exceptions never surfaced |
| C4 | No `StatementEvidence` table — `evidence_count` int is stored but no actual row-level links | database.py | "Every statement line should answer: where did this number come from?" (PDF p.12) — FAILS |
| C5 | No `graph_builder.py` — entities extracted but relationships never written to `relationships` table | services/ | Knowledge graph is empty; chat agent has no graph to traverse |
| C6 | Debit/credit balance never verified before statement generation | statement_generator.py | Unbalanced trial balance can silently become the income statement |

### IMPORTANT — Completeness

| # | Gap | Where |
|---|-----|--------|
| I1 | No `agents/` layer — 6 process agents prescribed by PDF exist nowhere | backend/ |
| I2 | `importance_scorer.py` only scores individual records — no aggregate rollup to branch/supplier/account/file | importance_scorer.py |
| I3 | `schema_mapper.py` always calls LLM even when rule-based match is 100% confident | schema_mapper.py |
| I4 | No startup check for `ANTHROPIC_API_KEY` — silently fails mid-request | config.py |
| I5 | `entity_resolver.py` does fuzzy matching but never persists to `entities` table via API | records.py |
| I6 | `file_sheets` table missing — multi-sheet Excel files not individually tracked | database.py |
| I7 | No `report_generator.py` for LLM-backed narrative management reports | services/ |

### MINOR — Polish

| # | Gap |
|---|-----|
| M1 | `classify.py` override has no ownership check |
| M2 | `accounting_mapper.py` DEFAULT_ACCOUNTS too thin (8 accounts; real SME needs 20+) |
| M3 | `statement_generator.py` has no balance sheet (PDF: include in Phase 3, acceptable) |

---

## Decisions

### D1 — Auth guard every endpoint (C1)
Add `current_user = Depends(get_current_user)` to all endpoints in upload, classify, records, schema, statements, chat. Add ownership verification: user must own the company that owns the period that owns the file.

### D2 — Add Tax/VAT accounts and journal mapping (C2, C3)
Extend `DEFAULT_ACCOUNTS` with: 1400 VAT Input, 2200 VAT Payable, 2300 WHT Payable, 7100 Interest Expense, 7200 Tax Expense.

### D3 — Add `StatementEvidence` table (C4)
New ORM model: `statement_line_id` → `business_record_id` → `raw_record_id` → `file_id`.

### D4 — Add `graph_builder.py` service (C5)
Deterministic rule-based edges from PDF spec (p.9).

### D5 — Add debit=credit balance check (C6)
In `statement_generator.py`, verify `sum(debit) == sum(credit)` across all journal lines before generating.

### D6 — Add agents layer (I1)
Create `backend/agents/` with one file per process agent.

### D7 — LLM skip for high-confidence rule matches (I3)
In `schema_mapper.py`: if rule-based confidence ≥ 0.90 for all columns, skip LLM call entirely.

### D8 — Startup validation (I4)
In `main.py` startup event: verify `ANTHROPIC_API_KEY` exists and is non-empty.

---

## Supersession — ADR-002 (informal)

The follow-up MVP v2 release (2026-05-13) replaced the rule-based entity resolver with an LLM-first two-sequence workflow. See **docs/MVP_v2_Report.pdf** for the full design. New components:

- `backend/services/entity_designer.py` (Sequence 1)
- `backend/services/graph_assembler.py` (Sequence 2)
- `backend/services/design_memory.py` (memory layer)
- `backend/api/entity_design.py` (user edits + relationship builder)

`graph_builder.py` is preserved as a legacy fallback; the LLM-designed `EntityRelationDesign` rows are now the canonical relationship source.
