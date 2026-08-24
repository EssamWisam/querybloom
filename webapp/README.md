# QueryBloom Standalone Web Application

This directory contains the standalone SvelteKit web application for **QueryBloom** (ABSTAT-driven knowledge graph sampling, pattern mining, and QA generation workbench).

## Architecture

- **Frontend**: SvelteKit single-page application (`ABSTAT/webapp/`)
- **Backend API**: FastAPI server (`ABSTAT/server.py` & `ABSTAT/api/router.py`) running on `http://localhost:8000/api/v1`
- **Sampling & Pipeline Engine**: `ABSTAT/` sampling services (`sampling_service.py`, `llm.py`, `subgraph_miner.py`)
- **Persistence & Auth**: Supabase integration via REST client and `.env` credentials in `ABSTAT/.env`.

## Getting Started

### 1. Launching Both Backend & Frontend

From the `ABSTAT/` folder:
```bash
./run_standalone.sh
```

### 2. Manual Launch

#### Backend:
```bash
cd /path/to/ABSTAT/..
python3 -m ABSTAT.server
# Runs FastAPI on http://localhost:8000
```

#### Frontend:
```bash
cd ABSTAT/webapp
npm install
npm run dev
# Runs dev server on http://localhost:5173 with API proxy to port 8000
```

### 3. Production Build

```bash
cd ABSTAT/webapp
npm run build
```
Build outputs to `build/` which can be statically served directly by FastAPI or any static file web server.
