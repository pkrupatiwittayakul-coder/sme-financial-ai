#!/bin/bash
# SME Financial Intelligence System — Startup Script
# Usage: bash start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 Starting SME Financial Intelligence System..."
echo ""

# Install dependencies if needed
echo "📦 Checking dependencies..."
pip install fastapi uvicorn sqlalchemy aiosqlite anthropic \
    pandas openpyxl python-multipart networkx python-dotenv \
    httpx pydantic requests plotly xlsxwriter --quiet 2>/dev/null || true

# Clear stale pycache
find backend -name "*.pyc" -delete 2>/dev/null || true
find backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Start backend
echo "🔧 Starting FastAPI backend on http://localhost:8000 ..."
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

sleep 3

# Health check
if curl -s http://localhost:8000/health | grep -q "ok"; then
    echo "✅ Backend running at http://localhost:8000"
    echo "📚 API docs at  http://localhost:8000/docs"
else
    echo "❌ Backend failed to start. Check logs above."
    exit 1
fi

echo ""
echo "✅ System ready!"
echo "   Backend:  http://localhost:8000"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop."
wait $BACKEND_PID
