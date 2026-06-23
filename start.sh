#!/bin/bash
# Unity Roster - start both servers (API + static page)
cd "$(dirname "$0")"

echo "Starting Unity Roster..."
echo "  API:  http://127.0.0.1:8000"
echo "  Page: http://127.0.0.1:5500/roster.html"
echo ""
echo "Press Ctrl+C to stop both."

# API server (reads .env for GEMINI_API_KEY via main.py)
python3 -m uvicorn roster.main:app --port 8000 --app-dir src &
API_PID=$!

# Static server for the frontend
( cd web && python3 -m http.server 5500 ) &
WEB_PID=$!

# Stop both on Ctrl+C
trap "echo; echo 'Stopping...'; kill $API_PID $WEB_PID 2>/dev/null; exit 0" INT
wait
