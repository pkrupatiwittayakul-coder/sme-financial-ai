"""FastAPI application entry point."""
import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.database import init_db
from backend.config import ANTHROPIC_API_KEY
from backend.api import auth, companies, upload, classify, schema, records, statements, chat, agents, pipeline

logger = logging.getLogger(__name__)

app = FastAPI(title="SME Financial AI", version="2.0.0")


@app.on_event("startup")
async def startup_event():
    """Initialise DB and validate critical config at startup."""
    init_db()
    # Validate API key — warn but don't crash (LLM features degrade gracefully)
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-api") is False:
        logger.warning(
            "ANTHROPIC_API_KEY not set or invalid. "
            "Schema mapping LLM assist and chat features will be disabled."
        )
    else:
        logger.info("Anthropic API key detected — LLM features enabled.")
    logger.info("SME Financial AI started. DB initialised.")


# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router,        prefix="/api/auth",       tags=["Auth"])
app.include_router(companies.router,   prefix="/api/companies",  tags=["Companies"])
app.include_router(upload.router,      prefix="/api/upload",     tags=["Upload"])
app.include_router(classify.router,    prefix="/api/classify",   tags=["Classify"])
app.include_router(schema.router,      prefix="/api/schema",     tags=["Schema"])
app.include_router(records.router,     prefix="/api/records",    tags=["Records"])
app.include_router(agents.router,      prefix="/api/agents",     tags=["Agents"])
app.include_router(statements.router,  prefix="/api/statements", tags=["Statements"])
app.include_router(chat.router,        prefix="/api/chat",       tags=["Chat"])
app.include_router(pipeline.router,    prefix="/api/pipeline",   tags=["Pipeline"])

# ── Static / SPA ─────────────────────────────────────────────────────────────
_DASHBOARD = os.path.join(os.path.dirname(__file__), "dashboard.html")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(_DASHBOARD)


@app.get("/health")
def health():
    llm_ok = bool(ANTHROPIC_API_KEY)
    return {"status": "ok", "llm_enabled": llm_ok, "version": "2.0.0"}
