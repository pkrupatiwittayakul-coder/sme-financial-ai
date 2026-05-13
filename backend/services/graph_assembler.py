"""
Sequence 2 — Graph Assembler
=============================
Takes the EntityDesign blueprints proposed by the LLM in Sequence 1 and
*assembles* them into the interactive ontology graph the user sees and
edits.  This module is intentionally thin — the heavy lifting (deciding
what entities exist and why) is done by `entity_designer.py`.  Here we:

  1. Persist EntityDesign + EntityRelationDesign rows for the period.
  2. Re-attach instance counts (how many real rows back each entity).
  3. Produce a `{nodes, edges, summary}` payload for the dashboard.

The user can later edit any node's objective/constraints, drag-link new
relationships, or accept/reject the LLM's proposals.  Those edits are
saved back via the entity_design API and *remembered* by the memory
layer for next time.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database import (
    EntityDesign, EntityRelationDesign, Entity,
    BusinessRecord, File as FileModel, JournalEntry,
)


# ── Persist designs ──────────────────────────────────────────────────────────
def persist_design(
    db: Session,
    period_id: int,
    payload: Dict,
    *,
    source: str = "llm",
    file_id: Optional[int] = None,
    replace: bool = True,
) -> Dict[str, int]:
    """
    Persist entities & relations for a period.

    `payload` is the dict produced by entity_designer.design_from_file (or
    merge_designs).  When `replace=True` any existing un-edited designs
    for the period are wiped first; user-edited rows are preserved.
    """
    if replace:
        # Keep user-edited rows; remove only auto-generated ones
        db.query(EntityDesign).filter(
            EntityDesign.period_id == period_id,
            EntityDesign.status.in_(["proposed", "approved"]),
            EntityDesign.source.in_(["llm", "memory", "fallback"]),
        ).delete(synchronize_session=False)
        db.query(EntityRelationDesign).filter(
            EntityRelationDesign.period_id == period_id,
            EntityRelationDesign.status.in_(["proposed", "approved"]),
            EntityRelationDesign.source.in_(["llm", "memory", "fallback"]),
        ).delete(synchronize_session=False)
        db.commit()

    existing_keys = {
        r.entity_key for r in db.query(EntityDesign).filter(
            EntityDesign.period_id == period_id
        ).all()
    }

    n_ent = 0
    for e in payload.get("entities", []):
        if e["entity_key"] in existing_keys:
            continue
        db.add(EntityDesign(
            period_id=period_id,
            source_file_id=e.get("source_file_id") or file_id,
            entity_key=e["entity_key"],
            label=e.get("label") or e["entity_key"],
            category=e.get("category") or "Master",
            objective=e.get("objective") or "",
            department=e.get("department") or "Finance",
            constraints=e.get("constraints") or {},
            attributes=e.get("attributes") or [],
            confidence=float(e.get("confidence") or 0.7),
            status="proposed",
            position_x=float(e.get("position_x") or 200.0),
            position_y=float(e.get("position_y") or 200.0),
            color=e.get("color") or "#6366F1",
            source=source,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))
        n_ent += 1
        existing_keys.add(e["entity_key"])

    existing_rel = {
        (r.from_key, r.to_key, r.label)
        for r in db.query(EntityRelationDesign).filter(
            EntityRelationDesign.period_id == period_id
        ).all()
    }
    n_rel = 0
    for r in payload.get("relations", []):
        sig = (r["from_key"], r["to_key"], r.get("label"))
        if sig in existing_rel:
            continue
        db.add(EntityRelationDesign(
            period_id=period_id,
            from_key=r["from_key"],
            to_key=r["to_key"],
            label=r.get("label") or "links_to",
            cardinality=r.get("cardinality") or "1—N",
            objective=r.get("objective") or "",
            confidence=float(r.get("confidence") or 0.6),
            status="proposed",
            source=source,
            created_at=datetime.utcnow(),
        ))
        existing_rel.add(sig)
        n_rel += 1

    db.commit()
    return {"entities_persisted": n_ent, "relations_persisted": n_rel}


# ── Assemble graph payload for the frontend ─────────────────────────────────
def assemble_graph(db: Session, period_id: int) -> Dict:
    designs = (
        db.query(EntityDesign)
        .filter(EntityDesign.period_id == period_id)
        .order_by(EntityDesign.id.asc())
        .all()
    )
    relations = (
        db.query(EntityRelationDesign)
        .filter(EntityRelationDesign.period_id == period_id)
        .all()
    )

    # Instance-level counts to surface on each node
    entity_rows = db.query(Entity).filter(Entity.period_id == period_id).all()
    instance_counts: Dict[str, int] = defaultdict(int)
    for e in entity_rows:
        instance_counts[e.entity_type] += 1

    file_ids = [f.id for f in db.query(FileModel).filter(FileModel.period_id == period_id).all()]
    rec_counts: Dict[str, int] = defaultdict(int)
    if file_ids:
        for rec in db.query(BusinessRecord).filter(BusinessRecord.file_id.in_(file_ids)).all():
            rec_counts[rec.record_type] += 1

    journal_count = (
        db.query(JournalEntry).filter(JournalEntry.period_id == period_id).count()
    )

    def _count_for(key: str) -> int:
        # Map entity_key to one of (entity_type, record_type) counters
        if key in ("Customer", "Branch", "Supplier", "SKU", "Product"):
            return instance_counts.get(key, 0) or instance_counts.get("SKU" if key == "Product" else key, 0)
        if key == "SalesTxn":
            return rec_counts.get("SalesTransaction", 0)
        if key == "Purchase":
            return rec_counts.get("SupplierInvoice", 0)
        if key == "Inventory":
            return rec_counts.get("InventoryMovement", 0)
        if key == "Bank":
            return rec_counts.get("BankTransaction", 0)
        if key == "Journal":
            return journal_count
        if key == "Account":
            return 8  # default COA size
        return 0

    nodes: List[Dict] = []
    valid_keys = set()
    for d in designs:
        valid_keys.add(d.entity_key)
        nodes.append({
            "id": d.entity_key,
            "design_id": d.id,
            "label": d.label,
            "category": d.category,
            "objective": d.objective,
            "department": d.department,
            "type": d.category,
            "attrs": d.attributes or [],
            "constraints": d.constraints or {},
            "x": d.position_x,
            "y": d.position_y,
            "color": d.color or "#6366F1",
            "conf": round(float(d.confidence or 0), 2),
            "count": _count_for(d.entity_key),
            "status": d.status,
            "source": d.source,
            "user_notes": d.user_notes or "",
        })

    edges: List[Dict] = []
    for i, r in enumerate(relations, 1):
        if r.from_key not in valid_keys or r.to_key not in valid_keys:
            continue
        edges.append({
            "id": f"e{i}-{r.id}",
            "rel_id": r.id,
            "from": r.from_key,
            "to": r.to_key,
            "label": r.label,
            "card": r.cardinality,
            "objective": r.objective,
            "conf": round(float(r.confidence or 0), 2),
            "status": r.status,
            "source": r.source,
            "dashed": r.status == "user_added",
        })

    summary = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "record_count": sum(rec_counts.values()),
        "entity_count": sum(instance_counts.values()),
        "journal_count": journal_count,
        "file_count": len(file_ids),
        "approved_nodes": sum(1 for n in nodes if n["status"] == "approved"),
        "edited_nodes": sum(1 for n in nodes if n["status"] == "edited"),
        "user_added_edges": sum(1 for e in edges if e["status"] == "user_added"),
    }
    return {"nodes": nodes, "edges": edges, "summary": summary}
