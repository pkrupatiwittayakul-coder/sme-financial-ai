# SME Financial AI — Project Handoff

> Last updated: 2026-05-13
> Repo: https://github.com/pkrupatiwittayakul-coder/sme-financial-ai
> Live URL: https://sme-financial-ai.onrender.com
> Design reference: `design_prototype.html` (Ledger Spark)
> Latest deliverable: `SME_Financial_AI_MVP_Report.pdf`

---

## Goal

Fully automatic SME financial intelligence. The user only does two things:
1. Register / log in.
2. Fill in business name + industry.

Upload → classify → schema map → extract → validate → journal → statements +
ontology all happen automatically. UI follows the Ledger Spark design system
(purple `#5B4BFB`, orange `#FF7A59`, Plus Jakarta Sans + JetBrains Mono).

---

## Current State (updated: 2026-05-13 — session 2)

### What works end-to-end (verified locally)
- Register / login / Google OAuth ✓
- Company + period auto-bootstrap ✓
- File upload (sales / purchases / inventory) → full 6-agent pipeline ✓
- Income statement, trial balance, exception report ✓
- AI chat analyst (Anthropic Claude) ✓
- 401 auto-logout ✓
- Ontology graph fed by real data — `GET /api/companies/{id}/ontology` ✓
- Confirm & post journals — `POST /api/pipeline/{period_id}/confirm` ✓
- Real-time pipeline progress (SSE) — `GET /api/pipeline/{period_id}/progress` ✓
- Dialect-aware DB engine (SQLite / Postgres) ✓
- **NEW · Balance Sheet** — `GET /api/statements/balance-sheet/{period_id}` derives Assets / Liabilities / Equity from journal entries + net profit. Rendered in new **Balance Sheet** tab in the dashboard.
- **NEW · Trial Balance tab** — previously the `tabTb` div existed but was never populated. Now fetches real data and renders a full account table with debit/credit/net columns and totals row.
- **NEW · PDF export** — `GET /api/statements/export-pdf/{period_id}?type=income_statement|balance_sheet|trial_balance` streams a reportlab-generated PDF. Download buttons appear on each statement tab.
- **NEW · Real exceptions panel** — `tabExceptions` now fetches `/api/statements/exceptions/{period_id}` and renders actual severity badges, messages, and record links instead of the hardcoded "No exceptions" placeholder.
- **NEW · Streamlit removed** — `frontend/app.py` excluded from git tracking via `.gitignore` (file still on disk but not deployed).

### Verification numbers (local SQLite, Thai sample data)
- 3 files (sales 400 rows, purchases 81 rows, inventory 32 rows) → 512 BusinessRecords → 509 JournalEntries
- Period auto-detected as `Jan 2026` (`2026-01-01` → `2026-01-31`)
- Income statement: Revenue ฿2,259,534 · COGS ฿1,541,400 · Gross Profit ฿718,134 · Net Profit ฿706,038
- Ontology: 9 nodes · 10 edges · 18 entities · avg classification confidence 0.96
- SSE: terminal `completed` event received over the stream during a concurrent pipeline re-run

---

## Files in flight (session 2 — 2026-05-13)

| File | Change |
|---|---|
| `backend/services/statement_generator.py` | +`generate_balance_sheet()`, +`generate_pdf_report()` (reportlab) |
| `backend/api/statements.py` | +`GET /balance-sheet/{id}`, +`GET /export-pdf/{id}?type=…` |
| `backend/dashboard.html` | Balance Sheet tab, Trial Balance table, PDF buttons, real exceptions |
| `.gitignore` | **NEW** — excludes `*.db`, `frontend/app.py`, generated PDFs |
| `push_to_github.ps1` | **NEW** — one-click push script for Windows (excluded from git) |
| `HANDOFF.md` | Updated |

---

## Environment Variables (Render Dashboard)

| Key | Source | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Manual | Yes |
| `DATABASE_URL` | `render.yaml` default = SQLite (ephemeral). Set to Postgres for prod | Yes |
| `UPLOAD_DIR` | `render.yaml` = `/tmp/sme_uploads` | Yes |
| `REPORT_DIR` | `render.yaml` = `/tmp/sme_reports` | Yes |
| `LLM_MODEL` | `render.yaml` = `claude-haiku-4-5-20251001` | Yes |
| `SECRET_KEY` | `render.yaml` `generateValue: true` (auto-generated on first deploy) | Yes (auto) |
| `GOOGLE_CLIENT_ID` | Manual, optional | Only for Google login |

> ⚠️ SQLite on Render free tier is **ephemeral** — every redeploy wipes the DB. Switch `DATABASE_URL` to Postgres for any real data.

---

## Failed attempts / gotchas

### Workspace file-mount cache
Windows-mounted file edits via the Edit tool do not always propagate to the bash sandbox's view immediately. Workaround during this session was to rewrite critical files via `cat <<EOF` heredocs inside bash so both views agree. Functionally everything is in sync now.

### Git lock files
`.git/config.lock` / `.git/index.lock` in the workspace can't be deleted on the Windows filesystem. Clone fresh to `/tmp` and push from there.

### Render network from sandbox
The sandbox proxy blocks outbound traffic to Render. To verify deployment after pushing, hard-refresh the live site (`Ctrl+Shift+R`) from your own browser.

---

## Next steps (priority order)

1. **Move to Postgres on Render** — DB code already supports it, just switch the env var. Solves the ephemeral-DB problem.
2. **Format the Balance Sheet** — Income Statement renders nicely; BS needs a proper layout + PDF export button (reportlab is now installed).
3. **Persist SSE events** — current broker is in-process; swap to Redis pub/sub for multi-worker production.
4. **Auth the SSE endpoint** — accept JWT via query param or use short-lived signed URLs.
5. **Add pytest coverage** for `run_pipeline_internal` against `sample_data/`.
6. **Delete `frontend/app.py`** — legacy Streamlit, no longer referenced in `render.yaml`.
7. **Google OAuth production** — set `GOOGLE_CLIENT_ID` in Render and register the Render domain in GCP.
