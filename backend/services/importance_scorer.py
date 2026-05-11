"""Score materiality, risk, and importance of business records."""
from typing import List, Dict


def score_record(rec: Dict, validations: List[Dict]) -> Dict:
    """
    Calculate importance score for a single business record.
    Returns {object_type, object_id, total_score, level, reason}
    """
    nd = rec.get("normalized_data", {})
    rtype = rec.get("record_type", "")
    rec_id = rec.get("id")
    amount = rec.get("amount", 0)
    reasons = []
    score = 0.0

    # --- Materiality (0-40 pts) ---
    if amount > 1_000_000:
        score += 40; reasons.append("Very large amount (>1M)")
    elif amount > 100_000:
        score += 25; reasons.append("Large amount (>100K)")
    elif amount > 10_000:
        score += 10; reasons.append("Medium amount (>10K)")
    else:
        score += 2

    # --- Exception score from validations (0-30 pts) ---
    rec_validations = [v for v in validations if v.get("business_record_id") == rec_id]
    for v in rec_validations:
        if v["severity"] == "critical":
            score += 15; reasons.append(f"Critical: {v['message'][:50]}")
        elif v["status"] == "warning":
            score += 5; reasons.append(f"Warning: {v['message'][:50]}")

    # --- Missing field risk (0-20 pts) ---
    if rtype == "SalesTransaction":
        if not nd.get("branch_id"): score += 10; reasons.append("Missing branch")
        if not nd.get("sku_id"):    score += 5;  reasons.append("Missing SKU")
        if not nd.get("cost_amount"): score += 5; reasons.append("No COGS data")
    elif rtype == "SupplierInvoice":
        if not nd.get("invoice_number"): score += 10; reasons.append("No invoice number")
        if not nd.get("po_number"):      score += 5;  reasons.append("No PO match")
        if not nd.get("supplier_id"):    score += 5;  reasons.append("Missing supplier")
    elif rtype == "InventoryMovement":
        if nd.get("ending_stock", 0) < 0: score += 15; reasons.append("Negative stock")
        if not nd.get("sku_id"):          score += 5;  reasons.append("Missing SKU")

    score = min(score, 100.0)
    level = _score_to_level(score)

    return {
        "object_type": rtype,
        "object_id": rec_id,
        "total_score": round(score, 1),
        "level": level,
        "reason": "; ".join(reasons) if reasons else "Standard record",
    }


def _score_to_level(score: float) -> str:
    if score >= 75:  return "Critical"
    if score >= 50:  return "High"
    if score >= 25:  return "Medium"
    return "Low"


def score_all_records(
    records: List[Dict], validations: List[Dict]
) -> List[Dict]:
    return [score_record(r, validations) for r in records]
