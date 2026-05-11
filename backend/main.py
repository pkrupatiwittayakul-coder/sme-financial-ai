"""FastAPI main app — SME Financial Intelligence System."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.database import init_db
from backend.api import companies, upload, classify, schema, records, statements, chat

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
app.include_router(companies.router, prefix="/api/companies", tags=["Companies"])
app.include_router(upload.router,    prefix="/api/upload",    tags=["Upload"])
app.include_router(classify.router,  prefix="/api/classify",  tags=["Classify"])
app.include_router(schema.router,    prefix="/api/schema",    tags=["Schema"])
app.include_router(records.router,   prefix="/api/records",   tags=["Records"])
app.include_router(statements.router,prefix="/api/statements",tags=["Statements"])
app.include_router(chat.router,      prefix="/api/chat",      tags=["Chat"])


@app.on_event("startup")
def startup_event():
    init_db()
    print("✅ Database initialised")


@app.get("/")
def root():
    return {"status": "running", "app": "SME Financial Intelligence System"}


@app.get("/health")
def health():
    return {"status": "ok"}
