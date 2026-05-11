"""Deterministic validation rules for business records."""
from typing import List, Dict, Any


def validate_records(
    records: List[Dict], file_type: str, period_id: int
) -> List[Dict]:
    """
    Run validation checks against all business records.
    Returns list of ValidationResult dicts.
    """
    results = []
    validators = {
        "sales": _validate_sales,
        "purchase": _validate_purchase,
        "inventory": _validate_inventory,
        "coa": _validate_coa,
    }
    fn = validators.get(file_type)
    if not fn:
        return results

    for rec in records:
        results.extend(fn(rec, period_id))

    # Cross-record checks
    if file_type == "sales":
        results.extend(_check_duplicate_sales(records, period_id))
    elif file_type == "purchase":
        results.extend(_check_duplicate_invoices(records, period_id))
    elif file_type == "inventory":
        results.extend(_check_negative_stock(records, period_id))

    return results


def _validate_sales(rec: Dict, period_id: int) -> List[Dict]:
    issues = []
    nd = rec.get("normalized_data", {})
    rec_id = rec.get("id")

    if not nd.get("branch_id"):
        issues.append(_result(period_id, rec_id, "missing_branch", "warning",
                              "warning", "Sales record missing branch_id"))
    if not nd.get("sku_id"):
        issues.append(_result(period_id, rec_id, "missing_sku", "warning",
                              "warning", "Sales record missing SKU/product code"))
    if nd.get("sales_amount", 0) <= 0:
        issues.append(_result(period_id, rec_id, "zero_sales", "failed",
                              "critical", "Sales amount is zero or negative"))
    if nd.get("cost_amount", 0) > nd.get("sales_amount", 0) and nd.get("sales_amount", 0) > 0:
        issues.append(_result(period_id, rec_id, "cost_exceeds_sales", "warning",
                              "warning", "Cost amount exceeds sales amount (negative margin)"))
    if nd.get("discount", 0) > nd.get("sales_amount", 0) * 0.5:
        issues.append(_result(period_id, rec_id, "abnormal_discount", "warning",
                              "warning", "Discount exceeds 50% of sales amount"))
    if not issues:
        issues.append(_result(period_id, rec_id, "sales_basic_check", "passed",
                              "info", "Basic sales validation passed"))
    return issues


def _validate_purchase(rec: Dict, period_id: int) -> List[Dict]:
    issues = []
    nd = rec.get("normalized_data", {})
    rec_id = rec.get("id")

    if not nd.get("supplier_id") and not nd.get("supplier_name"):
        issues.append(_result(period_id, rec_id, "missing_supplier", "warning",
                              "warning", "Purchase record missing supplier"))
    if not nd.get("invoice_number"):
        issues.append(_result(period_id, rec_id, "missing_invoice_no", "warning",
                              "warning", "Purchase record missing invoice number"))
    if nd.get("total_amount", 0) <= 0:
        issues.append(_result(period_id, rec_id, "zero_purchase", "failed",
                              "critical", "Purchase amount is zero or negative"))
    if not nd.get("po_number"):
        issues.append(_result(period_id, rec_id, "missing_po", "warning",
                              "info", "Purchase has no matching PO number"))
    if not issues:
        issues.append(_result(period_id, rec_id, "purchase_basic_check", "passed",
                              "info", "Basic purchase validation passed"))
    return issues


def _validate_inventory(rec: Dict, period_id: int) -> List[Dict]:
    issues = []
    nd = rec.get("normalized_data", {})
    rec_id = rec.get("id")

    if not nd.get("sku_id"):
        issues.append(_result(period_id, rec_id, "missing_sku", "warning",
                              "warning", "Inventory record missing SKU"))
    ending = nd.get("ending_stock", 0)
    if ending < 0:
        issues.append(_result(period_id, rec_id, "negative_stock", "failed",
                              "critical", f"Negative ending stock: {ending}"))
    waste_pct = 0
    qty_out = nd.get("quantity_out", 0)
    if qty_out > 0:
        waste_pct = nd.get("quantity_waste", 0) / qty_out * 100
    if waste_pct > 20:
        issues.append(_result(period_id, rec_id, "high_waste", "warning",
                              "warning", f"Waste rate {waste_pct:.1f}% exceeds 20%"))
    if not issues:
        issues.append(_result(period_id, rec_id, "inventory_basic_check", "passed",
                              "info", "Basic inventory validation passed"))
    return issues


def _validate_coa(rec: Dict, period_id: int) -> List[Dict]:
    issues = []
    nd = rec.get("normalized_data", {})
    rec_id = rec.get("id")

    if not nd.get("account_code"):
        issues.append(_result(period_id, rec_id, "missing_account_code", "warning",
                              "warning", "Account missing code"))
    if not nd.get("account_name"):
        issues.append(_result(period_id, rec_id, "missing_account_name", "warning",
                              "warning", "Account missing name"))
    valid_types = {"asset", "liability", "equity", "revenue", "expense",
                   "สินทรัพย์", "หนี้สิน", "ส่วนของผู้ถือหุ้น", "รายได้", "ค่าใช้จ่าย"}
    atype = str(nd.get("account_type") or "").lower()
    if atype and atype not in valid_types:
        issues.append(_result(period_id, rec_id, "unknown_account_type", "warning",
                              "info", f"Unknown account type: {atype}"))
    if not issues:
        issues.append(_result(period_id, rec_id, "coa_basic_check", "passed",
                              "info", "COA validation passed"))
    return issues


def _check_duplicate_sales(records: List[Dict], period_id: int) -> List[Dict]:
    seen = {}
    issues = []
    for rec in records:
        nd = rec.get("normalized_data", {})
        key = (nd.get("date"), nd.get("branch_id"), nd.get("sku_id"),
               nd.get("sales_amount"))
        if key in seen:
            issues.append(_result(period_id, rec.get("id"), "duplicate_sales",
                                  "warning", "warning",
                                  f"Possible duplicate sales row (date/branch/sku/amount match)"))
        seen[key] = True
    return issues


def _check_duplicate_invoices(records: List[Dict], period_id: int) -> List[Dict]:
    seen = {}
    issues = []
    for rec in records:
        nd = rec.get("normalized_data", {})
        inv_no = nd.get("invoice_number")
        if not inv_no:
            continue
        if inv_no in seen:
            issues.append(_result(period_id, rec.get("id"), "duplicate_invoice",
                                  "failed", "critical",
                                  f"Duplicate invoice number: {inv_no}"))
        seen[inv_no] = True
    return issues


def _check_negative_stock(records: List[Dict], period_id: int) -> List[Dict]:
    """Running stock check per SKU."""
    stock: Dict[str, float] = {}
    issues = []
    for rec in records:
        nd = rec.get("normalized_data", {})
        sku = nd.get("sku_id") or "unknown"
        begin = nd.get("beginning_stock", 0)
        if sku not in stock:
            stock[sku] = begin
        stock[sku] += nd.get("quantity_in", 0)
        stock[sku] -= nd.get("quantity_out", 0)
        stock[sku] -= nd.get("quantity_waste", 0)
        if stock[sku] < 0:
            issues.append(_result(period_id, rec.get("id"), "running_negative_stock",
                                  "failed", "critical",
                                  f"SKU {sku} running stock went negative: {stock[sku]:.1f}"))
    return issues


def _result(period_id, rec_id, vtype, status, severity, message) -> Dict:
    return {
        "period_id": period_id,
        "business_record_id": rec_id,
        "validation_type": vtype,
        "status": status,
        "severity": severity,
        "message": message,
    }


def summarize_validations(results: List[Dict]) -> Dict:
    """Return counts of passed/warning/failed/critical."""
    counts = {"passed": 0, "warning": 0, "failed": 0, "critical": 0}
    for r in results:
        s = r.get("status", "")
        if s in counts:
            counts[s] += 1
        if r.get("severity") == "critical":
            counts["critical"] += 1
    return counts


# ── Tax Agent checks ──────────────────────────────────────────────────────────

def validate_tax_records(records: List[Dict], period_id: int) -> List[Dict]:
    """
    Cross-record tax checks (called by Tax Agent).
    Checks: missing VAT, zero-tax on taxable lines, abnormal VAT rate.
    """
    results = []
    VAT_RATE = 0.07
    TOLERANCE = 0.02  # 2% tolerance on VAT rate

    for rec in records:
        nd = rec.get("normalized_data", {})
        rec_id = rec.get("id")
        total = nd.get("total_amount") or nd.get("sales_amount") or 0
        tax   = nd.get("tax_amount") or 0

        if total <= 0:
            continue

        # No tax column present at all
        if "tax_amount" not in nd:
            results.append(_result(period_id, rec_id, "missing_tax_column",
                                   "warning", "warning",
                                   "Record has no tax_amount column — VAT not trackable"))
            continue

        # Zero tax on non-zero amount
        if tax == 0 and total > 0:
            results.append(_result(period_id, rec_id, "zero_tax",
                                   "warning", "warning",
                                   f"Zero tax on taxable amount {total} — check VAT exemption"))
            continue

        # Check VAT rate is ~7%
        implied_rate = tax / (total - tax) if (total - tax) > 0 else 0
        if abs(implied_rate - VAT_RATE) > TOLERANCE:
            results.append(_result(period_id, rec_id, "abnormal_vat_rate",
                                   "warning", "warning",
                                   f"Implied VAT rate {implied_rate*100:.1f}% differs from 7%"))
        else:
            results.append(_result(period_id, rec_id, "tax_ok",
                                   "passed", "info",
                                   f"VAT rate {implied_rate*100:.1f}% — OK"))
    return results


def validate_debit_credit_balance(entries: List[Dict]) -> Dict:
    """
    Verify total debits == total credits across all journal entries.
    Returns {balanced: bool, debit_total, credit_total, variance}.
    """
    total_dr = sum(
        line.get("debit", 0)
        for entry in entries
        for line in entry.get("lines", [])
    )
    total_cr = sum(
        line.get("credit", 0)
        for entry in entries
        for line in entry.get("lines", [])
    )
    variance = round(abs(total_dr - total_cr), 2)
    return {
        "balanced": variance < 0.01,
        "debit_total": round(total_dr, 2),
        "credit_total": round(total_cr, 2),
        "variance": variance,
    }
