#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$DIR/.." && pwd )"

echo "=== Starting QueryBloom Standalone ==="

# Check virtual environment
PYTHON_BIN="python3"
if [ -f "$DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$DIR/.venv/bin/python3"
    source "$DIR/.venv/bin/activate" 2>/dev/null || true
elif [ -f "$REPO_ROOT/.venv/bin/python3" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
    source "$REPO_ROOT/.venv/bin/activate" 2>/dev/null || true
elif [ -f "$REPO_ROOT/kg-voyager/.venv/bin/python3" ]; then
    PYTHON_BIN="$REPO_ROOT/kg-voyager/.venv/bin/python3"
    source "$REPO_ROOT/kg-voyager/.venv/bin/activate" 2>/dev/null || true
fi

export PYTHONPATH="$REPO_ROOT:$DIR:$PYTHONPATH"

# 1. Start backend server
echo "Starting QueryBloom Backend API on http://localhost:8000..."
"$PYTHON_BIN" -m querybloom.server &
BACKEND_PID=$!

cleanup() {
    echo ""
    echo "Shutting down servers..."
    kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 2. Start frontend dev server
echo "Starting QueryBloom Webapp on http://localhost:5173..."
cd "$DIR/webapp"
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

npm run dev

