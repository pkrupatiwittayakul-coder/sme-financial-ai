# SME Financial Intelligence System

> Convert messy SME records (sales, purchases, inventory, bank) into
> validated financial statements through a two-sequence AI workflow.

Live: <https://sme-financial-ai.onrender.com>
Repo: <https://github.com/pkrupatiwittayakul-coder/sme-financial-ai>

---

## The two-sequence workflow

| # | Sequence | Owner | What happens |
|---|---|---|---|
| 1 | **LLM Entity Designer** | Claude API | Receives the raw column headers + sample rows for each upload and designs the entities. Every entity carries an **objective** (why the data exists), a **department owner**, **data constraints**, and proposed **relationships** to other entities. |
| 2 | **Graph Assembly + Memory** | Backend | Persists the LLM designs as `EntityDesign` + `EntityRelationDesign` rows, renders an interactive ontology graph, and caches approved designs by `sha1(file_type + sorted_columns)` so subsequent uploads are instant and stable. The user can edit any field or draw new relationships before approving. |

After approval the standard pipeline runs: extract → validate → score → post journals → generate statements.

---

## Repository layout

```
.
├── backend/                # FastAPI app (the deployed service)
│   ├── api/                # Route handlers (auth, upload, design, ontology, ...)
│   ├── services/           # Business logic (entity_designer, graph_assembler, ...)
│   ├── storage/            # Upload + report dirs (runtime, gitignored)
│   ├── database.py         # SQLAlchemy models
│   ├── dashboard.html      # Single-page UI (Ledger Spark design)
│   └── main.py             # FastAPI entry point
├── sample_data/            # Excel files to try the dashboard with
├── docs/                   # Reports, architecture decisions, design prototype
│   ├── MVP_v2_Report.pdf
│   ├── ADR-001-architecture-hardening.md
│   └── design_prototype.html  # The "Ledger Spark" visual reference
├── scripts/
│   └── push_to_github.ps1  # One-click commit + push (Windows)
├── .env.example
├── .gitignore
├── Procfile
├── render.yaml
├── requirements.txt
├── runtime.txt
└── start.sh
```

---

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # optional — fallback works without
export DATABASE_URL=sqlite:////tmp/sme.db
uvicorn backend.main:app --reload
# Open http://localhost:8000
```

---

## Try the flow

1. Sign in, create a company.
2. Drop the Excel files from `sample_data/` onto the dashboard.
3. Watch the **Sequence 1 — designing entities with LLM** progress event.
4. Open **Review ontology graph** — every node shows its department badge,
   objective text, and constraints JSON; click **Link to…** to draw new
   relationships.
5. Press **⟳ Re-design** to re-run the LLM; **Confirm & post journals** to
   commit and write the design into the memory cache.

---

## Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/design/{period_id}/run` | Run the LLM entity designer for a period |
| `GET` | `/api/design/{period_id}` | Get the assembled graph + memory stats |
| `PATCH` | `/api/design/entity/{design_id}` | Edit any field on an entity |
| `POST` | `/api/design/{period_id}/relation` | Add a user-drawn relationship |
| `POST` | `/api/design/{period_id}/approve` | Approve & persist to memory cache |
| `POST` | `/api/pipeline/{period_id}` | Run the full pipeline |
| `GET` | `/api/companies/{id}/ontology` | Read the graph for a company |

Full report: [docs/MVP_v2_Report.pdf](docs/MVP_v2_Report.pdf)
