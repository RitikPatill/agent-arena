#!/usr/bin/env bash
# Record an asciinema demo of the AgentArena CLI.
# Usage: bash scripts/record_demo.sh
# Requires: asciinema (brew install asciinema / pip install asciinema)

set -euo pipefail

# --- Prerequisites ---

if ! command -v asciinema &>/dev/null; then
    echo "Error: asciinema is not installed."
    echo "  macOS:  brew install asciinema"
    echo "  Linux:  pip install asciinema  OR  apt install asciinema"
    exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Error: ANTHROPIC_API_KEY is not set."
    echo "  export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

# --- Start API server in background ---

echo "Starting API server..."
uvicorn agent_arena.api:app --port 8000 --log-level warning &
API_PID=$!
trap "kill $API_PID 2>/dev/null || true" EXIT

sleep 2
echo "API server ready (PID $API_PID)."

# --- Write embedded demo commands to a temp file ---

TMPFILE=$(mktemp)
trap "rm -f $TMPFILE; kill $API_PID 2>/dev/null || true" EXIT

cat >"$TMPFILE" <<'DEMO_EOF'
#!/usr/bin/env bash
set -euo pipefail

echo "=== AgentArena CLI Demo ==="
echo ""

# Inspect the task suite
echo "$ arena tasks list examples/task_suites/customer_support.yaml"
arena tasks list examples/task_suites/customer_support.yaml
sleep 1

echo ""
echo "$ python examples/quickstart.py --tasks 3"
python examples/quickstart.py --tasks 3
sleep 2

echo ""
echo "Done — open http://localhost:8501 for the full dashboard experience."
DEMO_EOF

chmod +x "$TMPFILE"

# --- Record ---

echo "Recording demo to docs/demo.asc ..."
asciinema rec docs/demo.asc \
    --title "AgentArena demo" \
    --command "bash $TMPFILE"

echo ""
echo "Recording saved to docs/demo.asc"
echo ""
echo "# Dashboard screenshots:"
echo "#   1. Start the dashboard:  uvicorn agent_arena.api:app --reload & arena dashboard"
echo "#   2. Navigate to the Arena page and run a demo."
echo "#   3. Capture the leaderboard:  Cmd+Shift+4 (macOS) → save as docs/screenshot.png"
echo "#   4. Click a score cell → Trace Viewer opens → capture as docs/trace.png"
echo ""
# agg docs/demo.asc docs/demo.gif   # uncomment if agg (asciinema Rust renderer) is installed
