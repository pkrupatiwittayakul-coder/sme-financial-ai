"""Classify uploaded files by business process type."""
import re
from typing import Dict, Tuple, List

# Keywords mapped to file types (Thai + English)
CLASSIFICATION_RULES = {
    "sales": {
        "column_keywords": [
            "ยอดขาย", "sales", "revenue", "sale", "ขาย", "รายได้",
            "จำนวนขาย", "qty_sold", "quantity_sold", "sales_amount",
            "pos", "branch_sales", "สาขา", "ลูกค้า", "customer",
        ],
        "filename_keywords": ["sales", "ขาย", "revenue", "pos", "sell"],
    },
    "purchase": {
        "column_keywords": [
            "ซื้อ", "purchase", "supplier", "vendor", "ผู้ขาย", "po",
            "invoice", "ใบสั่งซื้อ", "ค่าใช้จ่าย", "expense",
            "accounts_payable", "ap", "grn", "goods_receipt",
        ],
        "filename_keywords": ["purchase", "ซื้อ", "supplier", "vendor", "invoice", "po"],
    },
    "inventory": {
        "column_keywords": [
            "สินค้า", "sku", "stock", "inventory", "คลัง", "warehouse",
            "quantity", "จำนวน", "movement", "เคลื่อนไหว", "waste",
            "beginning", "ending", "รับ", "จ่าย", "ต้นทุน", "cogs",
        ],
        "filename_keywords": ["inventory", "stock", "สินค้า", "คลัง", "sku", "warehouse"],
    },
    "coa": {
        "column_keywords": [
            "account_code", "account_name", "รหัสบัญชี", "ชื่อบัญชี",
            "chart_of_accounts", "account_type", "ประเภทบัญชี",
            "debit", "credit", "เดบิต", "เครดิต",
        ],
        "filename_keywords": ["coa", "chart", "account", "บัญชี", "ledger"],
    },
    "bank": {
        "column_keywords": [
            "bank", "ธนาคาร", "statement", "balance", "deposit",
            "withdrawal", "transaction_date", "reference",
        ],
        "filename_keywords": ["bank", "ธนาคาร", "statement"],
    },
}


def classify_file(filename: str, columns: List[str]) -> Tuple[str, str, float]:
    """
    Rule-based file classification.
    Returns: (file_type, business_process, confidence 0-1)
    """
    scores: Dict[str, float] = {k: 0.0 for k in CLASSIFICATION_RULES}

    fname_lower = filename.lower()
    cols_lower = [c.lower() for c in columns]
    cols_str = " ".join(cols_lower)

    for file_type, rules in CLASSIFICATION_RULES.items():
        # Filename match
        for kw in rules["filename_keywords"]:
            if kw in fname_lower:
                scores[file_type] += 2.0

        # Column keyword match
        for kw in rules["column_keywords"]:
            kw_l = kw.lower()
            # Exact column name match
            if kw_l in cols_lower:
                scores[file_type] += 1.5
            # Substring match in any column
            elif kw_l in cols_str:
                scores[file_type] += 0.5

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score == 0:
        return "unknown", "unknown", 0.0

    # Normalize confidence
    total = sum(scores.values())
    confidence = round(best_score / total, 2) if total > 0 else 0.0
    confidence = min(confidence * 1.5, 1.0)   # boost for clear winners

    process_map = {
        "sales": "order_to_cash",
        "purchase": "procure_to_pay",
        "inventory": "inventory_to_cogs",
        "coa": "record_to_report",
        "bank": "bank_reconciliation",
        "unknown": "unknown",
    }

    return best_type, process_map.get(best_type, "unknown"), confidence
