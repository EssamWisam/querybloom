# ABSTAT API and Supabase Schema

This document describes the DB-backed API layer for a Svelte application. The legacy GRASP routes (`/run`, `/live`, `/save`, `/load`, `/abstat/*`, `/knowledge_graphs`, and `/config`) remain available. The formal app surface is versioned under `/api/v1`.

## Environment

Required for Supabase-backed endpoints:

- `SUPABASE_URL`: Supabase project URL, for example `https://project-ref.supabase.co`.
- `SUPABASE_ANON_KEY`: Supabase anon/public API key.

Optional:

- `GRASP_ARTIFACT_ROOT`: if set, compatibility file paths used by ABSTAT LLM jobs must stay under this directory.

The backend can start without Supabase variables. `GET /api/v1/health` reports whether Supabase is configured and whether the expected database tables are reachable. Supabase-dependent endpoints return `503` until the variables are set.

## Database Design

The migration lives in `supabase/migrations/202604250001_grasp_app_schema.sql`.

All user-owned tables carry `owner_id uuid references auth.users(id)`. API calls use the user's Supabase access token against PostgREST, so row-level security enforces ownership in the database.

Table summaries:

- `profiles`: one row per `auth.users` user. A trigger creates or updates the profile from Supabase Auth metadata.
- `projects`: groups runs and UI workspaces. Contains a user-controlled `settings` JSON object.
- `runs`: canonical job records for ABSTAT sampling, ABSTAT LLM generation, chat, and SPARQL workflows. Stores status, config, result summary, and error text.
- `run_events`: append-only-ish progress events for replaying a run timeline in the Svelte app.
- `artifacts`: metadata for YAML, JSON, graph, subgraph, QA, log, or other artifacts. Small payloads can be stored in `payload`; larger files should move to Supabase Storage and use `storage_bucket` plus `storage_path`.
- `subgraphs`: queryable mined subgraphs with support, type counts, Cytoscape-style graph payloads, and raw subgraph JSON.
- `qa_pairs`: generated natural-language/SPARQL pairs, execution results, verification status, and metadata.
- `saved_states`: DB-backed replacement or extension point for share-state JSON. Public states are readable by share ID; private states are owner-only.

## Auth Flow for Svelte

1. Sign up with `POST /api/v1/auth/signup` using `{ "email": "...", "password": "...", "display_name": "..." }`.
2. Log in with `POST /api/v1/auth/login` using `{ "email": "...", "password": "..." }`.
3. Store the returned Supabase `access_token` in the Svelte app.
4. Send protected requests with `Authorization: Bearer <access_token>`.
5. Use `GET /api/v1/auth/me` to refresh current user information.
6. Use `POST /api/v1/auth/logout` to revoke the token on Supabase.

The backend validates tokens by calling Supabase Auth (`/auth/v1/user`). It does not decode JWTs locally.

## Endpoints

Health:

- `GET /api/v1/health`

Auth:

- `POST /api/v1/auth/signup`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Projects:

- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `DELETE /api/v1/projects/{project_id}`

Runs:

- `GET /api/v1/runs?project_id=...&kind=...&limit=50`
- `POST /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `PATCH /api/v1/runs/{run_id}`
- `DELETE /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/events`
- `POST /api/v1/runs/{run_id}/events`
- `GET /api/v1/runs/{run_id}/artifacts`
- `POST /api/v1/runs/{run_id}/artifacts`
- `GET /api/v1/runs/{run_id}/subgraphs`
- `POST /api/v1/runs/{run_id}/subgraphs`
- `GET /api/v1/runs/{run_id}/qa-pairs`
- `POST /api/v1/runs/{run_id}/qa-pairs`

ABSTAT:

- `GET /api/v1/abstat/defaults`
- `POST /api/v1/abstat/sample`
- `POST /api/v1/abstat/sample/stream`
- `POST /api/v1/abstat/llm`
- `POST /api/v1/abstat/llm/stream`

`POST /api/v1/abstat/sample` creates a `runs` row, executes the existing sampling service, writes progress events best-effort, stores discovered subgraphs and graph artifacts, updates the run status, and returns `{ "run": ..., "result": ... }`.

`POST /api/v1/abstat/llm` creates a `runs` row, executes the existing YAML-based LLM pipeline, writes progress events best-effort, stores the output path as an artifact, updates the run status, and returns `{ "run": ..., "output_path": "..." }`.

## Streaming Contract

The formal API exposes POST-based Server-Sent Event streams for browser `fetch()` streaming. These endpoints use the same request bodies as their blocking counterparts and require the same `Authorization: Bearer <access_token>` header.

- `POST /api/v1/abstat/sample/stream`: streams property and pattern discovery, ontology graph updates, subgraph formation, artifact updates, and the final run result.
- `POST /api/v1/abstat/llm/stream`: streams prompt formation, text-query generation, SPARQL execution, complexity/verification/rewording stages, per-subgraph completion, artifact updates, and the final run result.

Each stream frame is SSE-formatted:

```text
event: property.started
data: {"type":"property.started","stage":"abstat.property",...}

```

Important sampling events:

- `run.created`: run row has been created and contains the `run.id`.
- `run.started`: sampling worker started.
- `properties.list`: initial property list was fetched when not using dynamic seed discovery.
- `properties.filtered`: properties are ready for analysis.
- `property.started`: one discovered property is being processed.
- `property.completed`: patterns/types for that property have been extracted.
- `properties.discovered`: dynamic `seed_property` discovery finished.
- `graph.updated`: ontology or pattern graph is available.
- `subgraph.discovered`: one mined subgraph is available.
- `subgraph.samples`: sampled entities and readable edge details are available for one subgraph.
- `result`: final successful response payload.
- `error`: terminal failure payload.
- `done`: stream is complete.

Important LLM events:

- `subgraph.started`: text-query pipeline began for a subgraph.
- `prompt.ready`: prompt/subgraph pattern is available.
- `stage.started` / `stage.completed` with stages such as `llm.generate`, `sparql.execute`, `llm.complexity`, `llm.verify`, and `llm.reword`.
- `subgraph.completed`: final QA result for one subgraph is available.
- `result`, `error`, and `done` have the same meaning as sampling.

All streamed pipeline events are also persisted to `run_events`, so the frontend can reconnect or replay with `GET /api/v1/runs/{run_id}/events`.

## Artifact Safety

The current ABSTAT LLM pipeline accepts `input_yaml_path` for compatibility with notebooks and scripts. That is not the ideal long-term web contract. For a public deployment, prefer passing artifact IDs or Supabase Storage paths rather than raw server paths. Set `GRASP_ARTIFACT_ROOT` to restrict compatibility paths to one server-owned directory.

## Streaming Roadmap

The POST streams provide live updates for the first Svelte integration. A future queue-backed worker can split run creation from execution, allowing `POST /api/v1/abstat/sample` to return immediately and a separate `GET /api/v1/runs/{run_id}/events/stream` endpoint to replay persisted events from any point in the run.