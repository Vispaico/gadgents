#!/usr/bin/env bash
# One-command dev server for Gadgents:
#   ./dev.sh
# Starts the backend (uvicorn :8000) and frontend (vite :5173) together,
# streams both logs, and shuts them both down cleanly on Ctrl+C.
#
# Requires: the project venv at ./.venv and npm deps already installed
# (cd frontend && npm install). Firecrawl is optional — only needed if you
# tick "Use Firecrawl" in the Lead Finder (expects firecrawl-simple docker
# on http://localhost:3002).

set -euo pipefail
cd "$(dirname "$0")"

# Non-blocking check: is firecrawl reachable? Just informs the user.
if curl -s -o /dev/null -m 2 http://localhost:3002/health 2>/dev/null; then
  echo "✓ Firecrawl detected at http://localhost:3002 (Lead Finder Firecrawl mode available)"
else
  echo "ℹ Firecrawl not reachable at http://localhost:3002 — Lead Finder will use DuckDuckGo/HTTP mode. Start firecrawl-simple in Docker to enable deep mode."
fi

# Clean up both processes when this script exits (Ctrl+C included).
BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  echo ""
  echo "Shutting down dev servers…"
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Backend
# NOTE: do NOT use --reload here. The editorial pipeline runs as a background worker
# thread that can take many minutes; --reload restarts the worker on any file change
# (editor autosave, __pycache__ writes) and KILLS in-flight runs, leaving them orphaned
# ("Run was interrupted"). For code changes, restart dev.sh manually.
source .venv/bin/activate
echo "▶ Starting backend on http://localhost:8000"
uvicorn backend.app:app --port 8000 &
BACKEND_PID=$!

# Frontend
echo "▶ Starting frontend on http://localhost:5173"
( cd frontend && npm run dev ) &
FRONTEND_PID=$!

echo ""
echo "Both running. Open http://localhost:5173  (backend at http://localhost:8000/health)"
echo "Press Ctrl+C to stop both."
wait
