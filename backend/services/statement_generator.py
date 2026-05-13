"""Generate financial statements from journal lines with evidence links."""
from typing import List, Dict, Tuple
from collections import defaultdict

# Account classification for Balance Sheet derivation
_BS_ASSET_PREFIXES = ("1",)          # 1xxx = Asset accounts
_BS_LIABILITY_PREFIXES = ("2",)      # 2xxx = Liability accounts
_IS_PREFIXES = ("4", "5")            # 4xxx revenue, 5xxx expenses → close to equity


def generate_trial_balance(journal_entries: List[Dict]) -> List[Dict]:
    """
    Aggregate journal lines into trial balance by account.
    Returns list of {account_code, account_name, debit, credit, net}
    """
    balances: Dict[str, Dict] = {}

    for entry in journal_entries:
        for line in entry.get("lines", []):
            code = line["account_code"]
            if code not in balances:
                balances[code] = {
                    "account_code": code,
                    "account_name": line["account_name"],
                    "total_debit": 0.0,
                    "total_credit": 0.0,
                    "entry_count": 0,
                }
            balances[code]["total_debit"] += line.get("debit", 0)
            balances[code]["total_credit"] += line.get("credit", 0)
            balances[code]["entry_count"] += 1

    result = []
    for code, bal in sorted(balances.items()):
        net = bal["total_debit"] - bal["total_credit"]
        result.append({
            "account_code": code,
            "account_name": bal["account_name"],
            "total_debit": round(bal["total_debit"], 2),
            "total_credit": round(bal["total_credit"], 2),
            "net_balance": round(net, 2),
            "entry_count": bal["entry_count"],
        })

    return result


def generate_income_statement(
    journal_entries: List[Dict],
    period_label: str,
    record_index: Dict[int, Dict] = None,
) -> Dict:
    """
    Generate Income Statement from journal lines.
    Returns structured IS with evidence.
    """
    revenue = 0.0
    cogs = 0.0
    operating_expenses = 0.0
    waste = 0.0

    revenue_evidence = []
    cogs_evidence = []

    REVENUE_ACCOUNTS = {"4000"}
    COGS_ACCOUNTS = {"5000"}
    EXPENSE_ACCOUNTS = {"5100"}
    WASTE_ACCOUNTS = {"5200"}

    for entry in journal_entries:
        src_id = entry.get("source_record_id")
        for line in entry.get("lines", []):
            code = line["account_code"]
            credit = line.get("credit", 0)
            debit = line.get("debit", 0)

            if code in REVENUE_ACCOUNTS:
                revenue += credit
                if src_id:
                    revenue_evidence.append(src_id)
            elif code in COGS_ACCOUNTS:
                cogs += debit
                if src_id:
                    cogs_evidence.append(src_id)
            elif code in EXPENSE_ACCOUNTS:
                operating_expenses += debit
            elif code in WASTE_ACCOUNTS:
                waste += debit

    gross_profit = revenue - cogs
    total_expenses = operating_expenses + waste
    net_profit = gross_profit - total_expenses
    gross_margin = (gross_profit / revenue * 100) if revenue > 0 else 0

    lines = [
        _stmt_line("Revenue",            revenue,            "4000", "revenue",           len(set(revenue_evidence))),
        _stmt_line("Cost of Goods Sold", cogs,               "5000", "cogs",              len(set(cogs_evidence))),
        _stmt_line("Gross Profit",        gross_profit,       "",     "gross_profit",       0),
        _stmt_line("Operating Expenses",  operating_expenses, "5100", "expense",            0),
        _stmt_line("Waste & Shrinkage",   waste,              "5200", "expense",            0),
        _stmt_line("Net Profit",          net_profit,         "",     "net_profit",         0),
    ]

    return {
        "period_label": period_label,
        "statement_type": "income_statement",
        "summary": {
            "revenue": round(revenue, 2),
            "cogs": round(cogs, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_margin_pct": round(gross_margin, 1),
            "operating_expenses": round(operating_expenses, 2),
            "waste": round(waste, 2),
            "net_profit": round(net_profit, 2),
        },
        "lines": lines,
        "evidence_record_ids": list(set(revenue_evidence + cogs_evidence)),
    }


def _stmt_line(name, amount, account_code, line_type, evidence_count) -> Dict:
    return {
        "line_name": name,
        "amount": round(amount, 2),
        "account_code": account_code,
        "line_type": line_type,
        "evidence_count": evidence_count,
    }


def generate_exception_report(
    validations: List[Dict],
    importance_scores: List[Dict],
) -> Dict:
    """Summarize exceptions and high-risk items."""
    critical = [v for v in validations if v.get("severity") == "critical"]
    warnings = [v for v in validations if v.get("status") == "warning"]
    passed = [v for v in validations if v.get("status") == "passed"]

    high_risk = [s for s in importance_scores if s.get("level") in ("Critical", "High")]

    return {
        "total_validations": len(validations),
        "passed": len(passed),
        "warnings": len(warnings),
        "critical": len(critical),
        "high_risk_records": len(high_risk),
        "critical_issues": [
            {"type": v["validation_type"], "message": v["message"],
             "record_id": v.get("business_record_id")}
            for v in critical[:20]
        ],
        "warning_iss