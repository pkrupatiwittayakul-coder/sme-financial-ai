#!/bin/bash
# End-to-end API smoke test
# Usage: bash test_api.sh
# Requires: backend running on localhost:8000

BASE="http://localhost:8000/api"
PASS=0; FAIL=0

check() {
    local label=$1; local result=$2; local expect=$3
    if echo "$result" | grep -q "$expect"; then
        echo "  ✅ $label"
        PASS=$((PASS+1))
    else
        echo "  ❌ $label — got: $result"
        FAIL=$((FAIL+1))
    fi
}

echo "=== SME Financial API Smoke Test ==="

# 1. Health
R=$(curl -s http://localhost:8000/health)
check "Health check" "$R" "ok"

# 2. Create company
R=$(curl -sL -X POST $BASE/companies/ -H "Content-Type: application/json" \
    -d '{"name":"Test Co","industry":"Retail","currency":"THB"}')
check "Create company" "$R" '"id"'
CID=$(echo $R | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)

# 3. List companies
R=$(curl -sL $BASE/companies/)
check "List companies" "$R" "Test Co"

# 4. Create period
R=$(curl -sL -X POST $BASE/companies/periods -H "Content-Type: application/json" \
    -d "{\"company_id\":$CID,\"label\":\"Jan 2026\",\"start_date\":\"2026-01-01\",\"end_date\":\"2026-01-31\"}")
check "Create period" "$R" '"id"'
PID=$(echo $R | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)

# 5. List periods
R=$(curl -sL $BASE/companies/periods/$CID)
check "List periods" "$R" "Jan 2026"

# 6. Upload file
cat > /tmp/_smoke_sales.csv << 'EOF'
date,customer,description,amount,tax
2026-01-05,Acme Co,Coffee 5kg,5000,350
2026-01-07,Beta Ltd,Tea 3kg,3000,210
EOF
R=$(curl -sL -X POST $BASE/upload/ -F "period_id=$PID" -F "file=@/tmp/_smoke_sales.csv")
check "Upload file" "$R" "file_id"
FID=$(echo $R | python3 -c "import sys,json; print(json.load(sys.stdin)['file_id'])" 2>/dev/null)

# 7. Confirm schema
R=$(curl -sL -X POST "$BASE/schema/confirm/$FID" -H "Content-Type: application/json" \
    -d '{"mappings":[{"raw_column":"date","standard_field":"date","approved":true},{"raw_column":"customer","standard_field":"customer_id","approved":true},{"raw_column":"description","standard_field":"product_name","approved":true},{"raw_column":"amount","standard_field":"sales_amount","approved":true},{"raw_column":"tax","standard_field":"vat","approved":true}]}')
check "Confirm schema" "$R" "confirmed"

# 8. Extract records
R=$(curl -sL -X POST "$BASE/records/extract/$FID")
check "Extract records" "$R" "records_extracted"

# 9. List records
R=$(curl -sL "$BASE/records/list/$PID")
check "List records" "$R" "SalesTransaction"

# 10. Process period
R=$(curl -sL -X POST "$BASE/records/process/$PID")
check "Process period" "$R" "journal_entries_created"

# 11. Validations
R=$(curl -sL "$BASE/records/validations/$PID")
check "Get validations" "$R" "validation_type"

# 12. Generate statements
R=$(curl -sL -X POST "$BASE/statements/generate/$PID")
check "Generate statements" "$R" "income_statement"

# 13. Get income statement
R=$(curl -sL "$BASE/statements/income/$PID")
check "Get income statement" "$R" "Revenue"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ $FAIL -eq 0 ] && echo "🎉 All tests passed!" || echo "⚠️  Some tests failed."
