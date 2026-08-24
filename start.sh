#!/bin/bash
set -e

export BASE_PATH=/querybloom

# 1. Build frontend bundle if missing
cd /workspace/querybloom/webapp
if [ ! -d "build" ] || [ ! -f "build/index.html" ]; then
    echo "Frontend build missing or incomplete, compiling SvelteKit bundle..."
    npm run build
fi

# 2. Start Uvicorn backend with reload
cd /workspace/querybloom
export PYTHONPATH="/workspace/querybloom/src:/workspace:$PYTHONPATH"
exec uv run uvicorn querybloom.server:app --host 0.0.0.0 --port 8000 --reload
