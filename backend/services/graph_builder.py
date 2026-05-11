"""
Build company knowledge graph edges from structured business records.

Edge types per PDF spec (p.9):
  SOLD_AT       SalesTransaction → Branch
  INVOLVES      SalesTransaction → SKU
  POSTS_TO      SalesTransaction → Account (Revenue)
  CREATES       SalesTransaction → Account (COGS)
  REDUCES       SalesTransaction → Account (Inventory)
  ISSUED_BY     SupplierInvoice  → Supplier
  ADDS_TO       SupplierInvoice  → Account (Inventory/AP)
  MOVES         InventoryMovement → SKU
  AFFECTS       InventoryMovement → Account
  SUPPORTED_BY  StatementLine    → BusinessRecord (added later)
"""
from typing import List, Dict


def build_graph(records: List[Dict], entity_map: Dict[str, int]) -> List[Dict]:
    """
    Build graph edges given a list of business record dicts and
    a {entity_key: entity_db_id} map produced by entity_resolver.

    Returns list of edge dicts:
      {source, type, target, evidence, record_id}
    """
    edges = []

    for rec in records:
        rtype = rec.get("record_type")
        nd = rec.get("normalized_data", {})
        rec_id = rec.get("id")

        if rtype == "SalesTransaction":
            branch_key = f"Branch:{nd.get('branch_id', '')}".lower()
            sku_key = f"SKU:{nd.get('sku_id', '')}".lower()
            rev_key = "Account:4000"
            cogs_key = "Account:5000"
            inv_key = "Account:1300"

            rec_entity_key = f"SalesTransaction:{rec_id}"
            src = entity_map.get(rec_entity_key)
            if not src:
                continue

            _add_edge(edges, src, "SOLD_AT",  entity_map.get(branch_key), rec_id,
                      f"Sale {rec_id} at branch {nd.get('branch_id')}")
            _add_edge(edges, src, "INVOLVES", entity_map.get(sku_key), rec_id,
                      f"Sale {rec_id} involves SKU {nd.get('sku_id')}")
            _add_edge(edges, src, "POSTS_TO", entity_map.get(rev_key), rec_id,
                      f"Sale {rec_id} posts to Sales Revenue")
            if nd.get("cost_amount", 0) > 0:
                _add_edge(edges, src, "CREATES",  entity_map.get(cogs_key), rec_id,
                          f"Sale {rec_id} creates COGS entry")
                _add_edge(edges, src, "REDUCES",  entity_map.get(inv_key), rec_id,
                          f"Sale {rec_id} reduces Inventory")

        elif rtype == "SupplierInvoice":
            sup_key = f"Supplier:{nd.get('supplier_id', nd.get('supplier_name', ''))}".lower()
            ap_key = "Account:2100"
            inv_key = "Account:1300"

            rec_entity_key = f"SupplierInvoice:{rec_id}"
            src = entity_map.get(rec_entity_key)
            if not src:
                continue

            _add_edge(edges, src, "ISSUED_BY", entity_map.get(sup_key), rec_id,
                      f"Invoice {nd.get('invoice_number')} issued by {nd.get('supplier_name')}")
            _add_edge(edges, src, "ADDS_TO",   entity_map.get(inv_key), rec_id,
                      f"Invoice adds to Inventory account")
            _add_edge(edges, src, "CREATES_AP", entity_map.get(ap_key), rec_id,
                      f"Invoice creates Accounts Payable")

        elif rtype == "InventoryMovement":
            sku_key = f"SKU:{nd.get('sku_id', '')}".lower()
            inv_key = "Account:1300"

            rec_entity_key = f"InventoryMovement:{rec_id}"
            src = entity_map.get(rec_entity_key)
            if not src:
                continue

            _add_edge(edges, src, "MOVES",   entity_map.get(sku_key), rec_id,
                      f"Inventory movement for SKU {nd.get('sku_id')}")
            _add_edge(edges, src, "AFFECTS", entity_map.get(inv_key), rec_id,
                      f"Movement affects Inventory account")

    return edges


def _add_edge(edges, source, rel_type, target, record_id, evidence):
    if source and target:
        edges.append({
            "source": source,
            "type": rel_type,
            "target": target,
            "record_id": record_id,
            "evidence": evidence,
        })
