#!/bin/bash
set -e

export BASE_PATH=/querybloom

# 1. Clean previous build and build fresh bundle on startup
cd /workspace/querybloom/webapp
rm -rf build .svelte-kit
npm run build

# 2. Start Uvicorn backend with reload
cd /workspace/querybloom
exec uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
