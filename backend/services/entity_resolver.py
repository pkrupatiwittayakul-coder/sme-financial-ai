"""Resolve entities (branches, SKUs, suppliers, accounts) from business records."""
from typing import List, Dict, Any
import re


def normalize_name(name: str) -> str:
    """Strip punctuation, lowercase, remove common prefixes for matching."""
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r"[.\-_/\\,]", " ", n)
    n = re.sub(r"\s+", " ", n)
    # Remove Thai honorifics / company suffixes
    for remove in ["co ltd", "co,ltd", "บจก", "บริษัท", "จำกัด", "หจก", "ร้าน"]:
        n = n.replace(remove, "").strip()
    return n


def extract_entities_from_records(
    records: List[Dict], period_id: int
) -> List[Dict]:
    """
    Scan business records and extract unique entities.
    Returns list of entity dicts ready to be inserted into DB.
    """
    seen: Dict[str, set] = {
        "Branch": set(),
        "SKU": set(),
        "Supplier": set(),
        "Customer": set(),
    }
    entities = []

    for rec in records:
        nd = rec.get("normalized_data", {})
        rtype = rec.get("record_type")

        if rtype == "SalesTransaction":
            _add_entity(entities, seen, "Branch", nd.get("branch_id"), period_id)
            _add_entity(entities, seen, "SKU", nd.get("sku_id"), period_id,
                        extra={"product_name": nd.get("product_name")})
            _add_entity(entities, seen, "Customer", nd.get("customer_id"), period_id)

        elif rtype == "SupplierInvoice":
            _add_entity(entities, seen, "Supplier", nd.get("supplier_id"), period_id,
                        extra={"supplier_name": nd.get("supplier_name")})
            _add_entity(entities, seen, "SKU", nd.get("sku_id"), period_id)

        elif rtype == "InventoryMovement":
            _add_entity(entities, seen, "SKU", nd.get("sku_id"), period_id,
                        extra={"product_name": nd.get("product_name")})

    return entities


def _add_entity(
    entities: List, seen: Dict, entity_type: str,
    name: Any, period_id: int, extra: Dict = None
):
    if not name:
        return
    key = normalize_name(str(name))
    if not key or key in seen[entity_type]:
        return
    seen[entity_type].add(key)
    entities.append({
        "period_id": period_id,
        "entity_type": entity_type,
        "entity_name": str(name).strip(),
        "attributes": extra or {},
    })


def build_relationships_from_records(
    records: List[Dict],
    entity_lookup: Dict[str, int]   # (entity_type, normalized_name) -> entity_id
) -> List[Dict]:
    """
    Build graph relationships between entities and records.
    Returns list of relationship dicts.
    """
    relationships = []

    for rec in records:
        nd = rec.get("normalized_data", {})
        rtype = rec.get("record_type")
        rec_id = rec.get("id")

        if rtype == "SalesTransaction":
            branch_id = _lookup(entity_lookup, "Branch", nd.get("branch_id"))
            sku_id = _lookup(entity_lookup, "SKU", nd.get("sku_id"))
            if branch_id and rec_id:
                relationships.append({
                    "source_entity_id": rec_id,
                    "relationship_type": "SOLD_AT",
                    "target_entity_id": branch_id,
                    "evidence": f"SalesTransaction {rec_id}",
                    "business_record_id": rec_id,
                })
            if sku_id and rec_id:
                relationships.append({
                    "source_entity_id": rec_id,
                    "relationship_type": "INVOLVES",
                    "target_entity_id": sku_id,
                    "evidence": f"SalesTransaction {rec_id}",
                    "business_record_id": rec_id,
                })

        elif rtype == "SupplierInvoice":
            supplier_id = _lookup(entity_lookup, "Supplier", nd.get("supplier_id"))
            if supplier_id and rec_id:
                relationships.append({
                    "source_entity_id": rec_id,
                    "relationship_type": "ISSUED_BY",
                    "target_entity_id": supplier_id,
                    "evidence": f"SupplierInvoice {rec_id}",
                    "business_record_id": rec_id,
                })

    return relationships


def _lookup(lookup: Dict, entity_type: str, name: Any) -> int:
    if not name:
        return None
    key = (entity_type, normalize_name(str(name)))
    return lookup.get(key)
