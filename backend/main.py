"""FastAPI main app — SME Financial Intelligence System."""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from backend.database import init_db
from backend.api import companies, upload, classify, schema, records, statements, chat, auth, pipeline, ontology, entity_design

app = FastAPI(
    title="SME Financial Intelligence System",
    description="Convert messy SME records into validated financial statements",
    version="1.0.0-MVP",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router,      prefix="/api/auth",      tags=["Auth"])
app.include_router(companies.router, prefix="/api/companies", tags=["Companies"])
app.include_router(upload.router,    prefix="/api/upload",    tags=["Upload"])
app.include_router(classify.router,  prefix="/api/classify",  tags=["Classify"])
app.include_router(schema.router,    prefix="/api/schema",    tags=["Schema"])
app.include_router(records.router,   prefix="/api/records",   tags=["Records"])
app.include_router(statements.router,prefix="/api/statements",tags=["Statements"])
app.include_router(chat.router,      prefix="/api/chat",      tags=["Chat"])
app.include_router(pipeline.router,  prefix="/api/pipeline",  tags=["Pipeline"])
# Ontology router exposes /api/companies/{id}/ontology and /api/pipeline/{id}/confirm
app.include_router(ontology.router,  prefix="/api",           tags=["Ontology"])
# Entity-Design router — Sequence 1 (LLM design) + Sequence 2 (graph) + user edits
app.include_router(entity_design.router, prefix="/api/design", tags=["Entity Design"])

# Load dashboard HTML once at startup
_DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


@app.on_event("startup")
def startup_event():
    init_db()
    print("Database initialised")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    return HTMLResponse(content=_DASHBOARD_HTML)


@app.get("/health")
def health():
    return {"status": "ok"}
