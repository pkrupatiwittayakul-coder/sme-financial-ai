# SME Financial Intelligence System

> Convert messy SME records (sales, purchases, inventory, bank) into
> validated, insight-rich financial statements through a **five-sequence AI pipeline**.

Live: <https://sme-financial-ai.onrender.com>
Repo: <https://github.com/pkrupatiwittayakul-coder/sme-financial-ai>

---

## The five-sequence pipeline

| # | Sequence | Status | Owner | What happens |
|---|---|---|---|---|
| 1 | **LLM Entity Designer** | ✅ Live | Claude API | Receives raw column headers + sample rows for each uploaded file and designs the entities. Every entity carries an **objective** (why the data exists), a **department owner**, **data constraints**, and proposed **relationships** to other entities. |
| 2 | **Graph Assembly + Memory** | ✅ Live | Backend | Persists LLM blueprints as `EntityDesign` + `EntityRelationDesign` rows, renders an interactive ontology graph the user can edit, and caches approved designs by `sha1(file_type + sorted_columns)` so repeat uploads are instant and stable. |
| 3 | **Native Validation Agent** | ✅ Live | Claude API + Rules | Uses the **SQ2 ontology** (entity objectives, department owners, constraints, and relationships) as its domain model, then validates the period's actual data against **TFRS / IFRS for SMEs** (Thai Financial Reporting Standards for SMEs). Runs two layers: (1) deterministic rule checks anchored to TFRS sections (revenue recognition §23, inventory valuation §13, cut-off, completeness, classification) using the ontology's entity metadata as assumptions about what each data entity *means*; (2) an LLM reasoning layer that feeds the full ontology graph + deterministic findings to Claude, which reasons about structural and standard-level compliance issues the rule layer cannot catch. Each finding carries a severity, TFRS section reference, affected entity keys from the ontology, evidence rows, confidence score, and a recommended fix. Findings persist in `agent_validations` and can be acknowledged, dismissed, or marked fixed. |
| 4 | **Predictive Report Generation** | 🔜 Planned | Claude API | Condenses inventory flow and capital trajectory into a readable, forward-looking report with turning points, risk flags, and confidence signals. Output will appear as an **in-app report tab only** (no file export). |
| 5 | **Deep LLM Interaction** | 🔶 Foundation built | Claude API | Evidence-backed Q&A chat over the company's own books. The agent loads the income statement, trial balance, SQ3 validation findings, and importance-scored records as grounded context before every query — so answers are anchored to real numbers, not hallucinated. Persists `ChatSession` + `ChatMessage` history per period. Full deep-agent capabilities (multi-turn reasoning, cross-period comparison, drill-down) are planned for the next build cycle. |

After SQ1 + SQ2 approval, the standard pipeline runs: extract → validate → score → post journals → generate statements.

---

## Architecture overview

```
Upload (Excel/CSV)
       │
       ▼
 ┌─────────────┐
 │  SQ1: LLM   │  entity_designer.py
 │  Entity     │  → designs entities (objective, dept, constraints,
 │  Designer   │    relationships) using Claude
 └──────┬──────┘
        │ blueprints
        ▼
 ┌─────────────┐
 │  SQ2: Graph │  graph_assembler.py + design_memory.py
 │  Assembly + │  → EntityDesign + EntityRelationDesign rows
 │  Memory     │  → interactive ontology graph (user-editable)
 └──────┬──────┘  → sha1 memory cache (approved designs re-used instantly)
        │ approved graph
        ▼
 ┌─────────────┐
 │  SQ3: TFRS  │  validation_agent.py
 │  Validation │  → uses SQ2 ontology as domain assumptions
 │  Agent      │  → deterministic TFRS rule checks (5 categories)
 └──────┬──────┘  → LLM reasoning over ontology + rules
        │         → AgentValidation rows (severity, section ref, evidence)
        │
        ▼
 ┌────────────────────────────────────────────────┐
 │  Standard pipeline                             │
 │  extract → validate → score → journals →       │
 │  statements (P&L, Balance Sheet, Trial Bal.)   │
 └──────┬─────────────────────────────────────────┘
        │
        ├──▶  SQ4: Predictive Report  (planned)
        │
        └──▶  SQ5: Deep Chat          chat_agent.py
                  → grounded Q&A over financials + SQ3 findings
```

---

## Repository layout

```
.
├── backend/                          # FastAPI app (the deployed service)
│   ├── api/
│   │   ├── auth.py                   # JWT login / register
│   │   ├── chat.py                   # SQ5 — chat endpoint
│   │   ├── classify.py               # File type classifier
│   │   ├── companies.py              # Company + period CRUD
│   │   ├── entity_design.py          # SQ1 + SQ2 — design + graph API
│   │   ├── ontology.py               # Ontology graph read + confirm
│   │   ├── pipeline.py               # Full pipeline trigger
│   │   ├── records.py                # Business record reads
│   │   ├── schema.py                 # Schema mapping
│   │   ├── statements.py             # Generated financial statements
│   │   ├── upload.py                 # File upload handler
│   │   └── validation_agent.py       # SQ3 — TFRS validation API
│   ├── services/
│   │   ├── accounting_mapper.py      # Account code → chart of accounts
│   │   ├── auth_service.py           # Password hashing + JWT
│   │   ├── chat_agent.py             # SQ5 — evidence-backed chat agent
│   │   ├── design_memory.py          # SQ2 — sha1 memory cache
│   │   ├── entity_designer.py        # SQ1 — LLM entity design
│   │   ├── entity_resolver.py        # Legacy resolver (fallback)
│   │   ├── file_classifier.py        # Detect file type from headers
│   │   ├── file_parser.py            # Excel/CSV → DataFrame
│   │   ├── graph_assembler.py        # SQ2 — graph assembly
│   │   ├── importance_scorer.py      # Risk-score records
│   │   ├── pipeline_progress.py      # SSE progress stream
│   │   ├── record_extractor.py       # Extract structured records
│   │   ├── schema_mapper.py          # Map raw columns to schema
│   │   ├── statement_generator.py    # P&L / balance sheet / trial balance
│   │   ├── validation_agent.py       # SQ3 — TFRS rules + LLM validation
│   │   └── validation_engine.py      # Deterministic record validation
│   ├── database.py                   # SQLAlchemy models (all sequences)
│   ├── config.py                     # Settings + env vars
│   ├── dashboard.html                # Single-page UI (Ledger Spark design)
│   └── main.py                       # FastAPI entry point + router wiring
├── sample_data/                      # Excel files to try the dashboard with
├── docs/
│   ├── ADR-001-architecture-hardening.md
│   └── design_prototype.html         # "Ledger Spark" visual reference
├── scripts/
│   └── push_to_github.ps1            # One-click commit + push (Windows)
├── .env.example
├── .gitignore
├── Procfile
├── render.yaml
├── requirements.txt
├── runtime.txt
└── start.sh
```

---

## Database models (key tables)

| Table | Sequence | Purpose |
|---|---|---|
| `companies` / `periods` | — | Multi-tenant company + period scoping |
| `files` | — | Uploaded file metadata |
| `business_records` | — | Extracted, structured records |
| `journal_entries` / `journal_lines` | — | Double-entry journal |
| `financial_statements` / `statement_lines` | — | P&L, balance sheet |
| `entity_designs` | SQ1 | LLM-designed entity definitions |
| `entity_relation_designs` | SQ2 | Relationships between entities |
| `design_memory` | SQ2 | sha1-keyed approved-design cache |
| `agent_validations` | SQ3 | TFRS findings (rule + LLM layer, with severity, section ref, evidence, confidence) |
| `chat_sessions` / `chat_messages` | SQ5 | Persistent Q&A history per period |

---

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # SQ1, SQ3, SQ5 use Claude API
export DATABASE_URL=sqlite:////tmp/sme.db
uvicorn backend.main:app --reload
# Open http://localhost:8000
```

`.env.example` has all supported variables. The app runs without an API key — SQ1/SQ3/SQ5 degrade gracefully (SQ3 still returns full deterministic rule results).

---

## Try the flow

1. Sign in and create a company + period.
2. Drop the Excel files from `sample_data/` onto the dashboard.
3. Watch **Sequence 1** in the progress panel: Claude designs entities with objectives, department owners, and constraints.
4. Open **Review ontology graph** — nodes show department badges, objective text, and constraints JSON. Click **Link to…** to draw new relationships manually.
5. Press **⟳ Re-design** to re-run Claude; **Confirm & post journals** to approve and write to the memory cache.
6. Open the **Validation** tab and trigger **Sequence 3** — the TFRS agent runs deterministic checks + LLM reasoning and surfaces findings grouped by severity (critical / warning / info). Acknowledge, dismiss, or mark each finding as fixed.
7. Open the **Chat** tab to ask the AI questions about your books — every answer is grounded in your actual P&L, trial balance, and SQ3 findings.

---

## Key API endpoints

### SQ1 + SQ2 — Entity Design & Graph

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/design/{period_id}/run` | Run the LLM entity designer (SQ1) |
| `GET` | `/api/design/{period_id}` | Get the assembled graph + memory stats |
| `PATCH` | `/api/design/entity/{design_id}` | Edit any field on an entity |
| `POST` | `/api/design/{period_id}/relation` | Add a user-drawn relationship (SQ2) |
| `POST` | `/api/design/{period_id}/approve` | Approve + write to memory cache |
| `GET` | `/api/companies/{id}/ontology` | Read the ontology graph for a company |

### SQ3 — TFRS / IFRS for SMEs Validation Agent

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/validate/{period_id}/run` | Run the SQ3 validation agent (rules + LLM) |
| `GET` | `/api/validate/{period_id}` | List all findings + summary for a period |
| `PATCH` | `/api/validate/finding/{finding_id}` | Acknowledge / dismiss / mark fixed |

### SQ5 — Chat

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chat/` | Send a message; returns a grounded AI answer + session ID |

### Pipeline & Statements

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/pipeline/{period_id}` | Run the full extract → journal → statements pipeline |
| `GET` | `/api/statements/{period_id}` | Retrieve generated financial statements |

---

## Roadmap

- **SQ4 — Predictive Report**: inventory flow + capital trajectory with turning points, risk flags, and confidence signals (in-app tab, no export).
- **SQ5 deep mode**: multi-turn agent reasoning, cross-period comparison, and drill-down into individual journal entries and SQ3 findings.

Full implementation report: [SME_Financial_AI_MVP_v2_Report.pdf](SME_Financial_AI_MVP_v2_Report.pdf)
Architecture decision record: [ADR-001-architecture-hardening.md](ADR-001-architecture-hardening.md)
