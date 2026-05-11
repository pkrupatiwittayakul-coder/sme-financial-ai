"""Map raw/messy column names to standard schema fields."""
import re
from typing import Dict, List, Tuple
import anthropic
from backend.config import ANTHROPIC_API_KEY, LLM_MODEL

# Standard fields per file type with known aliases (Thai + English)
STANDARD_FIELD_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "sales": {
        "date":            ["วันที่", "date", "transaction_date", "sale_date", "วันขาย", "วันที"],
        "branch_id":       ["สาขา", "branch", "branch_id", "branch_code", "รหัสสาขา"],
        "sku_id":          ["รหัสสินค้า", "sku", "sku_id", "product_code", "item_code", "รหัส"],
        "product_name":    ["ชื่อสินค้า", "product_name", "item_name", "description", "สินค้า"],
        "quantity_sold":   ["จำนวนขาย", "qty", "quantity", "quantity_sold", "จำนวน", "qty_sold"],
        "sales_amount":    ["ยอดขาย", "sales", "revenue", "amount", "total", "sales_amount", "ยอด"],
        "cost_amount":     ["ต้นทุน", "cost", "cogs", "cost_amount", "ต้นทุนขาย"],
        "discount":        ["ส่วนลด", "discount", "disc"],
        "vat":             ["ภาษี", "vat", "tax", "vat_amount"],
        "customer_id":     ["ลูกค้า", "customer", "customer_id", "cust_id"],
        "payment_method":  ["วิธีชำระ", "payment_method", "payment_type", "cash_card"],
    },
    "purchase": {
        "date":            ["วันที่", "date", "invoice_date", "po_date"],
        "supplier_id":     ["ผู้ขาย", "supplier", "vendor", "supplier_id", "vendor_id", "ผู้จำหน่าย"],
        "supplier_name":   ["ชื่อผู้ขาย", "supplier_name", "vendor_name"],
        "invoice_number":  ["เลขใบแจ้งหนี้", "invoice_no", "invoice_number", "inv_no", "reference"],
        "po_number":       ["เลขใบสั่งซื้อ", "po_number", "po_no", "purchase_order"],
        "sku_id":          ["รหัสสินค้า", "sku", "item_code", "product_code"],
        "quantity":        ["จำนวน", "quantity", "qty"],
        "unit_price":      ["ราคาต่อหน่วย", "unit_price", "price", "rate"],
        "total_amount":    ["ยอดรวม", "total", "amount", "total_amount", "invoice_amount"],
        "vat_amount":      ["ภาษี", "vat", "tax", "vat_amount"],
        "payment_status":  ["สถานะ", "status", "payment_status", "paid"],
    },
    "inventory": {
        "date":            ["วันที่", "date", "movement_date"],
        "sku_id":          ["รหัสสินค้า", "sku", "item_code", "product_code", "รหัส"],
        "product_name":    ["ชื่อสินค้า", "product_name", "item_name", "description"],
        "movement_type":   ["ประเภท", "type", "movement_type", "transaction_type", "รับ/จ่าย"],
        "quantity_in":     ["รับเข้า", "qty_in", "quantity_in", "received"],
        "quantity_out":    ["จ่ายออก", "qty_out", "quantity_out", "issued", "sold"],
        "quantity_waste":  ["เสียหาย", "waste", "damaged", "scrap"],
        "unit_cost":       ["ต้นทุนต่อหน่วย", "unit_cost", "cost_per_unit"],
        "beginning_stock": ["สต็อกต้น", "beginning", "opening_stock", "begin_qty"],
        "ending_stock":    ["สต็อกปลาย", "ending", "closing_stock", "end_qty"],
        "warehouse":       ["คลัง", "warehouse", "location", "store"],
    },
    "coa": {
        "account_code":    ["รหัสบัญชี", "account_code", "code", "acc_code"],
        "account_name":    ["ชื่อบัญชี", "account_name", "name", "description"],
        "account_type":    ["ประเภท", "type", "account_type", "category"],
        "statement_type":  ["งบ", "statement", "statement_type", "report_type"],
        "normal_balance":  ["ยอดปกติ", "normal_balance", "debit_credit"],
    },
    "bank": {
        "date":            ["วันที่", "date", "transaction_date"],
        "description":     ["รายการ", "description", "detail", "narrative"],
        "debit":           ["เดบิต", "debit", "withdrawal", "charge"],
        "credit":          ["เครดิต", "credit", "deposit"],
        "balance":         ["ยอดคงเหลือ", "balance", "running_balance"],
        "reference":       ["อ้างอิง", "reference", "ref_no", "cheque_no"],
    },
}


def map_columns_rule_based(
    file_type: str, raw_columns: List[str]
) -> List[Dict]:
    """
    Fast rule-based column mapping using alias lists.
    Returns list of {raw_column, standard_field, confidence, source}.
    """
    aliases = STANDARD_FIELD_ALIASES.get(file_type, {})
    results = []

    for col in raw_columns:
        col_lower = col.lower().strip()
        best_field = None
        best_conf = 0.0

        for std_field, alias_list in aliases.items():
            for alias in alias_list:
                a_lower = alias.lower()
                if col_lower == a_lower:
                    score = 1.0
                elif col_lower in a_lower or a_lower in col_lower:
                    score = 0.8
                elif _fuzzy_match(col_lower, a_lower):
                    score = 0.6
                else:
                    continue

                if score > best_conf:
                    best_conf = score
                    best_field = std_field

        results.append({
            "raw_column": col,
            "standard_field": best_field or "unknown",
            "confidence": round(best_conf, 2),
            "source": "rule_based",
        })

    return results


def _fuzzy_match(a: str, b: str) -> bool:
    """Simple fuzzy: shared significant tokens."""
    tokens_a = set(re.split(r"[\s_\-/]+", a)) - {"", "the", "a", "an"}
    tokens_b = set(re.split(r"[\s_\-/]+", b)) - {"", "the", "a", "an"}
    return bool(tokens_a & tokens_b)


def map_columns_with_llm(
    file_type: str, raw_columns: List[str], sample_rows: List[Dict]
) -> List[Dict]:
    """
    Use Claude Haiku to suggest mappings for low-confidence/unknown columns.
    Only called when rule-based confidence < 0.6.
    """
    if not ANTHROPIC_API_KEY:
        return []

    std_fields = list(STANDARD_FIELD_ALIASES.get(file_type, {}).keys())
    sample_str = "\n".join(
        [str(row) for row in sample_rows[:3]]
    )

    prompt = f"""You are a financial data analyst mapping columns from a Thai SME {file_type} file to standard fields.

Standard fields available: {std_fields}

Raw column names: {raw_columns}

Sample data rows:
{sample_str}

For each raw column, suggest the best matching standard field (or "unknown" if no match).
Respond as JSON array: [{{"raw_column": "...", "standard_field": "...", "confidence": 0.0-1.0}}]
Only include columns that are not already clearly mapped. Be conservative with confidence scores."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        text = msg.content[0].text.strip()
        # Extract JSON from response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            mappings = json.loads(text[start:end])
            for m in mappings:
                m["source"] = "llm"
            return mappings
    except Exception:
        pass
    return []


def merge_mappings(rule_mappings: List[Dict], llm_mappings: List[Dict]) -> List[Dict]:
    """Merge rule-based and LLM mappings, preferring higher confidence."""
    llm_index = {m["raw_column"]: m for m in llm_mappings}
    final = []
    for rm in rule_mappings:
        lm = llm_index.get(rm["raw_column"])
        if lm and rm["confidence"] < 0.6 and lm.get("confidence", 0) > rm["confidence"]:
            final.append({**rm, **lm, "source": "llm"})
        else:
            final.append(rm)
    return final
