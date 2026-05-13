"""
Sequence 1 — LLM Entity Designer
=================================
Sends raw file data (columns + a small sample of rows) to an external LLM
and asks it to *design* the entities those rows represent.  For every
entity the LLM must answer:

    * label / category — what kind of thing this is
    * objective        — why this data exists, what it's used for
    * department       — which business unit owns it
    * constraints      — primary key, required fields, value rules
    * attributes       — fields with type + short description
    * relations        — likely links to other entities in the same period

The Design Memory layer is consulted first: if we've seen the same
file_type + columns fingerprint before, we return the cached design
without calling the LLM.  This keeps results stable and cheap.

When no API key is available — or the LLM call fails — we fall back to a
deterministic rule-based design so the rest of the pipeline can still run.
"""
from __future__ import annotations

import json
import re
from typing import List, Dict, Optional, Any
import anthropic

from backend.config import ANTHROPIC_API_KEY, LLM_MODEL
from backend.services import design_memory


# ── Visual styling shared with the ontology graph ───────────────────────────
DEFAULT_COLORS = {
    "Customer":   "#5B4BFB",
    "SalesTxn":   "#FF7A59",
    "Product":    "#10B981",
    "SKU":        "#10B981",
    "Supplier":   "#F59E0B",
    "Purchase":   "#FF7A59",
    "Inventory":  "#0EA5A5",
    "Journal":    "#1E293B",
    "Account":    "#EC4899",
    "Branch":     "#7C3AED",
    "Bank":       "#0EA5A5",
    "Employee":   "#FACC15",
}

# Layout grid used when LLM doesn't return positions
DEFAULT_LAYOUT = {
    "Customer":  (130, 200),
    "SalesTxn":  (480, 130),
    "Product":   (480, 360),
    "SKU":       (480, 360),
    "Supplier":  (130, 540),
    "Purchase":  (860, 560),
    "Inventory": (130, 380),
    "Journal":   (860, 200),
    "Account":   (1020, 440),
    "Branch":    (820, 30),
    "Bank":      (320, 540),
    "Employee":  (320, 30),
}


# ── Public API ──────────────────────────────────────────────────────────────
def design_from_file(
    *,
    db,                          # sqlalchemy Session (memory lookup)
    file_type: str,
    columns: List[str],
    sample_rows: List[Dict[str, Any]],
    user_id: Optional[int] = None,
    file_id: Optional[int] = None,
) -> Dict:
    """
    Returns:
      {
        "source": "memory" | "llm" | "fallback",
        "entities": [ { entity_key, label, category, objective, department,
                        constraints, attributes, color, position_x, position_y,
                        confidence } ],
        "relations": [ { from_key, to_key, label, cardinality, objective,
                         confidence } ]
      }
    """
    # 1. Memory hit?
    cached = design_memory.lookup(db, file_type, columns, user_id=user_id)
    if cached and cached.get("payload"):
        payload = _ensure_payload_shape(cached["payload"], file_type, file_id)
        payload["source"] = "memory"
        return payload

    # 2. Try LLM
    if ANTHROPIC_API_KEY:
        try:
            payload = _llm_design(file_type, columns, sample_rows)
            if payload and payload.get("entities"):
                payload = _ensure_payload_shape(payload, file_type, file_id)
                payload["source"] = "llm"
                return payload
        except Exception as exc:    # noqa: BLE001
            print(f"[entity_designer] LLM failed, falling back: {exc}")

    # 3. Deterministic fallback
    payload = _fallback_design(file_type, columns, sample_rows)
    payload = _ensure_payload_shape(payload, file_type, file_id)
    payload["source"] = "fallback"
    return payload


# ── LLM call ────────────────────────────────────────────────────────────────
_LLM_PROMPT = """You are a senior data architect for a small/medium business
accounting platform.  You will be shown the *headers* and a *small sample*
of rows from a single uploaded file.  Your job is to design the entities
this file represents so that downstream code can build an interactive
relationship graph and post correct accounting journals.

File type the user said this is: {file_type}
Columns: {columns}
Sample rows (truncated):
{sample}

Return STRICT JSON with this exact shape (no prose, no markdown fences):

{{
  "entities": [
    {{
      "entity_key": "PascalCase identifier — short, e.g. Customer, SalesTxn, Supplier",
      "label": "Human-friendly label",
      "category": "Transaction | Master | Document | Event | GL | Location",
      "objective": "WHY this data exists — 1-2 sentences explaining what business decisions or processes it supports.",
      "department": "Sales | Finance | Operations | Procurement | Inventory | HR",
      "constraints": {{
          "primary_key": "field_name or null",
          "required":   ["field_a","field_b"],
          "unique":     [],
          "value_rules":["amount > 0", "..."]
      }},
      "attributes": [
        {{"k": "field_name", "t": "type (PK·int, FK→X, date, decimal, string, enum)", "desc": "1-line description"}}
      ],
      "confidence": 0.0
    }}
  ],
  "relations": [
    {{
      "from_key": "Source entity_key",
      "to_key":   "Target entity_key",
      "label":    "places | issues | sold_at | generates | posts_to | tracked_in | stocked_via",
      "cardinality": "1—1 | 1—N | N—N",
      "objective":   "Why this connection matters to the business.",
      "confidence":  0.0
    }}
  ]
}}

Rules:
1. Always include a `JournalEntry` entity with a relation FROM the main
   transaction entity TO `JournalEntry` labelled "generates", and a relation
   FROM `JournalEntry` TO `Account` labelled "posts_to".
2. Always include an `Account` entity (the GL).
3. Master-data entities (Customer/Supplier/Product/Branch) should appear
   only when columns suggest them.
4. Objective MUST mention the department or process that owns the data.
5. Keep entity_key consistent: Customer, Supplier, SalesTxn, Purchase,
   Inventory, Product/SKU, Branch, Bank, Account, Journal, Employee.
6. Do not invent fields that aren't in the sample columns; you may infer
   foreign keys from naming patterns (e.g. customer_id → FK→Customer).
"""


def _llm_design(file_type: str, columns: List[str], sample_rows: List[Dict]) -> Dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    sample = json.dumps(sample_rows[:5], default=str, ensure_ascii=False, indent=2)
    prompt = _LLM_PROMPT.format(
        file_type=file_type or "unknown",
        columns=json.dumps(columns, ensure_ascii=False),
        sample=sample,
    )
    msg = client.messages.create(
        model=LLM_MODEL,
        max_tokens=2400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    # Strip code fences if any
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    # Try to slice to the JSON body
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        return {}
    return parsed


# ── Fallback (no API key / API error) ───────────────────────────────────────
def _fallback_design(file_type: str, columns: List[str], sample_rows: List[Dict]) -> Dict:
    """Pick a sensible entity set from the file_type and column names."""
    cols_lower = [c.lower() for c in columns]
    entities: List[Dict] = []
    relations: List[Dict] = []

    def push(key, label, category, obj, dept, attrs, conf=0.7):
        entities.append({
            "entity_key": key, "label": label, "category": category,
            "objective": obj, "department": dept,
            "constraints": {"primary_key": attrs[0]["k"] if attrs else None,
                            "required": [a["k"] for a in attrs[:3]],
                            "unique": [], "value_rules": []},
            "attributes": attrs, "confidence": conf,
        })

    if file_type == "sales":
        push("Customer", "Customer", "Master",
             "Identifies the buyers placing orders so Sales can analyse repeat business and credit risk.",
             "Sales",
             [{"k":"customer_id","t":"PK·int","desc":"Stable id"},
              {"k":"name","t":"string","desc":"Customer name"}], 0.8)
        push("Branch", "Branch", "Location",
             "Where the sale occurred — used by Operations for store-level performance.",
             "Operations",
             [{"k":"branch_id","t":"PK·string","desc":"Branch code"},
              {"k":"name","t":"string","desc":"Branch label"}], 0.75)
        push("SKU", "Product / SKU", "Master",
             "What was sold; lets Finance compute COGS and Operations track demand.",
             "Inventory",
             [{"k":"sku","t":"PK·string","desc":"SKU code"},
              {"k":"product_name","t":"string","desc":"Display name"}], 0.85)
        push("SalesTxn", "Sales Transaction", "Transaction",
             "Each sale event the Sales team needs to recognise as revenue.",
             "Sales",
             [{"k":"invoice_no","t":"PK·string","desc":"Doc id"},
              {"k":"date","t":"date","desc":"Sale date"},
              {"k":"total","t":"decimal","desc":"Gross amount"},
              {"k":"customer_id","t":"FK→Customer","desc":"Buyer"}], 0.9)
        relations += [
            {"from_key":"Customer","to_key":"SalesTxn","label":"places","cardinality":"1—N",
             "objective":"A customer can place many sales transactions.","confidence":0.9},
            {"from_key":"Branch","to_key":"SalesTxn","label":"sold_at","cardinality":"1—N",
             "objective":"A branch hosts many sales.","confidence":0.85},
            {"from_key":"SKU","to_key":"SalesTxn","label":"sold_as","cardinality":"1—N",
             "objective":"A SKU appears in many sales.","confidence":0.85},
            {"from_key":"SalesTxn","to_key":"Journal","label":"generates","cardinality":"1—1",
             "objective":"Each sale must produce a journal entry.","confidence":0.99},
        ]

    elif file_type == "purchase":
        push("Supplier","Supplier","Master",
             "Vendors providing goods/services — Procurement and Finance use this to manage AP.",
             "Procurement",
             [{"k":"supplier_id","t":"PK·int","desc":"Stable id"},
              {"k":"name","t":"string","desc":"Supplier name"}], 0.85)
        push("Purchase","Supplier Invoice","Document",
             "Recorded so Finance can pay suppliers on time and recognise expense/inventory.",
             "Procurement",
             [{"k":"invoice_no","t":"PK·string","desc":"Doc id"},
              {"k":"date","t":"date","desc":"Invoice date"},
              {"k":"total","t":"decimal","desc":"Total payable"},
              {"k":"supplier_id","t":"FK→Supplier","desc":"Vendor"}], 0.9)
        relations += [
            {"from_key":"Supplier","to_key":"Purchase","label":"issues","cardinality":"1—N",
             "objective":"A supplier issues many invoices.","confidence":0.9},
            {"from_key":"Purchase","to_key":"Journal","label":"generates","cardinality":"1—1",
             "objective":"Each invoice yields one journal entry.","confidence":0.99},
        ]

    elif file_type == "inventory":
        push("SKU","Product / SKU","Master",
             "What is in stock — Inventory uses this to track quantity & value.",
             "Inventory",
             [{"k":"sku","t":"PK·string","desc":"SKU"},
              {"k":"product_name","t":"string","desc":"Name"}], 0.85)
        push("Inventory","Inventory Movement","Event",
             "Every in/out/waste movement so Operations and Finance can reconcile stock.",
             "Inventory",
             [{"k":"sku","t":"FK→SKU","desc":"Item"},
              {"k":"qty_in","t":"decimal","desc":"Received"},
              {"k":"qty_out","t":"decimal","desc":"Issued"},
              {"k":"qty_waste","t":"decimal","desc":"Scrap"}], 0.85)
        relations += [
            {"from_key":"SKU","to_key":"Inventory","label":"tracked_in","cardinality":"1—N",
             "objective":"Each SKU has many stock movements.","confidence":0.9},
            {"from_key":"Inventory","to_key":"Journal","label":"generates","cardinality":"1—1",
             "objective":"Inventory movements may post adjustment journals.","confidence":0.8},
        ]

    elif file_type == "bank":
        push("Bank","Bank Transaction","Event",
             "Bank line items used by Finance to reconcile cash to the GL.",
             "Finance",
             [{"k":"date","t":"date","desc":"Posting date"},
              {"k":"description","t":"string","desc":"Narrative"},
              {"k":"debit","t":"decimal","desc":"Out"},
              {"k":"credit","t":"decimal","desc":"In"}], 0.9)
        relations += [
            {"from_key":"Bank","to_key":"Journal","label":"generates","cardinality":"1—1",
             "objective":"Each bank line maps to one journal entry.","confidence":0.85},
        ]

    # Always include Journal + Account
    push("Journal","Journal Entry","GL",
         "The accounting record of every business event — Finance posts to GL accounts.",
         "Finance",
         [{"k":"entry_id","t":"PK·int","desc":"Entry id"},
          {"k":"date","t":"date","desc":"Posting date"},
          {"k":"description","t":"text","desc":"Narrative"}], 0.95)
    push("Account","Chart of Accounts","GL",
         "Standard GL accounts used to classify journal lines.",
         "Finance",
         [{"k":"code","t":"PK·string","desc":"Account code"},
          {"k":"name","t":"string","desc":"Account name"},
          {"k":"type","t":"enum","desc":"Asset/Liab/Eq/Rev/Exp"}], 0.95)
    relations.append(
        {"from_key":"Journal","to_key":"Account","label":"posts_to","cardinality":"N—N",
         "objective":"Each journal line posts to a GL account.","confidence":0.99}
    )

    return {"entities": entities, "relations": relations}


# ── Normaliser: make sure every entity has color + position + confidence ────
def _ensure_payload_shape(payload: Dict, file_type: str, file_id: Optional[int]) -> Dict:
    payload = dict(payload or {})
    ents = list(payload.get("entities") or [])
    rels = list(payload.get("relations") or [])

    seen_keys = set()
    clean_ents = []
    for i, e in enumerate(ents):
        key = (e.get("entity_key") or e.get("label") or f"Entity{i}").strip()
        if not key:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        color = e.get("color") or DEFAULT_COLORS.get(key, "#6366F1")
        pos = e.get("position") or {}
        px, py = DEFAULT_LAYOUT.get(key, (200 + (i % 4) * 220, 120 + (i // 4) * 200))
        px = float(pos.get("x", e.get("position_x", px)))
        py = float(pos.get("y", e.get("position_y", py)))
        clean_ents.append({
            "entity_key": key,
            "label": e.get("label") or key,
            "category": e.get("category") or "Master",
            "objective": (e.get("objective") or "").strip(),
            "department": e.get("department") or "Finance",
            "constraints": e.get("constraints") or {},
            "attributes": e.get("attributes") or [],
            "confidence": float(e.get("confidence") or 0.7),
            "color": color,
            "position_x": px,
            "position_y": py,
            "source_file_id": file_id,
        })

    clean_rels = []
    seen_pairs = set()
    for r in rels:
        a, b = r.get("from_key"), r.get("to_key")
        if not a or not b or (a, b, r.get("label")) in seen_pairs:
            continue
        if a not in seen_keys or b not in seen_keys:
            continue
        seen_pairs.add((a, b, r.get("label")))
        clean_rels.append({
            "from_key": a,
            "to_key": b,
            "label": r.get("label") or "links_to",
            "cardinality": r.get("cardinality") or "1—N",
            "objective": (r.get("objective") or "").strip(),
            "confidence": float(r.get("confidence") or 0.6),
        })

    return {"entities": clean_ents, "relations": clean_rels}


# ── Merge helper — combines designs from several files into one period ──────
def merge_designs(designs: List[Dict]) -> Dict:
    """
    Combine per-file designs into one period-wide design.  Entities with the
    same `entity_key` are merged (union of attributes, max confidence).
    """
    entities_by_key: Dict[str, Dict] = {}
    relations_set = {}

    for d in designs:
        for e in d.get("entities", []):
            k = e["entity_key"]
            if k not in entities_by_key:
                entities_by_key[k] = dict(e)
                entities_by_key[k]["attributes"] = list(e.get("attributes") or [])
                continue
            cur = entities_by_key[k]
            # union attributes by k
            seen_attrs = {a.get("k") for a in cur["attributes"]}
            for a in e.get("attributes") or []:
                if a.get("k") not in seen_attrs:
                    cur["attributes"].append(a)
                    seen_attrs.add(a.get("k"))
            cur["confidence"] = max(cur.get("confidence", 0), e.get("confidence", 0))
            # prefer a non-empty objective
            if not cur.get("objective") and e.get("objective"):
                cur["objective"] = e["objective"]
        for r in d.get("relations", []):
            key = (r["from_key"], r["to_key"], r.get("label"))
            if key not in relations_set:
                relations_set[key] = r

    return {
        "entities": list(entities_by_key.values()),
        "relations": list(relations_set.values()),
    }
