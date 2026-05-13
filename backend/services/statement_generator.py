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
        "warning_issues": [
            {"type": v["validation_type"], "message": v["message"],
             "record_id": v.get("business_record_id")}
            for v in warnings[:20]
        ],
        "top_risk_records": sorted(high_risk, key=lambda x: -x["total_score"])[:10],
    }


# ──────────────────────────────────────────────────────────────────────────────
# BALANCE SHEET
# ──────────────────────────────────────────────────────────────────────────────

def generate_balance_sheet(
    journal_entries: List[Dict],
    period_label: str,
    net_profit: float = 0.0,
) -> Dict:
    """
    Derive a simplified Balance Sheet from journal lines.

    Assets  = accounts 1xxx with a net debit balance
    Liabilities = accounts 2xxx with a net credit balance
    Equity  = retained earnings (prior equity) + net profit for the period.
              We approximate retained earnings as Assets − Liabilities − Net Profit.
    """
    # Aggregate net balances per account
    balances: Dict[str, Dict] = {}
    for entry in journal_entries:
        for line in entry.get("lines", []):
            code = line["account_code"]
            if code not in balances:
                balances[code] = {
                    "account_code": code,
                    "account_name": line["account_name"],
                    "net": 0.0,
                }
            balances[code]["net"] += line.get("debit", 0) - line.get("credit", 0)

    assets: List[Dict] = []
    liabilities: List[Dict] = []

    for code, bal in sorted(balances.items()):
        net = round(bal["net"], 2)
        row = {"account_code": code, "account_name": bal["account_name"], "amount": abs(net)}
        if any(code.startswith(p) for p in _BS_ASSET_PREFIXES) and net > 0:
            assets.append(row)
        elif any(code.startswith(p) for p in _BS_LIABILITY_PREFIXES) and net < 0:
            liabilities.append(row)

    total_assets = round(sum(a["amount"] for a in assets), 2)
    total_liabilities = round(sum(l["amount"] for l in liabilities), 2)

    # Retained earnings = total assets − liabilities − current net profit
    retained_earnings = round(total_assets - total_liabilities - net_profit, 2)
    total_equity = round(retained_earnings + net_profit, 2)
    total_liab_equity = round(total_liabilities + total_equity, 2)

    return {
        "period_label": period_label,
        "statement_type": "balance_sheet",
        "assets": assets,
        "liabilities": liabilities,
        "equity": [
            {"account_name": "Retained Earnings (prior periods)", "amount": retained_earnings},
            {"account_name": f"Net Profit — {period_label}", "amount": round(net_profit, 2)},
        ],
        "totals": {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "total_liabilities_and_equity": total_liab_equity,
            "balanced": abs(total_assets - total_liab_equity) < 0.02,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# PDF EXPORT  (reportlab)
# ──────────────────────────────────────────────────────────────────────────────

def generate_pdf_report(
    statement_type: str,
    data: Dict,
    company_name: str,
    currency: str = "THB",
) -> bytes:
    """
    Render a financial statement as a PDF and return the raw bytes.
    statement_type: 'income_statement' | 'balance_sheet' | 'trial_balance'
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph,
            Spacer, HRFlowable,
        )
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER
        import io
    except ImportError:
        raise RuntimeError("reportlab is not installed. Add it to requirements.txt.")

    BRAND   = colors.HexColor("#5B4BFB")
    SPARK   = colors.HexColor("#FF7A59")
    MINT    = colors.HexColor("#10B981")
    ROSE    = colors.HexColor("#EF4444")
    INK     = colors.HexColor("#1B1730")
    INK2    = colors.HexColor("#3C3856")
    INK3    = colors.HexColor("#6C6884")
    CANVAS  = colors.HexColor("#FAFAF7")
    LINE    = colors.HexColor("#E9E6DE")

    styles = getSampleStyleSheet()
    title_style  = ParagraphStyle("title",  fontName="Helvetica-Bold", fontSize=18, textColor=INK,  spaceAfter=2)
    sub_style    = ParagraphStyle("sub",    fontName="Helvetica",      fontSize=10, textColor=INK3, spaceAfter=6)
    section_style= ParagraphStyle("sec",    fontName="Helvetica-Bold", fontSize=9,  textColor=BRAND, spaceBefore=10, spaceAfter=4)
    body_style   = ParagraphStyle("body",   fontName="Helvetica",      fontSize=9,  textColor=INK2)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm,
    )

    def fmt(n):
        sym = "฿" if currency == "THB" else ("$" if currency == "USD" else currency + " ")
        return f"{sym}{abs(n):,.2f}" if n >= 0 else f"({sym}{abs(n):,.2f})"

    elements = []

    # Header
    elements.append(Paragraph("Ledger Spark", ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=11, textColor=BRAND)))
    elements.append(Spacer(1, 4))
    title_map = {
        "income_statement": "Income Statement",
        "balance_sheet":    "Balance Sheet",
        "trial_balance":    "Trial Balance",
    }
    elements.append(Paragraph(title_map.get(statement_type, statement_type.replace("_", " ").title()), title_style))
    period_label = data.get("period_label", "")
    elements.append(Paragraph(f"{company_name} · {period_label} · {currency}", sub_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND, spaceAfter=10))

    col_w = [11*cm, 5*cm]
    hdr_style = TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, CANVAS]),
        ("GRID",       (0,0), (-1,-1), 0.3, LINE),
        ("ALIGN",      (1,0), (1,-1), "RIGHT"),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING",   (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0), (-1,-1), 5),
    ])

    if statement_type == "income_statement":
        lines = data.get("lines", [])
        rows = [["Line", "Amount"]]
        for l in lines:
            amt = l["amount"]
            color_flag = l["line_type"] in ("net_profit", "gross_profit")
            rows.append([l["line_name"], fmt(amt)])
        t = Table(rows, colWidths=col_w)
        t.setStyle(hdr_style)
        # Bold totals
        for i, l in enumerate(lines, 1):
            if l["line_type"] in ("gross_profit", "net_profit"):
                t.setStyle(TableStyle([("FONTNAME", (0,i), (-1,i), "Helvetica-Bold"), ("LINEABOVE", (0,i), (-1,i), 0.8, INK2)]))
        elements.append(t)

    elif statement_type == "balance_sheet":
        totals = data.get("totals", {})

        # Assets
        elements.append(Paragraph("ASSETS", section_style))
        rows = [["Account", "Amount"]]
        for a in data.get("assets", []):
            rows.append([a["account_name"], fmt(a["amount"])])
        rows.append(["Total Assets", fmt(totals.get("total_assets", 0))])
        t = Table(rows, colWidths=col_w)
        t.setStyle(hdr_style)
        t.setStyle(TableStyle([("FONTNAME", (0, len(rows)-1), (-1, len(rows)-1), "Helvetica-Bold"),
                                ("LINEABOVE", (0, len(rows)-1), (-1, len(rows)-1), 0.8, INK2)]))
        elements.append(t)
        elements.append(Spacer(1, 10))

        # Liabilities
        elements.append(Paragraph("LIABILITIES", section_style))
        rows2 = [["Account", "Amount"]]
        for l in data.get("liabilities", []):
            rows2.append([l["account_name"], fmt(l["amount"])])
        rows2.append(["Total Liabilities", fmt(totals.get("total_liabilities", 0))])
        t2 = Table(rows2, colWidths=col_w)
        t2.setStyle(hdr_style)
        t2.setStyle(TableStyle([("FONTNAME", (0, len(rows2)-1), (-1, len(rows2)-1), "Helvetica-Bold"),
                                 ("LINEABOVE", (0, len(rows2)-1), (-1, len(rows2)-1), 0.8, INK2)]))
        elements.append(t2)
        elements.append(Spacer(1, 10))

        # Equity
        elements.append(Paragraph("EQUITY", section_style))
        rows3 = [["Account", "Amount"]]
        for e in data.get("equity", []):
            rows3.append([e["account_name"], fmt(e["amount"])])
        rows3.append(["Total Equity", fmt(totals.get("total_equity", 0))])
        t3 = Table(rows3, colWidths=col_w)
        t3.setStyle(hdr_style)
        t3.setStyle(TableStyle([("FONTNAME", (0, len(rows3)-1), (-1, len(rows3)-1), "Helvetica-Bold"),
                                 ("LINEABOVE", (0, len(rows3)-1), (-1, len(rows3)-1), 0.8, INK2)]))
        elements.append(t3)
        elements.append(Spacer(1, 10))

        # Check balance
        elements.append(Paragraph(
            f"Total Liabilities & Equity: {fmt(totals.get('total_liabilities_and_equity', 0))} "
            + ("✓ Balanced" if totals.get("balanced") else "⚠ Out of balance"),
            ParagraphStyle("check", fontName="Helvetica-Bold", fontSize=10,
                           textColor=MINT if totals.get("balanced") else ROSE)
        ))

    elif statement_type == "trial_balance":
        rows = [["Code", "Account", "Debit", "Credit", "Net"]]
        for r in data:
            rows.append([
                r["account_code"], r["account_name"],
                fmt(r["total_debit"]), fmt(r["total_credit"]), fmt(r["net_balance"]),
            ])
        t = Table(rows, colWidths=[2*cm, 7.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), BRAND),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,-1), 8.5),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, CANVAS]),
            ("GRID",       (0,0), (-1,-1), 0.3, LINE),
            ("ALIGN",      (2,0), (-1,-1), "RIGHT"),
            ("LEFTPADDING",  (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING",   (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ]))
        elements.append(t)

    elements.append(Spacer(1, 16))
    elements.append(Paragraph(
        f"Generated by Ledger Spark AI · {period_label}",
        ParagraphStyle("footer", fontName="Helvetica", fontSize=8, textColor=INK3),
    ))

    doc.build(elements)
    return buf.getvalue()
