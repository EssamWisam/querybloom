#!/bin/bash
set -e

export BASE_PATH=/querybloom

# 1. Build frontend bundle on startup
cd /workspace/querybloom/webapp
npm run build

# 2. Start Vite in watch mode in the background to recompile whenever .svelte files change
npm run build -- --watch &

# 3. Start Uvicorn backend with auto-reload for Python files
cd /workspace/querybloom
exec uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
