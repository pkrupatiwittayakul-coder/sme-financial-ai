"""Convert raw rows into structured BusinessRecord objects."""
from typing import List, Dict, Any, Optional
from datetime import datetime


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def safe_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none", "") else None


def extract_sales_records(
    rows: List[Dict], mapping: Dict[str, str], file_id: int
) -> List[Dict]:
    """Convert rows from a sales file into SalesTransaction records."""
    records = []
    for i, row in enumerate(rows):
        mapped = _apply_mapping(row, mapping)
        amount = safe_float(mapped.get("sales_amount"))
        if amount == 0:
            continue   # Skip blank rows

        rec = {
            "file_id": file_id,
            "row_number": i,
            "record_type": "SalesTransaction",
            "date": safe_str(mapped.get("date")) or _today(),
            "amount": amount,
            "normalized_data": {
                "branch_id":       safe_str(mapped.get("branch_id")),
                "sku_id":          safe_str(mapped.get("sku_id")),
                "product_name":    safe_str(mapped.get("product_name")),
                "quantity_sold":   safe_float(mapped.get("quantity_sold")),
                "sales_amount":    amount,
                "cost_amount":     safe_float(mapped.get("cost_amount")),
                "discount":        safe_float(mapped.get("discount")),
                "vat":             safe_float(mapped.get("vat")),
                "customer_id":     safe_str(mapped.get("customer_id")),
                "payment_method":  safe_str(mapped.get("payment_method")),
            },
        }
        records.append(rec)
    return records


def extract_purchase_records(
    rows: List[Dict], mapping: Dict[str, str], file_id: int
) -> List[Dict]:
    """Convert rows from a purchase file into SupplierInvoice records."""
    records = []
    for i, row in enumerate(rows):
        mapped = _apply_mapping(row, mapping)
        amount = safe_float(mapped.get("total_amount"))
        if amount == 0:
            continue

        rec = {
            "file_id": file_id,
            "row_number": i,
            "record_type": "SupplierInvoice",
            "date": safe_str(mapped.get("date")) or _today(),
            "amount": amount,
            "normalized_data": {
                "supplier_id":      safe_str(mapped.get("supplier_id")),
                "supplier_name":    safe_str(mapped.get("supplier_name")),
                "invoice_number":   safe_str(mapped.get("invoice_number")),
                "po_number":        safe_str(mapped.get("po_number")),
                "sku_id":           safe_str(mapped.get("sku_id")),
                "quantity":         safe_float(mapped.get("quantity")),
                "unit_price":       safe_float(mapped.get("unit_price")),
                "total_amount":     amount,
                "vat_amount":       safe_float(mapped.get("vat_amount")),
                "payment_status":   safe_str(mapped.get("payment_status")),
            },
        }
        records.append(rec)
    return records


def extract_inventory_records(
    rows: List[Dict], mapping: Dict[str, str], file_id: int
) -> List[Dict]:
    """Convert rows from an inventory file into InventoryMovement records."""
    records = []
    for i, row in enumerate(rows):
        mapped = _apply_mapping(row, mapping)
        qty_in = safe_float(mapped.get("quantity_in"))
        qty_out = safe_float(mapped.get("quantity_out"))
        waste = safe_float(mapped.get("quantity_waste"))

        if qty_in == 0 and qty_out == 0 and waste == 0:
            continue

        net_amount = (qty_in - qty_out - waste) * safe_float(mapped.get("unit_cost"), 1.0)

        rec = {
            "file_id": file_id,
            "row_number": i,
            "record_type": "InventoryMovement",
            "date": safe_str(mapped.get("date")) or _today(),
            "amount": abs(net_amount),
            "normalized_data": {
                "sku_id":           safe_str(mapped.get("sku_id")),
                "product_name":     safe_str(mapped.get("product_name")),
                "movement_type":    safe_str(mapped.get("movement_type")),
                "quantity_in":      qty_in,
                "quantity_out":     qty_out,
                "quantity_waste":   waste,
                "unit_cost":        safe_float(mapped.get("unit_cost")),
                "beginning_stock":  safe_float(mapped.get("beginning_stock")),
                "ending_stock":     safe_float(mapped.get("ending_stock")),
                "warehouse":        safe_str(mapped.get("warehouse")),
            },
        }
        records.append(rec)
    return records


def extract_coa_records(
    rows: List[Dict], mapping: Dict[str, str], file_id: int
) -> List[Dict]:
    """Convert rows from a chart-of-accounts file."""
    records = []
    for i, row in enumerate(rows):
        mapped = _apply_mapping(row, mapping)
        code = safe_str(mapped.get("account_code"))
        name = safe_str(mapped.get("account_name"))
        if not code and not name:
            continue

        rec = {
            "file_id": file_id,
            "row_number": i,
            "record_type": "ChartOfAccount",
            "date": _today(),
            "amount": 0.0,
            "normalized_data": {
                "account_code":   code,
                "account_name":   name,
                "account_type":   safe_str(mapped.get("account_type")),
                "statement_type": safe_str(mapped.get("statement_type")),
                "normal_balance": safe_str(mapped.get("normal_balance")),
            },
        }
        records.append(rec)
    return records


def extract_records(
    file_type: str, rows: List[Dict], approved_mappings: List[Dict], file_id: int
) -> List[Dict]:
    """Dispatch to the correct extractor based on file type."""
    mapping = {m["raw_column"]: m["standard_field"] for m in approved_mappings}
    if file_type == "sales":
        return extract_sales_records(rows, mapping, file_id)
    elif file_type == "purchase":
        return extract_purchase_records(rows, mapping, file_id)
    elif file_type == "inventory":
        return extract_inventory_records(rows, mapping, file_id)
    elif file_type == "coa":
        return extract_coa_records(rows, mapping, file_id)
    return []


def _apply_mapping(row: Dict, mapping: Dict[str, str]) -> Dict:
    """Apply column mapping to a raw row -> standard field dict."""
    result = {}
    for raw_col, val in row.items():
        std_field = mapping.get(raw_col)
        if std_field and std_field != "unknown":
            result[std_field] = val
    return result


def _today() -> str:
    return datetime.today().strftime("%Y-%m-%d")
