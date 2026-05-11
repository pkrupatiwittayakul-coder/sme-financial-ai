"""
SME Financial Intelligence System — Streamlit Frontend
Run:  streamlit run frontend/app.py
"""
import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json
import os

API_BASE = os.getenv("BACKEND_URL", "http://localhost:8000") + "/api"

st.set_page_config(
    page_title="SME Financial Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
.metric-card {
    background: #f0f2f6; border-radius: 8px; padding: 16px;
    text-align: center; margin: 4px;
}
.status-passed { color: #28a745; font-weight: bold; }
.status-warning { color: #ffc107; font-weight: bold; }
.status-failed { color: #dc3545; font-weight: bold; }
.status-critical { color: #dc3545; font-weight: bold; }
.chat-user { background: #e3f2fd; padding: 10px; border-radius: 8px; margin: 4px 0; }
.chat-ai { background: #f1f8e9; padding: 10px; border-radius: 8px; margin: 4px 0; }
</style>
""", unsafe_allow_html=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def api_get(path: str):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_post(path: str, json_data=None, files=None, data=None):
    try:
        r = requests.post(f"{API_BASE}{path}", json=json_data, files=files,
                          data=data, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        try:
            detail = r.json().get("detail", str(e))
        except Exception:
            detail = str(e)
        st.error(f"API error: {detail}")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def check_api():
    try:
        r = requests.get("http://localhost:8000/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/combo-chart.png", width=64)
    st.title("SME Financial AI")
    st.caption("v1.0 MVP")
    st.divider()

    # API health check
    if check_api():
        st.success("✅ Backend connected")
    else:
        st.error("❌ Backend offline\nRun: `uvicorn backend.main:app --reload`")

    st.divider()
    page = st.radio(
        "Navigation",
        ["🏢 Company Setup", "📤 Upload Files", "🗺️ Schema Mapping",
         "✅ Validation Dashboard", "📊 Financial Statements", "💬 Management Chat"],
        label_visibility="collapsed"
    )

    st.divider()
    # Company/Period selector (shared state)
    companies = api_get("/companies") or []
    if companies:
        company_options = {c["name"]: c["id"] for c in companies}
        selected_company = st.selectbox("Company", list(company_options.keys()))
        company_id = company_options[selected_company]

        periods = api_get(f"/companies/periods/{company_id}") or []
        if periods:
            period_options = {p["label"]: p["id"] for p in periods}
            selected_period = st.selectbox("Reporting Period", list(period_options.keys()))
            st.session_state["period_id"] = period_options[selected_period]
            st.session_state["period_label"] = selected_period
        else:
            st.info("No periods yet. Go to Company Setup.")
            st.session_state["period_id"] = None
    else:
        st.info("No companies yet. Go to Company Setup.")
        st.session_state["period_id"] = None
        st.session_state["period_label"] = ""


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1: Company Setup
# ═══════════════════════════════════════════════════════════════════════════════
if page == "🏢 Company Setup":
    st.title("🏢 Company & Period Setup")
    st.markdown("Define your company and reporting period before uploading data.")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Create Company")
        with st.form("new_company"):
            company_name = st.text_input("Company Name", placeholder="บริษัท ABC จำกัด")
            industry = st.selectbox("Industry", ["Retail", "Wholesale", "Manufacturing",
                                                  "Food & Beverage", "Construction", "Services"])
            currency = st.selectbox("Currency", ["THB", "USD", "EUR"])
            if st.form_submit_button("Create Company", type="primary"):
                result = api_post("/companies/", {"name": company_name, "industry": industry, "currency": currency})
                if result:
                    st.success(f"✅ Company created: {result['name']} (ID: {result['id']})")
                    st.rerun()

    with col2:
        st.subheader("Create Reporting Period")
        companies_list = api_get("/companies") or []
        if companies_list:
            with st.form("new_period"):
                cid_options = {c["name"]: c["id"] for c in companies_list}
                selected_co = st.selectbox("Company", list(cid_options.keys()))
                period_label = st.text_input("Period Label", placeholder="Jan 2026")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    start_date = st.date_input("Start Date")
                with col_d2:
                    end_date = st.date_input("End Date")
                if st.form_submit_button("Create Period", type="primary"):
                    result = api_post("/companies/periods", {
                        "company_id": cid_options[selected_co],
                        "label": period_label,
                        "start_date": str(start_date),
                        "end_date": str(end_date),
                    })
                    if result:
                        st.success(f"✅ Period created: {result['label']} (ID: {result['id']})")
                        st.rerun()
        else:
            st.info("Create a company first.")

    st.divider()
    st.subheader("Existing Companies & Periods")
    for co in (api_get("/companies") or []):
        with st.expander(f"🏢 {co['name']} ({co['industry']}) — {co['currency']}"):
            periods_list = api_get(f"/companies/periods/{co['id']}") or []
            if periods_list:
                df = pd.DataFrame(periods_list)
                st.dataframe(df[["id", "label", "start_date", "end_date", "status"]],
                             use_container_width=True, hide_index=True)
            else:
                st.caption("No periods yet.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2: Upload Files
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📤 Upload Files":
    st.title("📤 Upload SME Data Files")
    period_id = st.session_state.get("period_id")
    if not period_id:
        st.warning("⚠️ Select a company and reporting period in the sidebar first.")
        st.stop()

    st.info(f"Uploading to period: **{st.session_state.get('period_label')}** (ID: {period_id})")

    uploaded_files = st.file_uploader(
        "Upload Excel (.xlsx) or CSV files",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        help="Supported: Sales, Purchase, Inventory, Chart of Accounts files"
    )

    if uploaded_files:
        for uf in uploaded_files:
            with st.spinner(f"Processing {uf.name}..."):
                result = api_post(
                    "/upload/",
                    files={"file": (uf.name, uf.getvalue(), uf.type)},
                    data={"period_id": str(period_id)},
                )
            if result and "file_id" in result:
                conf = result.get("classification_confidence", 0)
                ft = result.get("file_type", "unknown")
                color = "🟢" if conf > 0.7 else ("🟡" if conf > 0.4 else "🔴")

                with st.expander(f"{color} **{uf.name}** → detected as `{ft}` (confidence: {conf:.0%})", expanded=True):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("File Type", ft.upper())
                    col2.metric("Rows", result.get("row_count", 0))
                    col3.metric("Confidence", f"{conf:.0%}")

                    if result.get("columns"):
                        st.caption(f"Columns: {', '.join(result['columns'])}")

                    if conf < 0.5:
                        st.warning("Low confidence classification. Please override below.")
                        new_type = st.selectbox(
                            "Override file type", ["sales", "purchase", "inventory", "coa", "bank"],
                            key=f"override_{result['file_id']}"
                        )
                        if st.button("Apply Override", key=f"btn_override_{result['file_id']}"):
                            process_map = {
                                "sales": "order_to_cash", "purchase": "procure_to_pay",
                                "inventory": "inventory_to_cogs", "coa": "record_to_report",
                                "bank": "bank_reconciliation"
                            }
                            api_post(f"/classify/{result['file_id']}", {
                                "file_type": new_type,
                                "business_process": process_map[new_type]
                            })
                            st.success("Override applied!")

                    # Auto-suggest schema mapping
                    if st.button(f"Auto-map columns →", key=f"map_{result['file_id']}"):
                        mapping_result = api_post(f"/schema/suggest/{result['file_id']}?use_llm=false")
                        if mapping_result:
                            st.success(f"Schema mapping suggested! Go to Schema Mapping page to review.")

    st.divider()
    st.subheader("Uploaded Files")
    files = api_get(f"/upload/files/{period_id}") or []
    if files:
        df = pd.DataFrame(files)
        st.dataframe(
            df[["id", "filename", "file_type", "classification_confidence", "row_count"]],
            use_container_width=True, hide_index=True
        )
    else:
        st.info("No files uploaded yet.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3: Schema Mapping
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🗺️ Schema Mapping":
    st.title("🗺️ Schema Mapping Review")
    st.markdown("Review and approve how your raw column names map to standard financial fields.")
    period_id = st.session_state.get("period_id")
    if not period_id:
        st.warning("⚠️ Select a period in the sidebar first.")
        st.stop()

    files = api_get(f"/upload/files/{period_id}") or []
    if not files:
        st.info("No files uploaded yet. Go to Upload Files first.")
        st.stop()

    for f in files:
        fid = f["id"]
        with st.expander(f"📄 **{f['filename']}** ({f['file_type'].upper()})", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col2:
                use_llm = st.checkbox("Use AI assist", key=f"llm_{fid}",
                                       help="Send low-confidence columns to Claude for mapping suggestion")
                if st.button("Suggest Mappings", key=f"suggest_{fid}", type="primary"):
                    with st.spinner("Analysing columns..."):
                        result = api_post(f"/schema/suggest/{fid}?use_llm={str(use_llm).lower()}")
                    if result:
                        st.session_state[f"mappings_{fid}"] = result.get("mappings", [])
                        st.session_state[f"samples_{fid}"] = result.get("sample_rows", [])
                        st.rerun()

            # Show sample data
            if f"samples_{fid}" in st.session_state:
                with col1:
                    st.caption("Sample rows from file:")
                    st.dataframe(pd.DataFrame(st.session_state[f"samples_{fid}"]),
                                 use_container_width=True, height=120, hide_index=True)

            # Get mappings (from session or DB)
            if f"mappings_{fid}" not in st.session_state:
                existing = api_get(f"/schema/mappings/{fid}") or []
                if existing:
                    st.session_state[f"mappings_{fid}"] = existing

            mappings = st.session_state.get(f"mappings_{fid}", [])

            if mappings:
                st.caption("Edit mappings below (change Standard Field or uncheck to reject):")

                STANDARD_FIELDS = {
                    "sales": ["date", "branch_id", "sku_id", "product_name", "quantity_sold",
                               "sales_amount", "cost_amount", "discount", "vat", "customer_id",
                               "payment_method", "unknown"],
                    "purchase": ["date", "supplier_id", "supplier_name", "invoice_number",
                                  "po_number", "sku_id", "quantity", "unit_price", "total_amount",
                                  "vat_amount", "payment_status", "unknown"],
                    "inventory": ["date", "sku_id", "product_name", "movement_type", "quantity_in",
                                   "quantity_out", "quantity_waste", "unit_cost", "beginning_stock",
                                   "ending_stock", "warehouse", "unknown"],
                    "coa": ["account_code", "account_name", "account_type", "statement_type",
                             "normal_balance", "unknown"],
                    "bank": ["date", "description", "debit", "credit", "balance", "reference", "unknown"],
                }
                std_fields = STANDARD_FIELDS.get(f["file_type"], ["unknown"])

                updated_mappings = []
                for i, m in enumerate(mappings):
                    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                    with c1:
                        st.text(m["raw_column"])
                    with c2:
                        curr_std = m.get("standard_field", "unknown")
                        if curr_std not in std_fields:
                            std_fields_extended = [curr_std] + std_fields
                        else:
                            std_fields_extended = std_fields
                        new_std = st.selectbox(
                            "→", std_fields_extended,
                            index=std_fields_extended.index(curr_std),
                            key=f"std_{fid}_{i}", label_visibility="collapsed"
                        )
                    with c3:
                        conf = m.get("confidence", 0)
                        color = "🟢" if conf >= 0.8 else ("🟡" if conf >= 0.5 else "🔴")
                        st.markdown(f"{color} {conf:.0%}")
                    with c4:
                        approved = st.checkbox("✓", value=True, key=f"app_{fid}_{i}",
                                                label_visibility="collapsed")
                    updated_mappings.append({
                        "raw_column": m["raw_column"],
                        "standard_field": new_std,
                        "confidence": m.get("confidence", 1.0),
                        "approved": approved,
                    })

                if st.button(f"✅ Confirm Mappings for {f['filename']}", key=f"confirm_{fid}", type="primary"):
                    result = api_post(f"/schema/confirm/{fid}", {"mappings": updated_mappings})
                    if result:
                        # Extract records
                        with st.spinner("Extracting business records..."):
                            ext = api_post(f"/records/extract/{fid}")
                        if ext:
                            st.success(f"✅ {ext['records_extracted']} business records extracted!")
                            st.session_state.pop(f"mappings_{fid}", None)
                        st.rerun()
            else:
                st.info("Click 'Suggest Mappings' to start.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4: Validation Dashboard
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "✅ Validation Dashboard":
    st.title("✅ Validation Dashboard")
    period_id = st.session_state.get("period_id")
    if not period_id:
        st.warning("⚠️ Select a period in the sidebar first.")
        st.stop()

    col_run, col_space = st.columns([2, 6])
    with col_run:
        if st.button("🔄 Run Full Validation & Scoring", type="primary"):
            with st.spinner("Processing all records..."):
                result = api_post(f"/records/process/{period_id}")
            if result and "validation_summary" in result:
                st.success("Pipeline complete!")
                st.session_state["val_result"] = result

    result = st.session_state.get("val_result")
    if result:
        vs = result.get("validation_summary", {})
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Records Processed", result.get("records_processed", 0))
        r2.metric("Journal Entries", result.get("journal_entries_created", 0))
        r3.metric("✅ Passed", vs.get("passed", 0))
        r4.metric("⚠️ Warnings", vs.get("warning", 0))
        r5.metric("❌ Critical", vs.get("critical", 0))

    st.divider()

    # Load validation results
    tabs = st.tabs(["⚠️ Critical Issues", "🟡 Warnings", "✅ Passed", "🏆 Risk Rankings"])

    with tabs[0]:
        critical = api_get(f"/records/validations/{period_id}?status=failed") or []
        if critical:
            df = pd.DataFrame(critical)
            st.dataframe(df[["id", "validation_type", "severity", "message", "record_id"]],
                         use_container_width=True, hide_index=True)
            # Pie chart
            if len(df) > 0:
                type_counts = df["validation_type"].value_counts().reset_index()
                type_counts.columns = ["type", "count"]
                fig = px.pie(type_counts, values="count", names="type",
                             title="Critical Issues by Type", color_discrete_sequence=px.colors.qualitative.Set3)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.success("No critical issues found! 🎉")

    with tabs[1]:
        warnings = api_get(f"/records/validations/{period_id}?status=warning") or []
        if warnings:
            df = pd.DataFrame(warnings)
            st.dataframe(df[["id", "validation_type", "severity", "message", "record_id"]],
                         use_container_width=True, hide_index=True)
        else:
            st.success("No warnings!")

    with tabs[2]:
        passed = api_get(f"/records/validations/{period_id}?status=passed") or []
        st.metric("Passed Checks", len(passed))
        if passed:
            df = pd.DataFrame(passed[:50])
            st.dataframe(df[["id", "validation_type", "message"]],
                         use_container_width=True, hide_index=True)

    with tabs[3]:
        records_list = api_get(f"/records/list/{period_id}") or []
        if records_list:
            df = pd.DataFrame(records_list)
            df_sorted = df.sort_values("amount", ascending=False).head(20)
            fig = px.bar(df_sorted, x="id", y="amount", color="record_type",
                         title="Top 20 Records by Amount",
                         labels={"id": "Record ID", "amount": "Amount (THB)"})
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_sorted[["id", "record_type", "date", "amount"]],
                         use_container_width=True, hide_index=True)
        else:
            st.info("No records yet.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5: Financial Statements
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📊 Financial Statements":
    st.title("📊 Financial Statements")
    period_id = st.session_state.get("period_id")
    period_label = st.session_state.get("period_label", "")
    if not period_id:
        st.warning("⚠️ Select a period in the sidebar first.")
        st.stop()

    col_gen, col_space = st.columns([2, 6])
    with col_gen:
        if st.button("📊 Generate Statements", type="primary"):
            with st.spinner("Generating financial statements..."):
                result = api_post(f"/statements/generate/{period_id}")
            if result:
                st.session_state["stmt_result"] = result
                st.success("Statements generated!")

    result = st.session_state.get("stmt_result")
    if not result:
        # Try loading from DB
        is_data = api_get(f"/statements/income/{period_id}")
        if is_data:
            lines = {l["line_type"]: l["amount"] for l in is_data.get("lines", [])}
            result = {
                "income_statement": {
                    "summary": {
                        "revenue": lines.get("revenue", 0),
                        "cogs": lines.get("cogs", 0),
                        "gross_profit": lines.get("gross_profit", 0),
                        "gross_margin_pct": (
                            lines.get("gross_profit", 0) / lines.get("revenue", 1) * 100
                            if lines.get("revenue", 0) > 0 else 0
                        ),
                        "operating_expenses": lines.get("expense", 0),
                        "net_profit": lines.get("net_profit", 0),
                    },
                    "lines": is_data.get("lines", []),
                }
            }

    if result:
        is_data = result.get("income_statement", {})
        summary = is_data.get("summary", {})

        # Summary metrics
        st.subheader(f"📈 Income Statement — {period_label}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue", f"฿{summary.get('revenue', 0):,.0f}")
        c2.metric("Gross Profit", f"฿{summary.get('gross_profit', 0):,.0f}",
                  f"{summary.get('gross_margin_pct', 0):.1f}% margin")
        c3.metric("Net Profit", f"฿{summary.get('net_profit', 0):,.0f}")
        c4.metric("COGS", f"฿{summary.get('cogs', 0):,.0f}")

        # Waterfall chart
        categories = ["Revenue", "COGS", "Gross Profit", "Operating\nExpenses", "Net Profit"]
        vals = [
            summary.get("revenue", 0),
            -summary.get("cogs", 0),
            summary.get("gross_profit", 0),
            -summary.get("operating_expenses", 0),
            summary.get("net_profit", 0),
        ]
        colors = ["#2196F3", "#F44336", "#4CAF50", "#FF9800", "#4CAF50" if summary.get("net_profit", 0) >= 0 else "#F44336"]

        fig = go.Figure(go.Bar(
            x=categories, y=[abs(v) for v in vals],
            marker_color=colors,
            text=[f"฿{v:,.0f}" for v in vals],
            textposition="outside"
        ))
        fig.update_layout(title="Income Statement Overview", yaxis_title="Amount (THB)",
                          plot_bgcolor="white", height=400)
        st.plotly_chart(fig, use_container_width=True)

        # Detailed lines table
        st.subheader("Detailed Statement Lines")
        lines = is_data.get("lines", [])
        if lines:
            df = pd.DataFrame(lines)
            df["amount"] = df["amount"].apply(lambda x: f"฿{x:,.2f}")
            st.dataframe(df[["line_name", "amount", "line_type", "evidence_count"]],
                         use_container_width=True, hide_index=True,
                         column_config={
                             "line_name": "Line Item",
                             "amount": "Amount",
                             "line_type": "Category",
                             "evidence_count": st.column_config.NumberColumn("Evidence Records", format="%d"),
                         })

        # Exception report
        if "exception_report" in result:
            ex = result["exception_report"]
            st.divider()
            st.subheader("⚠️ Exception Report")
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("Total Validations", ex.get("total_validations", 0))
            e2.metric("✅ Passed", ex.get("passed", 0))
            e3.metric("⚠️ Warnings", ex.get("warnings", 0))
            e4.metric("❌ Critical", ex.get("critical", 0))

            critical_issues = ex.get("critical_issues", [])
            if critical_issues:
                st.error("**Critical Issues Requiring Review:**")
                for issue in critical_issues[:5]:
                    st.markdown(f"- ❌ **{issue['type']}**: {issue['message']}")

        # Trial balance
        if "trial_balance" in result:
            st.divider()
            st.subheader("Trial Balance")
            tb = result["trial_balance"]
            if tb:
                df_tb = pd.DataFrame(tb)
                df_tb["total_debit"] = df_tb["total_debit"].apply(lambda x: f"฿{x:,.2f}")
                df_tb["total_credit"] = df_tb["total_credit"].apply(lambda x: f"฿{x:,.2f}")
                df_tb["net_balance"] = df_tb["net_balance"].apply(lambda x: f"฿{x:,.2f}")
                st.dataframe(
                    df_tb[["account_code", "account_name", "total_debit",
                            "total_credit", "net_balance", "entry_count"]],
                    use_container_width=True, hide_index=True
                )
    else:
        st.info("Click **Generate Statements** to create financial statements from your processed data.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6: Management Chat
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "💬 Management Chat":
    st.title("💬 Management Chat")
    st.markdown("Ask questions about your financial data. Answers are backed by your actual records.")
    period_id = st.session_state.get("period_id")
    period_label = st.session_state.get("period_label", "")
    if not period_id:
        st.warning("⚠️ Select a period in the sidebar first.")
        st.stop()

    if "chat_session_id" not in st.session_state:
        st.session_state["chat_session_id"] = None
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    st.caption(f"Talking about period: **{period_label}**")

    # Quick question suggestions
    st.markdown("**Quick questions:**")
    qcol1, qcol2, qcol3 = st.columns(3)
    suggested_q = None
    with qcol1:
        if st.button("Why did gross profit change?"):
            suggested_q = "Why did gross profit change? What were the main drivers?"
    with qcol2:
        if st.button("What are the biggest risks?"):
            suggested_q = "What are the biggest financial risks and data quality issues I should know about?"
    with qcol3:
        if st.button("Summarize this period"):
            suggested_q = "Give me a brief executive summary of this reporting period's financial performance."

    # Chat history display
    st.divider()
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state["chat_history"]:
            if msg["role"] == "user":
                st.markdown(f'<div class="chat-user">🧑 **You:** {msg["content"]}</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-ai">🤖 **AI Analyst:** {msg["content"]}</div>',
                            unsafe_allow_html=True)
                if msg.get("evidence"):
                    st.caption(f"Evidence based on: {', '.join(msg['evidence'])}")

    # Input
    st.divider()
    user_input = st.chat_input("Ask about your financials...")
    if suggested_q:
        user_input = suggested_q

    if user_input:
        st.session_state["chat_history"].append({"role": "user", "content": user_input})

        with st.spinner("Analysing your data..."):
            result = api_post("/chat/", {
                "period_id": period_id,
                "session_id": st.session_state.get("chat_session_id"),
                "message": user_input,
            })

        if result:
            st.session_state["chat_session_id"] = result.get("session_id")
            ai_msg = {
                "role": "assistant",
                "content": result.get("answer", ""),
                "evidence": result.get("evidence", []),
            }
            st.session_state["chat_history"].append(ai_msg)

        st.rerun()

    if st.session_state["chat_history"]:
        if st.button("🗑️ Clear conversation"):
            st.session_state["chat_history"] = []
            st.session_state["chat_session_id"]