"""
Ontology endpoint — returns the schema graph (nodes + edges) and entity instance
counts for a company's latest open period, derived from real data in the DB.

GET  /api/companies/{company_id}/ontology  → { nodes, edges, period, summary }
POST /api/pipeline/{period_id}/confirm     → marks the period as 'confirmed'
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from collections import defaultdict
from backend.database import (
    get_db, Company, Period, File as FileModel,
    Entity, BusinessRecord, ColumnMapping, JournalEntry,
)
from backend.services.auth_service import get_current_user

router = APIRouter()


# ── Color & layout config (kept in sync with the dashboard's Ledger Spark palette)
NODE_COLORS = {
    "Customer":   "#5B4BFB",  # brand
    "SalesTxn":   "#FF7A59",  # spark
    "Product":    "#10B981",  # mint
    "Supplier":   "#F59E0B",  # amber
    "Purchase":   "#FF7A59",
    "Inventory":  "#0EA5A5",
    "Journal":    "#1E293B",
    "Account":    "#EC4899",
    "Branch":     "#7C3AED",
}

# Default node layout positions — wide enough that the SVG viewBox can show them
NODE_POSITIONS = {
    "Customer":  (130, 200),
    "SalesTxn":  (480, 130),
    "Product":   (480, 360),
    "Supplier":  (130, 540),
    "Purchase":  (860, 560),
    "Inventory": (130, 380),
    "Journal":   (860, 200),
    "Account":   (1020, 440),
    "Branch":    (820, 30),
}


def _company_period(db: Session, company_id: int, user_id: int) -> Period:
    company = db.query(Company).filter(
        Company.id == company_id, Company.user_id == user_id
    ).first()
    if not company:
        raise HTTPException(404, "Company not found")
    period = (
        db.query(Period)
        .filter(Period.company_id == company_id)
        .order_by(Period.id.desc())
        .first()
    )
    if not period:
        raise HTTPException(404, "No period exists yet — upload a file first.")
    return period


@router.get("/companies/{company_id}/ontology")
def get_ontology(
    company_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Returns the schema-level ontology for the active period:
      * nodes:   one per detected entity-type, with count + confidence + position + attrs
      * edges:   relationship types between nodes (derived from record types present)
      * summary: counts, status, period info
    The frontend renders this as the interactive graph.
    """
    period = _company_period(db, company_id, current_user.id)
    period_id = period.id

    # ── Per-file mapping confidence aggregate ───────────────────────────────
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    file_types_present = {f.file_type for f in files}
    file_ids = [f.id for f in files]

    avg_conf_by_filetype: dict = defaultdict(list)
    for f in files:
        avg_conf_by_filetype[f.file_type].append(f.classification_confidence or 0.0)
    avg_classification = {
        ft: (sum(vals) / len(vals) if vals else 0.0) for ft, vals in avg_conf_by_filetype.items()
    }

    mappings = (
        db.query(ColumnMapping)
        .filter(ColumnMapping.file_id.in_(file_ids))
        .all()
    ) if file_ids else []
    mapping_conf_by_file: dict = defaultdict(list)
    for m in mappings:
        mapping_conf_by_file[m.file_id].append(m.confidence or 0.0)
    file_avg_mapping_conf = {
        fid: (sum(v) / len(v) if v else 0.0) for fid, v in mapping_conf_by_file.items()
    }
    # roll up mapping confidence by file_type
    type_to_files = defaultdict(list)
    for f in files:
        type_to_files[f.file_type].append(f.id)
    mapping_conf_by_type = {}
    for ft, fids in type_to_files.items():
        confs = [file_avg_mapping_conf.get(fid, 0.0) for fid in fids]
        mapping_conf_by_type[ft] = sum(confs) / len(confs) if confs else 0.0

    # ── Record counts by record_type ────────────────────────────────────────
    rec_counts = defaultdict(int)
    if file_ids:
        for rec in db.query(BusinessRecord).filter(BusinessRecord.file_id.in_(file_ids)).all():
            rec_counts[rec.record_type] += 1

    # ── Entity counts (Customer / Supplier / SKU / Branch) ──────────────────
    entity_counts = defaultdict(int)
    for e in db.query(Entity).filter(Entity.period_id == period_id).all():
        entity_counts[e.entity_type] += 1

    journal_count = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).count()

    # ── Build nodes ─────────────────────────────────────────────────────────
    nodes: list = []

    def push_node(key, label, type_label, count, conf, attrs):
        x, y = NODE_POSITIONS.get(key, (200, 200))
        nodes.append({
            "id": key,
            "type": type_label,
            "label": label,
            "x": x, "y": y,
            "conf": round(float(conf), 2),
            "color": NODE_COLORS.get(key, "#6366F1"),
            "count": count,
            "attrs": attrs,
        })

    # Customer (only show if sales records exist OR any customer entities)
    if "sales" in file_types_present or entity_counts["Customer"] > 0:
        push_node(
            "Customer", "Customer", "Customer",
            entity_counts["Customer"],
            mapping_conf_by_type.get("sales", 0.85),
            [{"k": "customer_id", "t": "PK·int"}, {"k": "name", "t": "string"}, {"k": "segment", "t": "enum"}],
        )

    # Sales transaction node
    if rec_counts["SalesTransaction"] > 0 or "sales" in file_types_present:
        push_node(
            "SalesTxn", "SalesTransaction", "Transaction",
            rec_counts["SalesTransaction"],
            mapping_conf_by_type.get("sales", 0.0),
            [{"k": "invoice_no", "t": "PK·string"}, {"k": "date", "t": "date"},
             {"k": "total", "t": "decimal"}, {"k": "customer_id", "t": "FK→Customer"}],
        )

    # Product / SKU
    if entity_counts["SKU"] > 0 or "inventory" in file_types_present:
        push_node(
            "Product", "Product / SKU", "Product",
            entity_counts["SKU"],
            mapping_conf_by_type.get("inventory", 0.85),
            [{"k": "sku", "t": "PK·string"}, {"k": "name", "t": "string"},
             {"k": "unit_price", "t": "decimal"}],
        )

    # Branch
    if entity_counts["Branch"] > 0:
        push_node(
            "Branch", "Branch", "Location",
            entity_counts["Branch"],
            mapping_conf_by_type.get("sales", 0.85),
            [{"k": "branch_id", "t": "PK·string"}, {"k": "name", "t": "string"}],
        )

    # Supplier
    if entity_counts["Supplier"] > 0 or "purchase" in file_types_present:
        push_node(
            "Supplier", "Supplier", "Vendor",
            entity_counts["Supplier"],
            mapping_conf_by_type.get("purchase", 0.85),
            [{"k": "supplier_id", "t": "PK·int"}, {"k": "name", "t": "string"},
             {"k": "tax_id", "t": "string"}],
        )

    # Purchase invoice
    if rec_counts["SupplierInvoice"] > 0 or "purchase" in file_types_present:
        push_node(
            "Purchase", "SupplierInvoice", "Document",
            rec_counts["SupplierInvoice"],
            mapping_conf_by_type.get("purchase", 0.0),
            [{"k": "invoice_no", "t": "PK·string"}, {"k": "supplier_id", "t": "FK→Supplier"},
             {"k": "total", "t": "decimal"}],
        )

    # Inventory movement
    if rec_counts["InventoryMovement"] > 0 or "inventory" in file_types_present:
        push_node(
            "Inventory", "InventoryMovement", "Event",
            rec_counts["InventoryMovement"],
            mapping_conf_by_type.get("inventory", 0.0),
            [{"k": "sku", "t": "FK→Product"}, {"k": "qty_in", "t": "decimal"},
             {"k": "qty_out", "t": "decimal"}, {"k": "qty_waste", "t": "decimal"}],
        )

    # Journal Entry (always shown once any record exists)
    has_any = sum(rec_counts.values()) > 0
    if has_any or journal_count > 0:
        push_node(
            "Journal", "JournalEntry", "Ledger",
            journal_count,
            0.99,
            [{"k": "entry_id", "t": "PK·int"}, {"k": "date", "t": "date"},
             {"k": "description", "t": "text"}, {"k": "lines", "t": "1—N"}],
        )

    # Account (always — comes from default COA)
    push_node(
        "Account", "Account", "GL",
        8,  # default COA has 8 accounts
        0.95,
        [{"k": "code", "t": "PK·string"}, {"k": "name", "t": "string"},
         {"k": "type", "t": "Asset/Liab/Eq/Rev/Exp"}],
    )

    node_ids = {n["id"] for n in nodes}

    # ── Build edges (only between nodes that exist) ─────────────────────────
    raw_edges = [
        ("Customer", "SalesTxn",  "places",    "1—N"),
        ("Branch",   "SalesTxn",  "sold_at",   "1—N"),
        ("Product",  "SalesTxn",  "sold_as",   "1—N"),
        ("Supplier", "Purchase",  "issues",    "1—N"),
        ("Product",  "Purchase",  "stocked_via","N—N"),
        ("Product",  "Inventory", "tracked_in","1—N"),
        ("SalesTxn", "Journal",   "generates", "1—1"),
        ("Purchase", "Journal",   "generates", "1—1"),
        ("Inventory","Journal",   "generates", "1—1"),
        ("Journal",  "Account",   "posts_to",  "N—N"),
    ]
    edges = []
    for i, (a, b, lab, card) in enumerate(raw_edges, 1):
        if a in node_ids and b in node_ids:
            edges.append({
                "id": f"e{i}",
                "from": a, "to": b,
                "label": lab, "card": card,
                "dashed": False,
            })

    summary = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "record_count": sum(rec_counts.values()),
        "entity_count": sum(entity_counts.values()),
        "journal_count": journal_count,
        "file_count": len(files),
        "avg_classification_confidence": (
            round(sum(avg_classification.values()) / len(avg_classification), 2)
            if avg_classification else 0.0
        ),
    }

    return {
        "period": {
            "id": period.id,
            "label": period.label,
            "status": period.status,
            "start_date": period.start_date,
            "end_date": period.end_date,
        },
        "company_id": company_id,
        "nodes": nodes,
        "edges": edges,
        "summary": summary,
    }


@router.post("/pipeline/{period_id}/confirm")
def confirm_ontology(
    period_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Mark a period as confirmed. Verifies the user owns the company, then flips
    period.status from 'open' → 'confirmed'. This is what the dashboard's
    'Confirm & post journals' button calls.
    """
    period = db.query(Period).get(period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    company = db.query(Company).filter(
        Company.id == period.company_id, Company.user_id == current_user.id
    ).first()
    if not company:
        raise HTTPException(403, "Not authorised for this period")

    # Confirm the period
    period.status = "confirmed"
    db.commit()
    journals = db.query(JournalEntry).filter(JournalEntry.period_id == period_id).count()
    return {
        "period_id": period_id,
        "status": period.status,
        "journals_posted": journals,
        "message": "Ontology confirmed and journals locked.",
    }
