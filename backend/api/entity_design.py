"""
Entity-Design API
==================
Endpoints that drive the new two-sequence workflow:

  Sequence 1 — POST /api/design/{period_id}/run
      For every file in the period, send columns+sample to the LLM and
      persist proposed EntityDesigns + EntityRelationDesigns.

  Sequence 2 — GET  /api/design/{period_id}
      Returns the assembled graph (nodes + edges + counts + memory hit
      info) for the dashboard to render and let the user interact with.

  User edits:
    PATCH  /api/design/entity/{design_id}     update objective/constraints/position
    POST   /api/design/{period_id}/relation   add a user-defined edge
    DELETE /api/design/relation/{rel_id}      drop an edge
    POST   /api/design/{period_id}/approve    mark the design approved + remember
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import (
    get_db, Period, Company, File as FileModel,
    RawRecord, EntityDesign, EntityRelationDesign,
)
from backend.services import design_memory
from backend.services.entity_designer import design_from_file, merge_designs
from backend.services.graph_assembler import persist_design, assemble_graph


router = APIRouter()


# ─── helpers ────────────────────────────────────────────────────────────────
def _resolve_user_id(db: Session, period_id: int) -> Optional[int]:
    """Best-effort owner lookup so memory is scoped per user."""
    period = db.query(Period).get(period_id)
    if not period:
        return None
    company = db.query(Company).get(period.company_id) if period.company_id else None
    return company.user_id if company and company.user_id else None


def _check_period(db: Session, period_id: int) -> Period:
    period = db.query(Period).get(period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    return period


# ─── Sequence 1: run the LLM designer ───────────────────────────────────────
@router.post("/{period_id}/run")
def run_design(
    period_id: int,
    db: Session = Depends(get_db),
):
    """
    For every file in this period, run the entity-designer (with memory
    lookup) and persist the resulting EntityDesigns + relations.
    """
    period = _check_period(db, period_id)
    user_id = _resolve_user_id(db, period_id)
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    if not files:
        raise HTTPException(400, "No files in this period.  Upload first.")

    per_file_designs = []
    memory_hits = 0
    llm_calls = 0
    fallback_calls = 0

    for f in files:
        sample_rows = db.query(RawRecord).filter(RawRecord.file_id == f.id).limit(5).all()
        if not sample_rows:
            continue
        columns = list(sample_rows[0].raw_data.keys())
        sample_dicts = [r.raw_data for r in sample_rows]
        design = design_from_file(
            db=db,
            file_type=f.file_type or "unknown",
            columns=columns,
            sample_rows=sample_dicts,
            user_id=user_id,
            file_id=f.id,
        )
        if design.get("source") == "memory":
            memory_hits += 1
        elif design.get("source") == "llm":
            llm_calls += 1
        else:
            fallback_calls += 1
        per_file_designs.append(design)

    if not per_file_designs:
        raise HTTPException(400, "No raw records to analyse.")

    combined = merge_designs(per_file_designs)
    info = persist_design(
        db, period_id, combined,
        source="llm" if llm_calls else ("memory" if memory_hits else "fallback"),
    )

    return {
        "period_id": period_id,
        "period_label": period.label,
        "memory_hits": memory_hits,
        "llm_calls": llm_calls,
        "fallback_calls": fallback_calls,
        "entities_proposed": info["entities_persisted"],
        "relations_proposed": info["relations_persisted"],
        "design": assemble_graph(db, period_id),
    }


# ─── Sequence 2: assembled graph for the dashboard ─────────────────────────
@router.get("/{period_id}")
def get_design(
    period_id: int,
    db: Session = Depends(get_db),
):
    _check_period(db, period_id)
    graph = assemble_graph(db, period_id)
    user_id = _resolve_user_id(db, period_id)
    return {
        "period_id": period_id,
        "graph": graph,
        "memory": design_memory.stats(db, user_id=user_id),
    }


# ─── User edits an entity ───────────────────────────────────────────────────
class EntityPatch(BaseModel):
    label: Optional[str] = None
    category: Optional[str] = None
    objective: Optional[str] = None
    department: Optional[str] = None
    constraints: Optional[Dict[str, Any]] = None
    attributes: Optional[List[Dict[str, Any]]] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    color: Optional[str] = None
    user_notes: Optional[str] = None
    status: Optional[str] = Field(None, description="approved | edited | rejected")


@router.patch("/entity/{design_id}")
def patch_entity(
    design_id: int,
    patch: EntityPatch,
    db: Session = Depends(get_db),
):
    d = db.query(EntityDesign).get(design_id)
    if not d:
        raise HTTPException(404, "Entity design not found")

    fields = patch.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(d, k, v)
    if "status" not in fields:
        d.status = "edited"
    d.source = "user" if d.source != "user" else d.source
    d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    return {
        "id": d.id, "entity_key": d.entity_key,
        "status": d.status, "updated": True,
    }


# ─── User adds a relationship ───────────────────────────────────────────────
class RelationCreate(BaseModel):
    from_key: str
    to_key: str
    label: str = "links_to"
    cardinality: str = "1—N"
    objective: str = ""


@router.post("/{period_id}/relation")
def add_relation(
    period_id: int,
    body: RelationCreate,
    db: Session = Depends(get_db),
):
    _check_period(db, period_id)
    keys = {
        e.entity_key for e in db.query(EntityDesign).filter(
            EntityDesign.period_id == period_id
        ).all()
    }
    if body.from_key not in keys or body.to_key not in keys:
        raise HTTPException(400, "Both entities must exist in this period's design.")
    r = EntityRelationDesign(
        period_id=period_id,
        from_key=body.from_key,
        to_key=body.to_key,
        label=body.label or "links_to",
        cardinality=body.cardinality or "1—N",
        objective=body.objective or "",
        confidence=0.99,
        status="user_added",
        source="user",
        created_at=datetime.utcnow(),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id, "status": r.status}


@router.delete("/relation/{rel_id}")
def delete_relation(rel_id: int, db: Session = Depends(get_db)):
    r = db.query(EntityRelationDesign).get(rel_id)
    if not r:
        raise HTTPException(404, "Relation not found")
    db.delete(r)
    db.commit()
    return {"deleted": rel_id}


# ─── Approve + commit to memory ─────────────────────────────────────────────
@router.post("/{period_id}/approve")
def approve_design(
    period_id: int,
    db: Session = Depends(get_db),
):
    """
    Approve all entity designs for the period and write the resulting
    payload to the Design Memory layer so future uploads hit cache.
    """
    _check_period(db, period_id)
    user_id = _resolve_user_id(db, period_id)
    ents = db.query(EntityDesign).filter(EntityDesign.period_id == period_id).all()
    if not ents:
        raise HTTPException(400, "No entity designs to approve.")

    for e in ents:
        if e.status not in ("edited", "rejected"):
            e.status = "approved"
        e.updated_at = datetime.utcnow()
    rels = db.query(EntityRelationDesign).filter(
        EntityRelationDesign.period_id == period_id
    ).all()
    for r in rels:
        if r.status != "user_added":
            r.status = "approved"
    db.commit()

    # Persist per-file payloads to memory (group by source_file_id)
    by_file: Dict[Optional[int], Dict] = {}
    for e in ents:
        fid = e.source_file_id
        by_file.setdefault(fid, {"entities": [], "relations": []})
        by_file[fid]["entities"].append(_entity_to_dict(e))
    # relations are period-wide; attach to each file's payload
    rel_dicts = [_relation_to_dict(r) for r in rels]
    for v in by_file.values():
        v["relations"] = rel_dicts

    saved = 0
    for fid, payload in by_file.items():
        if fid is None:
            continue
        f = db.query(FileModel).get(fid)
        if not f:
            continue
        sample = db.query(RawRecord).filter(RawRecord.file_id == fid).first()
        if not sample:
            continue
        cols = list(sample.raw_data.keys())
        design_memory.remember(
            db,
            file_type=f.file_type or "unknown",
            columns=cols,
            payload=payload,
            user_id=user_id,
        )
        saved += 1

    return {
        "period_id": period_id,
        "entities_approved": len(ents),
        "relations_approved": len(rels),
        "memory_entries_saved": saved,
    }


def _entity_to_dict(e: EntityDesign) -> Dict:
    return {
        "entity_key": e.entity_key,
        "label": e.label,
        "category": e.category,
        "objective": e.objective,
        "department": e.department,
        "constraints": e.constraints or {},
        "attributes": e.attributes or [],
        "confidence": e.confidence,
        "color": e.color,
        "position_x": e.position_x,
        "position_y": e.position_y,
    }


def _relation_to_dict(r: EntityRelationDesign) -> Dict:
    return {
        "from_key": r.from_key,
        "to_key": r.to_key,
        "label": r.label,
        "cardinality": r.cardinality,
        "objective": r.objective,
        "confidence": r.confidence,
    }
