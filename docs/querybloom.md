# QueryBloom — Developer Onboarding Guide

QueryBloom is the web-based ontology explorer and benchmark-generation tool built on top of
**GRASP** (Generic Reasoning and SPARQL Generation across Knowledge Graphs).
It runs a two-phase pipeline entirely in the browser:

1. **Sampling phase** — Points at any SPARQL endpoint, runs ABSTAT pattern extraction, and mines representative subgraph patterns from the knowledge graph.
2. **QA generation phase** — Feeds each mined subgraph to a multi-agent LLM pipeline that generates, executes, complexity-augments, verifies, and rewords NL question / SPARQL query pairs — producing a ready-to-use benchmark dataset.

The output QA pairs serve as few-shot examples for the GRASP NL→SPARQL translation pipeline.

---

## Repository layout

```
querybloom/
├── .env                                # Local Supabase credentials
├── server.py                           # Standalone FastAPI server (CORS + Static SPA serving)
├── run_standalone.sh                   # One-command launcher for backend + frontend
├── api/                                # Standalone API package
│   ├── __init__.py
│   ├── models.py                       # Pydantic request/response schemas
│   ├── supabase.py                     # Standalone Supabase REST/Auth client
│   └── router.py                       # Full /api/v1 router (auth, runs, events, SSE streaming)
├── executor/                           # Standalone SPARQL query executor (mirrors kg_voyager.executor)
│   ├── __init__.py
│   ├── sparql_executor.py
│   └── sparql_executor_utils.py
├── abstat_2.py                         # ABSTAT v2: queries SPARQL endpoint, extracts patterns
├── subgraph_miner.py                   # SubgraphMiner: preprocess() + mine()
├── sampling_service.py                 # run_sampling() orchestrator
├── llm.py                              # Multi-agent QA generation pipeline
├── events.py                           # PipelineEvent + EventSink
├── graph_serialization.py              # Cytoscape graph serializers
└── webapp/                             # Standalone SvelteKit Frontend
    ├── package.json
    ├── svelte.config.js
    ├── vite.config.js
    └── src/
        ├── routes/+page.svelte         # QueryBloom Workbench UI
        └── lib/abstat/                 # Frontend components & API client
```
            │                          skip-to-subgraphs button)
            ├── PropertiesPanel.svelte  Live property discovery list
            ├── GraphSubgraphs.svelte   Mined subgraph viewer
            ├── RunLauncher.svelte   Config form + start/cancel buttons
            ├── RunTimeline.svelte   Historical run list
            ├── QaPanel.svelte       QA generation launcher (triggers LLM pipeline,
            │                          streams progress, shows generated pairs)
            └── AuthPanel.svelte     Login / signup
```

---

## How a sampling run works end-to-end

```
User fills RunLauncher form → startSampling() in +page.svelte
  │
  └─► POST /api/v1/abstat/sample/stream  (SSE, chunked transfer)
        │
        ├── router.py creates run record in Supabase DB
        ├── creates threading.Event  stop_event  (set when client disconnects)
        ├── creates threading.Event  skip_event  (set by /skip-discovery endpoint)
        ├── stores skip_event in  _active_skip_events[run_id]
        └── runs worker thread: run_sampling(config, event_sink, stop_event, skip_event)
              │
              ├── [stage: "preprocess"]
              │     miner.preprocess(…, skip_event=skip_event)
              │       └── abstat_2.process_properties()
              │             - sequential mode: for p in properties → break if skip_event set
              │             - BFS/seed mode:   while … → break if skip_event set
              │             - emits: property.started, property.completed, graph.updated,
              │                      properties.discovered, cache.loaded
              │
              ├── stop_event checked here → cancel if set
              │
              └── [stage: "mining"]
                    miner.mine(…, stop_event=stop_event)
                  emits: subgraph.discovered, subgraph.samples

SSE frames → handleStreamFrame() in +page.svelte dispatches on event type:
  run.created        → activeRun set
  stage.started      → discoveryPhase = true/false, tab state
  property.completed → properties[] updated
  graph.updated      → graph reactive variable (triggers AbstatGraph re-render)
  subgraph.discovered → subgraphs[] updated
  result / done      → run finished
```

---

## How a QA generation run works end-to-end

After subgraphs are mined, the user triggers a second run from **QaPanel**:

```
User fills QaPanel form (model, max_subgraphs, verify_iterations) → submit()
  │
  └─► POST /api/v1/abstat/llm/stream  (SSE, chunked transfer)
        │
        └── router.py calls process_subgraphs_data() in a worker thread
              │
              ├── Loads mined subgraphs from the sampling run (via sample_run_id)
              ├── Spins up ThreadPoolExecutor (max_workers, default 10)
              └── For each subgraph in parallel → process_single_subgraph_pipeline()
                    │
                    ├── 1. GENERATOR AGENT
                    │     LLM call (structured output: SubgraphGenerationResult)
                    │     Decides if subgraph is meaningful; generates NL + SPARQL pairs
                    │     Template: ABSTAT/generate.jinja
                    │
                    ├── 2. SPARQL EXECUTOR
                    │     Each generated SPARQL query is executed against the live endpoint
                    │     execution_results: {success, count, error_message, result_preview}
                    │
                    ├── 3. COMPLEXITY INTRODUCER AGENT  (if introduce_complexity_step=True)
                    │     LLM call (structured output: ComplexityIntroducerResult)
                    │     Rewrites each pair with one non-trivial construct:
                    │     FILTER, OPTIONAL, UNION, ORDER_BY_LIMIT, EXISTS, SUBQUERY,
                    │     PROPERTY_PATH — re-executes the augmented queries
                    │     Template: ABSTAT/complexity.jinja
                    │
                    ├── 4. VERIFIER AGENT  (if verify_iterations > 0)
                    │     LLM call (structured output: VerificationResult)
                    │     Reviews pairs with execution results; marks correct / needs_fix
                    │     Picks most_meaningful_index; applies fixes and re-executes
                    │     Up to verify_iterations cycles
                    │     Template: ABSTAT/verify.jinja
                    │
                    └── 5. REWORD AGENT  (if reword_questions_step=True)
                          LLM call (structured output: RewordResult)
                          Audits NL questions for KG URI leakage / jargon
                          Rewrites only the question text of correct pairs
                          Template: ABSTAT/reword.jinja

SSE frames → QaPanel addFrame():
  run.started         → batch started
  subgraph.started    → per-subgraph work begins
  stage.started/completed (llm.generate, sparql.execute, llm.complexity,
                           llm.verify, llm.reword)
  subgraph.completed  → full result including qa_pairs[] available
  run.completed       → all subgraphs done
```

---

## SSE event catalogue

### Sampling events

| Event type | Stage | Key payload fields |
|---|---|---|
| `run.created` | — | `run` |
| `stage.started` | `preprocess` / `mining` / `abstat.preprocess` | `stage`, config fields |
| `stage.completed` | same | `num_patterns`, `num_attribute_patterns` |
| `properties.list` | `abstat.properties` | `count`, `properties[]`, `truncated` |
| `properties.filtered` | `abstat.properties` | `count` |
| `property.started` | `abstat.property` | `uri`, `label`, `short_name` |
| `property.completed` | `abstat.property` | `uri`, `added_object_patterns`, `added_attribute_patterns`, `total_object_patterns` |
| `properties.discovered` | `abstat.properties` | `discovered_type_count` |
| `graph.updated` | `ontology` | `graph` (Cytoscape JSON), `num_patterns`, `source_property` |
| `cache.loaded` | `abstat.properties` / `abstat.patterns` | `path`, `count` / `num_object_patterns` |
| `subgraph.discovered` | `mining` | `index`, `subgraph`, `graph`, `support` |
| `subgraph.samples` | `mining` | `index`, `samples[]` |
| `result` | — | `run`, `result` (SamplingRunResult) |
| `error` | — | `run_id`, `error` |
| `done` | — | `run_id` |

### QA generation events

| Event type | Stage | Key payload fields |
|---|---|---|
| `run.started` | `llm.batch` | `num_subgraphs`, `model`, `label` |
| `subgraph.started` | `llm.subgraph` | `subgraph_index` |
| `prompt.ready` | `llm.prompt` | `subgraph_index`, `pattern` |
| `stage.started/completed` | `llm.generate` | `subgraph_index`, `model`, `is_meaningful`, `num_questions`, `questions[]` |
| `stage.started/completed` | `sparql.execute` | `subgraph_index`, `qa_index`, `question`, `sparql_query`, `execution_results` |
| `stage.started/completed` | `llm.complexity` | `subgraph_index`, `num_pairs`, `augmentations[]` |
| `stage.started/completed` | `llm.verify` | `subgraph_index`, `iteration`, `verification` |
| `stage.started/completed` | `llm.reword` | `subgraph_index`, `num_pairs`, `pairs[]` |
| `subgraph.completed` | `llm.subgraph` / `llm.batch` | `subgraph_index`, `result` (full qa_pairs[]) |
| `run.completed` | `llm.batch` | `output_path`, `num_subgraphs` |
| `error` | `llm.batch` | `subgraph_index`, `error` |

---

## Key data models (Python / `sampling_service.py`)

```python
SamplingRunConfig
  endpoint: str              # SPARQL endpoint URL
  min_support: int           # minimum pattern occurrence count
  preprocess: SamplingPreprocessConfig
    property_limit: int      # max properties to process (or BFS limit with seed)
    max_triples: int         # triples sampled per property
    seed_property: str|None  # if set → BFS dynamic discovery from this property
    minimize_patterns: bool  # paper-style instance-level type minimisation
    rand_offset: bool        # randomise triple OFFSET (good for large KGs)
    use_cache / persist_cache: bool
    exclude_properties / exclude_classes / include_classes: list[str]|None
  mine: SamplingMineConfig
    k: int|tuple|dict        # subgraph size distribution  e.g. {3:0.7, 4:0.2, 5:0.1}
    num_subgraphs: int        # target number of subgraphs to mine
    m: int                   # max patterns per subgraph
    strategy: str            # "rand" (default) | others
    prob_optional / num_attrs / max_attr_len / verif_timeout …
```

---

## Multi-agent QA pipeline (`ABSTAT/llm.py`)

Each mined subgraph goes through up to five agents sequentially (agents run in
parallel across subgraphs via `ThreadPoolExecutor`). All agents use **litellm** with
`response_format` structured output so every response is parsed into a Pydantic model.

### Agent 1 — Generator (`SubgraphGenerationResult`)
Prompt: `generate.jinja` — receives the subgraph YAML (with a random subsample of
representative entities via `subsample_subgraph_entities()`) and produces:
- `is_meaningful: bool` — gate; meaningless subgraphs are skipped
- `questions: list[QuestionQueryPair]` — each has `text_query` + `sparql_query`

### Agent 2 — SPARQL Executor (not an LLM)
Each generated query is fired against the live SPARQL endpoint.
`execute_sparql_and_get_result()` returns `{success, count, error_message, result_preview}`.
Results are attached to the pair so downstream agents see whether the query actually works.

### Agent 3 — Complexity Introducer (`ComplexityIntroducerResult`)
Prompt: `complexity.jinja` — optional, enabled by `introduce_complexity_step=True`.
For each pair augments the SPARQL with exactly one non-trivial construct:
`FILTER | OPTIONAL | UNION | ORDER_BY_LIMIT | EXISTS | SUBQUERY | PROPERTY_PATH`
`skipped=True` means the pair can't be meaningfully augmented. Augmented queries are
re-executed to confirm they still return results.

### Agent 4 — Verifier (`VerificationResult`)
Prompt: `verify.jinja` — optional, enabled by `verify_iterations > 0`.
Receives the subgraph pattern + all pairs with their execution results. Returns:
- `pairs[]: VerificationPairResult` — `status: correct | needs_fix`, `reason`,
  optional `fixed_text_query` / `fixed_sparql_query`
- `all_correct: bool`
- `most_meaningful_index: int` (1-based)
Runs for up to `verify_iterations` cycles; fixes are applied and queries re-executed
between cycles until all pairs pass or the limit is reached.

### Agent 5 — Reword Agent (`RewordResult`)
Prompt: `reword.jinja` — optional, enabled by `reword_questions_step=True`.
Audits NL questions only (not SPARQL) for KG URI leakage, technical jargon, and
phrasing that a human user wouldn't naturally write. Rewrites the question text of
any flagged pair; SPARQL stays unchanged.

### LLM run config (`LLMRunRequest`)
```python
LLMRunRequest
  sample_run_id: str|None      # link to prior sampling run; loads its subgraphs
  endpoint: str                # SPARQL endpoint for query execution
  model: str                   # litellm model string, e.g. "gpt-5", "gpt-4o-mini"
  max_subgraphs: int|None      # random subsample of mined subgraphs
  verify_iterations: int       # 0 = no verification
  introduce_complexity_step: bool   # default True
  reword_questions_step: bool       # default True
  focus_entity_qa: bool        # generate entity-centric questions
  ents_ratio: float            # fraction of sample entities shown to LLM (default 0.4)
  max_workers: int             # parallel workers (default 10)
  timeout: int                 # SPARQL query timeout per call (seconds, default 70)
```

---

## Frontend state (`+page.svelte`)

| Variable | Type | Purpose |
|---|---|---|
| `running` | bool | whether a sampling SSE stream is active |
| `discoveryPhase` | bool | true while stage=preprocess is active; drives skip button visibility |
| `activeRun` | object | current sampling run record from DB |
| `graph` | object | Cytoscape JSON + `latestProperty` for green highlight |
| `lastNumPatterns` | number | guards against re-rendering graph when count is unchanged |
| `properties` | array | per-property status objects for PropertiesPanel |
| `propertySummary` | object | aggregate counts + cache status |
| `subgraphs` | array | mined subgraphs for GraphSubgraphs |
| `selectedSubgraphIndex` | number | which subgraph is highlighted |
| `sampleAbortController` | AbortController | `.abort()` cancels the SSE fetch → sets stop_event server-side |

QA generation state lives entirely inside `QaPanel.svelte`:
- `streamLlm()` opens its own SSE connection to `POST /api/v1/abstat/llm/stream`
- `QaPanel` accumulates `subgraph.completed` events to show generated pairs in the UI
- `QaPanel` is passed `token`, `endpoint`, and `sampleRunId` from the parent page

---

## AbstatGraph.svelte — rendering notes

- Uses **Cytoscape.js ^3.33.1** + **cytoscape-cola** layout.
- Positions are saved to `savedPositions` Map on each layout stop and restored on re-renders — nodes don't jump around when new edges are added.
- `isFirstRender` (savedPositions.size === 0) — only fits the viewport on the very first render; subsequent renders preserve the current pan/zoom.
- `applyFreshHighlight()` — adds CSS class `fresh` (green) to the most recently added property's edges and their endpoint nodes. Skipped when a subgraph is selected (`selectedIndex !== null`).
- Re-render is skipped entirely when `graph.updated` arrives but `num_patterns` has not changed (guards against noisy re-renders during attribute-only updates).

---

## Skip-to-subgraphs feature

Allows interrupting property discovery early and proceeding straight to mining
with whatever patterns have been collected so far.

**How it works:**
1. Each run gets a `threading.Event skip_event` stored in `_active_skip_events[run_id]` in `router.py`.
2. `POST /api/v1/abstat/sample/{run_id}/skip-discovery` sets `skip_event`.
3. The event is threaded through `run_sampling → miner.preprocess → abstat_2.process_properties`.
4. Both the sequential `for` loop and the BFS `while` loop in `process_properties` check `skip_event.is_set()` at the top of each iteration and `break` early.
5. Mining continues normally with the patterns already collected.
6. Frontend: `discoveryPhase` state tracks whether the preprocess stage is active. The **"Skip to subgraphs →"** button in `PatternsPanel` is visible only while `running && discoveryPhase`.
7. The `skip_event` is cleaned up from `_active_skip_events` in the worker's `finally` block.

---

## Running locally

### Backend (FastAPI)
```bash
# from repo root
conda activate grasp
pip install -e .
python -m kg_voyager.server serve configs/run.yaml
# or with hot-reload:
GRASP_RELOAD=true python -m kg_voyager.server serve configs/run.yaml
```
Runs on **port 6789** by default.

### Frontend (SvelteKit dev server)
```bash
cd website
npm install
npm run dev           # default port 5173
# or
npm run dev -- --port 5174
```
The Vite dev server proxies `/api/v1/*` to `localhost:6789` automatically
(configured in `website/vite.config.js`).

### Docker (full stack)
```bash
cp .env.example .env   # fill in API keys
docker compose up      # website on :80, backend on :6789
```
For production use `docker-compose.prod.yml`.

---

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | yes (for LLM features) | |
| `GEMINI_API_KEY` | optional | |
| `OPENROUTER_API_KEY` | optional | |
| `SUPABASE_URL` | yes (for persistence) | |
| `SUPABASE_ANON_KEY` | yes (for persistence) | |
| `GRASP_RELOAD` | dev only | enables FastAPI hot-reload |
| `DOCKER_ENDPOINT_MAP` | Docker only | remaps SPARQL endpoint URLs inside container |

---

## Supabase persistence

The API stores runs, events, subgraphs, and artifacts in Supabase (Postgres).
Auth uses Supabase JWT tokens — the frontend stores the session in `localStorage`
under the key `grasp:abstat-session` and sends `Authorization: Bearer <token>` on
every API request. The `require_user` FastAPI dependency validates the token.

Without Supabase configured the SSE stream still works but results won't be persisted
(errors are swallowed by `_best_effort` helpers in `router.py`).

---

## Adding a new SSE event type

1. Call `emit_event(event_sink, "your.event", "stage_name", "message", {…data…})` anywhere in the Python pipeline.
2. In `handleStreamFrame()` in `+page.svelte`, add a branch: `if (event === "your.event") { … }`.
3. The `data` object in the handler corresponds to the full `PipelineEvent.to_dict()` payload; actual event data is in `data.data` (or the `payload` alias already computed at the top of the function).

---

## Notebooks

`ABSTAT/*.ipynb` notebooks (`ABSTAT_2.ipynb`, `sampler.ipynb`, `llm.ipynb`, etc.)
call `abstat.process_properties()` and `SubgraphMiner` directly without going through
the API. All new keyword arguments added to those functions have `= None` defaults so
existing notebook calls are never broken.
