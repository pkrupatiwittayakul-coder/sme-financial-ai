"""Map validated business events to double-entry journal entries (IFRS-aligned)."""
from typing import List, Dict, Optional

VAT_RATE = 0.07   # Thailand standard VAT

# Default chart of accounts — extended per PDF spec
DEFAULT_ACCOUNTS = {
    # Assets
    "1100": {"name": "Cash & Bank",            "type": "Asset",     "statement": "BS"},
    "1200": {"name": "Accounts Receivable",    "type": "Asset",     "statement": "BS"},
    "1300": {"name": "Inventory",              "type": "Asset",     "statement": "BS"},
    "1400": {"name": "VAT Input Tax",          "type": "Asset",     "statement": "BS"},
    "1500": {"name": "Prepaid Expenses",       "type": "Asset",     "statement": "BS"},
    # Liabilities
    "2100": {"name": "Accounts Payable",       "type": "Liability", "statement": "BS"},
    "2200": {"name": "VAT Payable",            "type": "Liability", "statement": "BS"},
    "2300": {"name": "WHT Payable",            "type": "Liability", "statement": "BS"},
    "2400": {"name": "Accrued Expenses",       "type": "Liability", "statement": "BS"},
    # Equity
    "3000": {"name": "Retained Earnings",      "type": "Equity",    "statement": "BS"},
    # Revenue
    "4000": {"name": "Sales Revenue — Retail", "type": "Revenue",   "statement": "IS"},
    "4100": {"name": "Sales Revenue — Wholesale","type": "Revenue", "statement": "IS"},
    "4900": {"name": "Other Income",           "type": "Revenue",   "statement": "IS"},
    # COGS
    "5000": {"name": "Cost of Goods Sold",     "type": "Expense",   "statement": "IS"},
    "5100": {"name": "Waste & Shrinkage",      "type": "Expense",   "statement": "IS"},
    # Operating Expenses
    "6100": {"name": "Selling Expenses",       "type": "Expense",   "statement": "IS"},
    "6200": {"name": "General & Admin",        "type": "Expense",   "statement": "IS"},
    "6300": {"name": "Depreciation",           "type": "Expense",   "statement": "IS"},
    # Other
    "7100": {"name": "Interest Expense",       "type": "Expense",   "statement": "IS"},
    "7200": {"name": "Income Tax Expense",     "type": "Expense",   "statement": "IS"},
}


def map_record_to_journal(rec: Dict, period_id: int) -> Optional[Dict]:
    """
    Convert one BusinessRecord to a JournalEntry dict with JournalLines.
    All debit/credit logic is deterministic — NO LLM involvement.
    Returns None for records that produce no journal impact.
    """
    rtype = rec.get("record_type")
    nd = rec.get("normalized_data", {})
    amount = rec.get("amount", 0)
    if amount <= 0:
        return None

    entry = {
        "period_id": period_id,
        "source_record_id": rec.get("id"),
        "date": rec.get("date") or "",
        "description": "",
        "status": "posted",
        "lines": [],
    }

    if rtype == "SalesTransaction":
        sales = float(nd.get("sales_amount") or amount)
        cogs  = float(nd.get("cost_amount") or 0)
        tax   = float(nd.get("tax_amount") or 0)
        branch = nd.get("branch_id", "?")
        sku    = nd.get("sku_id", "?")

        entry["description"] = f"Sale: SKU {sku} @ Branch {branch}"

        # Revenue side — net of VAT
        net_sales = round(sales / (1 + VAT_RATE), 2) if tax == 0 and sales > 0 else sales
        vat_output = round(sales - net_sales, 2) if tax == 0 else tax

        entry["lines"] += [
            _line("1200", "Accounts Receivable",    debit=sales),
            _line("4000", "Sales Revenue — Retail", credit=net_sales),
            _line("2200", "VAT Payable",             credit=vat_output),
        ]
        # COGS side
        if cogs > 0:
            entry["lines"] += [
                _line("5000", "Cost of Goods Sold", debit=cogs),
                _line("1300", "Inventory",          credit=cogs),
            ]

    elif rtype == "SupplierInvoice":
        total   = float(nd.get("total_amount") or amount)
        tax_in  = float(nd.get("tax_amount") or round(total * VAT_RATE / (1 + VAT_RATE), 2))
        net     = round(total - tax_in, 2)
        inv_no  = nd.get("invoice_number", "?")
        sup     = nd.get("supplier_name", "?")

        entry["description"] = f"Purchase Invoice {inv_no} — {sup}"
        entry["lines"] += [
            _line("1300", "Inventory",         debit=net),
            _line("1400", "VAT Input Tax",     debit=tax_in),
            _line("2100", "Accounts Payable",  credit=total),
        ]

    elif rtype == "InventoryMovement":
        waste    = float(nd.get("quantity_waste") or 0)
        unit_cost = float(nd.get("unit_cost") or 0)
        if waste > 0 and unit_cost > 0:
            waste_val = round(waste * unit_cost, 2)
            entry["description"] = f"Inventory waste: SKU {nd.get('sku_id', '?')}"
            entry["lines"] += [
                _line("5100", "Waste & Shrinkage", debit=waste_val),
                _line("1300", "Inventory",         credit=waste_val),
            ]
        else:
            return None

    else:
        return None

    return entry if entry["lines"] else None


def _line(code: str, name: str, debit: float = 0.0, credit: float = 0.0) -> Dict:
    return {"account_code": code, "account_name": name,
            "debit": round(debit, 2), "credit": round(credit, 2)}


def map_all_records(records: List[Dict], period_id: int) -> List[Dict]:
    """Map all business records. Returns only mappable ones."""
    return [e for e in (map_record_to_journal(r, period_id) for r in records) if e]


def build_default_accounts(period_id: int) -> List[Dict]:
    return [
        {"period_id": period_id, "account_code": code,
         "account_name": info["name"], "account_type": info["type"],
         "statement_type": info["statement"]}
        for code, info in DEFAULT_ACCOUNTS.items()
    ]
