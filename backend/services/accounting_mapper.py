"""Map validated business events to double-entry journal entries."""
from typing import List, Dict, Optional


# Default chart of accounts (used if no COA file uploaded)
DEFAULT_ACCOUNTS = {
    "1100": {"name": "Cash & Bank",      "type": "Asset",   "statement": "BS"},
    "1200": {"name": "Accounts Receivable","type": "Asset", "statement": "BS"},
    "1300": {"name": "Inventory",         "type": "Asset",  "statement": "BS"},
    "2100": {"name": "Accounts Payable",  "type": "Liability","statement": "BS"},
    "4000": {"name": "Sales Revenue",     "type": "Revenue","statement": "IS"},
    "5000": {"name": "Cost of Goods Sold","type": "Expense","statement": "IS"},
    "5100": {"name": "Operating Expenses","type": "Expense","statement": "IS"},
    "5200": {"name": "Waste & Shrinkage", "type": "Expense","statement": "IS"},
}


def map_record_to_journal(rec: Dict, period_id: int) -> Optional[Dict]:
    """
    Convert a BusinessRecord into a JournalEntry with JournalLines.
    Returns None if the record cannot be mapped.
    """
    rtype = rec.get("record_type")
    nd = rec.get("normalized_data", {})
    amount = rec.get("amount", 0)
    if amount <= 0:
        return None

    entry = {
        "period_id": period_id,
        "source_record_id": rec.get("id"),
        "date": rec.get("date"),
        "description": "",
        "status": "posted",
        "lines": [],
    }

    if rtype == "SalesTransaction":
        sales = nd.get("sales_amount", amount)
        cogs = nd.get("cost_amount", 0)

        entry["description"] = f"Sales: {nd.get('sku_id','?')} @ {nd.get('branch_id','?')}"
        # Dr Cash/AR  Cr Sales Revenue
        entry["lines"].append(_line("1100", "Cash & Bank", debit=sales))
        entry["lines"].append(_line("4000", "Sales Revenue", credit=sales))
        # Dr COGS  Cr Inventory
        if cogs > 0:
            entry["lines"].append(_line("5000", "Cost of Goods Sold", debit=cogs))
            entry["lines"].append(_line("1300", "Inventory", credit=cogs))

    elif rtype == "SupplierInvoice":
        total = nd.get("total_amount", amount)
        entry["description"] = f"Purchase invoice {nd.get('invoice_number','?')} - {nd.get('supplier_name','?')}"
        # Dr Inventory/Expense  Cr Accounts Payable
        entry["lines"].append(_line("1300", "Inventory", debit=total))
        entry["lines"].append(_line("2100", "Accounts Payable", credit=total))

    elif rtype == "InventoryMovement":
        waste = nd.get("quantity_waste", 0)
        unit_cost = nd.get("unit_cost", 0)
        if waste > 0 and unit_cost > 0:
            waste_val = waste * unit_cost
            entry["description"] = f"Inventory waste: {nd.get('sku_id','?')}"
            entry["lines"].append(_line("5200", "Waste & Shrinkage", debit=waste_val))
            entry["lines"].append(_line("1300", "Inventory", credit=waste_val))
        else:
            return None   # Pure movement records don't need journal entries

    else:
        return None

    return entry if entry["lines"] else None


def _line(code: str, name: str, debit: float = 0, credit: float = 0) -> Dict:
    return {
        "account_code": code,
        "account_name": name,
        "debit": round(debit, 2),
        "credit": round(credit, 2),
    }


def map_all_records(records: List[Dict], period_id: int) -> List[Dict]:
    """Map all business records to journal entries, skipping unmappable ones."""
    entries = []
    for rec in records:
        entry = map_record_to_journal(rec, period_id)
        if entry:
            entries.append(entry)
    return entries


def build_default_accounts(period_id: int) -> List[Dict]:
    """Return default chart of accounts for a period."""
    return [
        {
            "period_id": period_id,
            "account_code": code,
            "account_name": info["name"],
            "account_type": info["type"],
            "statement_type": info["statement"],
        }
        for code, info in DEFAULT_ACCOUNTS.items()
    ]
