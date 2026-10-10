from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from querybloom.events import PipelineEvent
from querybloom.llm import process_subgraphs_data, process_subgraphs_yaml
from querybloom.sampling_service import (
    SamplingRunConfig,
    run_mining_from_patterns,
    run_sampling,
    sampling_defaults,
    sampling_ui_metadata,
)
from querybloom.api.models import (
    ABSTATLLMRunRequest,
    ABSTATSampleRunRequest,
    ArtifactCreate,
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthSignupRequest,
    EventCreate,
    LLMRunRequest,
    ProjectCreate,
    ProjectUpdate,
    QAPairCreate,
    RunCreate,
    RunUpdate,
    SubgraphCreate,
    llm_ui_metadata,
)
from querybloom.api.supabase import (
    SupabaseClient,
    SupabasePersistenceIdentity,
    SupabaseUser,
    get_supabase_client,
    require_user,
)


api_router = APIRouter(prefix="/api/v1", tags=["api-v1"])
_logger = logging.getLogger(__name__)
_PERSISTENCE_MAX_ATTEMPTS = 3
_PERSISTENCE_RETRY_DELAYS = (0.25, 0.5)
_RETRYABLE_PERSISTENCE_STATUSES = {401, 408, 409, 425, 429, 500, 502, 503, 504}


def _subgraph_num_types(subgraph: dict[str, Any]) -> int | None:
    if subgraph.get("num_types") is not None:
        return subgraph.get("num_types")
    types = subgraph.get("types")
    if isinstance(types, (dict, list, set, tuple)):
        return len(types)
    return None


class _SkipEvent:
    _prefix = "grasp_skip"

    def __init__(self, run_id: str) -> None:
        self._event = threading.Event()
        self._sentinel = Path(tempfile.gettempdir()) / f"{self._prefix}_{run_id}"

    def is_set(self) -> bool:
        return self._event.is_set() or self._sentinel.exists()

    def set(self) -> None:
        self._event.set()
        try:
            self._sentinel.touch()
        except OSError:
            pass

    def clear(self) -> None:
        self._event.clear()
        try:
            self._sentinel.unlink(missing_ok=True)
        except OSError:
            pass

    @classmethod
    def write_sentinel(cls, run_id: str) -> None:
        """Write a sentinel file for a run_id (used when in-memory state is gone)."""
        try:
            (Path(tempfile.gettempdir()) / f"{cls._prefix}_{run_id}").touch()
        except OSError:
            pass


_active_skip_events: dict[str, threading.Event] = {}
_active_skip_mining_events: dict[str, _SkipEvent] = {}
_active_stop_events: dict[str, threading.Event] = {}
_active_run_owners: dict[str, str] = {}


def _stream_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def _sse_message(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_model_dump(model: Any, *, exclude_none: bool = False, exclude_unset: bool = False) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=exclude_none, exclude_unset=exclude_unset)


def _first_or_404(rows: list[dict[str, Any]], resource: str) -> dict[str, Any]:
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found")
    return rows[0]


def _first_or_empty(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {}


def _owned_payload(user: SupabaseUser, payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "owner_id": user.id}


def _persistence_payload(identity: SupabasePersistenceIdentity, payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "owner_id": identity.owner_id}


def _persistence_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _require_persisted_rows(rows: list[dict[str, Any]], operation: str) -> list[dict[str, Any]]:
    if not rows:
        raise RuntimeError(f"Supabase returned no rows for {operation}")
    return rows


def _persist_with_retry(
    operation: str,
    run_id: str,
    table: str,
    callback: Callable[[], Any],
) -> tuple[bool, Any]:
    for attempt in range(1, _PERSISTENCE_MAX_ATTEMPTS + 1):
        try:
            return True, callback()
        except Exception as exc:
            status_code = _persistence_status_code(exc)
            retryable = status_code in _RETRYABLE_PERSISTENCE_STATUSES or status_code is None
            if retryable and attempt < _PERSISTENCE_MAX_ATTEMPTS:
                _logger.warning(
                    "Persistence attempt failed operation=%s run_id=%s table=%s status=%s attempt=%d/%d error=%s",
                    operation,
                    run_id,
                    table,
                    status_code,
                    attempt,
                    _PERSISTENCE_MAX_ATTEMPTS,
                    exc,
                )
                time.sleep(_PERSISTENCE_RETRY_DELAYS[attempt - 1])
                continue
            _logger.error(
                "Persistence failed operation=%s run_id=%s table=%s status=%s attempt=%d/%d error=%s",
                operation,
                run_id,
                table,
                status_code,
                attempt,
                _PERSISTENCE_MAX_ATTEMPTS,
                exc,
                exc_info=True,
            )
            return False, None
    return False, None


def _id_filter(row_id: str) -> dict[str, str]:
    return {"id": f"eq.{row_id}"}


def _run_filter(run_id: str) -> dict[str, str]:
    return {"run_id": f"eq.{run_id}"}


def _guard_artifact_path(path: str | None) -> None:
    root = os.environ.get("GRASP_ARTIFACT_ROOT")
    if not root or not path:
        return
    root_abs = os.path.abspath(root)
    path_abs = os.path.abspath(path)
    if path_abs != root_abs and not path_abs.startswith(f"{root_abs}{os.sep}"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is outside GRASP_ARTIFACT_ROOT",
        )


def _insert_one(client: SupabaseClient, user: SupabaseUser, table: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _first_or_empty(client.rest_insert(user.access_token, table, _owned_payload(user, payload)))


def _update_one(client: SupabaseClient, user: SupabaseUser, table: str, row_id: str, payload: dict[str, Any], resource: str) -> dict[str, Any]:
    rows = client.rest_update(user.access_token, table, _id_filter(row_id), payload)
    return _first_or_404(rows, resource)


def _delete_one(client: SupabaseClient, user: SupabaseUser, table: str, row_id: str, resource: str) -> dict[str, Any]:
    rows = client.rest_delete(user.access_token, table, _id_filter(row_id))
    _first_or_404(rows, resource)
    return {"ok": True}


def _create_run(client: SupabaseClient, user: SupabaseUser, payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_one(client, user, "runs", payload)


def _update_run_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    run_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    succeeded, rows = _persist_with_retry(
        "update",
        run_id,
        "runs",
        lambda: _require_persisted_rows(
            client.rest_update(identity.access_token, "runs", _id_filter(run_id), payload),
            "run update",
        ),
    )
    return _first_or_empty(rows) if succeeded else {}


def _persist_event_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    run_id: str,
    event: PipelineEvent,
) -> None:
    _persist_with_retry(
        "insert",
        run_id,
        "run_events",
        lambda: client.rest_insert(
            identity.access_token,
            "run_events",
            _persistence_payload(
                identity,
                {
                    "run_id": run_id,
                    "event_type": event.type,
                    "stage": event.stage,
                    "message": event.message,
                    "payload": event.data,
                },
            ),
        ),
    )


def _persist_artifact_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    _persist_with_retry(
        "insert",
        run_id,
        "artifacts",
        lambda: client.rest_insert(
            identity.access_token,
            "artifacts",
            _persistence_payload(identity, {"run_id": run_id, **payload}),
        ),
    )


def _persist_subgraph_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    run_id: str,
    subgraph_index: int,
    subgraph: dict[str, Any],
    graph: dict[str, Any] | None = None,
) -> bool:
    succeeded, _ = _persist_with_retry(
        "insert",
        run_id,
        "subgraphs",
        lambda: _require_persisted_rows(
            client.rest_insert(
                identity.access_token,
                "subgraphs",
                _persistence_payload(
                    identity,
                    {
                        "run_id": run_id,
                        "subgraph_index": subgraph_index,
                        "support": subgraph.get("support"),
                        "num_types": _subgraph_num_types(subgraph),
                        "graph": graph or {},
                        "payload": subgraph,
                    },
                ),
            ),
            "subgraph insert",
        ),
    )
    return succeeded


def _update_subgraph_payload_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    run_id: str,
    subgraph_index: int,
    payload: dict[str, Any],
) -> None:
    _persist_with_retry(
        "update",
        run_id,
        "subgraphs",
        lambda: client.rest_update(
            identity.access_token,
            "subgraphs",
            {"run_id": f"eq.{run_id}", "subgraph_index": f"eq.{subgraph_index}"},
            {"payload": payload},
        ),
    )


def _upsert_subgraph_result_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    run_id: str,
    subgraph_index: int,
    subgraph: dict[str, Any],
) -> None:
    payload = dict(subgraph)
    graph = payload.pop("graph", None)
    row_payload = {
        "run_id": run_id,
        "subgraph_index": subgraph_index,
        "support": payload.get("support"),
        "num_types": _subgraph_num_types(payload),
        "graph": graph if isinstance(graph, dict) else {},
        "payload": payload,
    }
    def upsert() -> None:
        updated = client.rest_update(
            identity.access_token,
            "subgraphs",
            {"run_id": f"eq.{run_id}", "subgraph_index": f"eq.{subgraph_index}"},
            row_payload,
        )
        if updated:
            return
        client.rest_insert(
            identity.access_token,
            "subgraphs",
            _persistence_payload(identity, row_payload),
        )

    _persist_with_retry("upsert", run_id, "subgraphs", upsert)


def _persist_llm_subgraph_results_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    run_id: str,
    subgraphs: list[dict[str, Any]],
) -> None:
    for index, subgraph in enumerate(subgraphs):
        if not isinstance(subgraph, dict):
            continue
        subgraph_index = subgraph.get("source_subgraph_index", index)
        _upsert_subgraph_result_best_effort(client, identity, run_id, int(subgraph_index), subgraph)


def _sample_event_sink(client: SupabaseClient, identity: SupabasePersistenceIdentity, run_id: str):
    persisted_subgraphs: set[int] = set()

    def sink(event: PipelineEvent) -> None:
        if event.type != "subgraph.discovered":
            _persist_event_best_effort(client, identity, run_id, event)
        data = event.data or {}

        if event.type == "graph.updated" and isinstance(data.get("graph"), dict):
            _persist_artifact_best_effort(
                client,
                identity,
                run_id,
                {
                    "kind": "graph",
                    "label": event.message or event.stage,
                    "metadata": {"stage": event.stage, "event_type": event.type},
                    "payload": data["graph"],
                },
            )

        if event.type == "subgraph.discovered" and isinstance(data.get("subgraph"), dict):
            index = data.get("index")
            if isinstance(index, int) and index not in persisted_subgraphs:
                succeeded = _persist_subgraph_best_effort(
                    client,
                    identity,
                    run_id,
                    index,
                    data["subgraph"],
                    data.get("graph") if isinstance(data.get("graph"), dict) else None,
                )
                if succeeded:
                    persisted_subgraphs.add(index)

        if event.type == "subgraph.samples" and isinstance(data.get("samples"), dict):
            index = data.get("index")
            if isinstance(index, int):
                _update_subgraph_payload_best_effort(
                    client, identity, run_id, index, data["samples"]
                )

    sink.persisted_subgraphs = persisted_subgraphs  # type: ignore[attr-defined]
    return sink


def _load_sample_run_subgraphs(client: SupabaseClient, user: SupabaseUser, sample_run_id: str) -> list[dict[str, Any]]:
    run_rows = client.rest_select(user.access_token, "runs", {**_id_filter(sample_run_id), "limit": "1"})
    run = _first_or_404(run_rows, "sample run")
    if run.get("kind") != "sample":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sample_run_id must reference a sampling run")

    subgraph_rows = client.rest_select(
        user.access_token,
        "subgraphs",
        {**_run_filter(sample_run_id), "order": "subgraph_index.asc"},
    )
    subgraphs: list[dict[str, Any]] = []
    for row in subgraph_rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        merged = dict(payload)
        sg_idx = row.get("subgraph_index")
        if sg_idx is not None:
            try:
                merged["subgraph_index"] = int(sg_idx)
                merged["index"] = int(sg_idx)
            except (ValueError, TypeError):
                pass
        if row.get("id"):
            merged["id"] = row["id"]
            merged["dbId"] = row["id"]
        graph = row.get("graph")
        if isinstance(graph, dict) and graph and "graph" not in merged:
            merged["graph"] = graph
        if merged.get("support") is None and row.get("support") is not None:
            merged["support"] = row.get("support")
        if merged.get("num_types") is None and row.get("num_types") is not None:
            merged["num_types"] = row.get("num_types")
        subgraphs.append(merged)
    if subgraphs:
        return subgraphs

    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    result_subgraphs = result.get("subgraphs") if isinstance(result, dict) else None
    if isinstance(result_subgraphs, list):
        items = []
        for idx, item in enumerate(result_subgraphs):
            if isinstance(item, dict):
                merged_item = dict(item)
                sg_idx = item.get("source_subgraph_index", item.get("subgraph_index", item.get("index", idx)))
                try:
                    merged_item["subgraph_index"] = int(sg_idx)
                    merged_item["index"] = int(sg_idx)
                except (ValueError, TypeError):
                    merged_item["subgraph_index"] = idx
                    merged_item["index"] = idx
                items.append(merged_item)
        return items

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sample run has no stored subgraphs")


def _load_sample_run_subgraph_rows(
    client: SupabaseClient,
    user: SupabaseUser,
    sample_run_id: str,
) -> list[dict[str, Any]]:
    return client.rest_select(
        user.access_token,
        "subgraphs",
        {**_run_filter(sample_run_id), "order": "subgraph_index.asc"},
    )


def _is_active_qa_pair(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return not metadata.get("deleted_at") and metadata.get("active", True) is not False


def _soft_delete_qa_pairs_for_subgraph(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    sample_run_id: str,
    subgraph_id: str,
    llm_run_id: str,
) -> None:
    rows = client.rest_select(
        identity.access_token,
        "qa_pairs",
        {
            "select": "*",
            "run_id": f"eq.{sample_run_id}",
            "subgraph_id": f"eq.{subgraph_id}",
            "order": "created_at.asc",
        },
    )
    deleted_at = _now_iso()
    for row in rows:
        if not _is_active_qa_pair(row):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        client.rest_update(
            identity.access_token,
            "qa_pairs",
            _id_filter(row["id"]),
            {
                "metadata": {
                    **metadata,
                    "active": False,
                    "deleted_at": deleted_at,
                    "superseded_by_llm_run_id": llm_run_id,
                }
            },
        )


def _persist_qa_pairs_for_subgraph_best_effort(
    client: SupabaseClient,
    identity: SupabasePersistenceIdentity,
    sample_run_id: str | None,
    subgraph_index: int | None,
    result: dict[str, Any],
    llm_run_id: str,
    llm_request: LLMRunRequest,
    subgraph_row_by_index: dict[int, dict[str, Any]],
) -> None:
    if sample_run_id is None or subgraph_index is None:
        return
    try:
        subgraph_index = int(subgraph_index)
    except (TypeError, ValueError):
        return
    qa_pairs = result.get("qa_pairs")
    if not isinstance(qa_pairs, list):
        return
    subgraph_row = subgraph_row_by_index.get(subgraph_index)
    subgraph_id = subgraph_row.get("id") if isinstance(subgraph_row, dict) else None
    if not subgraph_id:
        print(f"[QA persist] Warning: no subgraph_id found for subgraph_index {subgraph_index} in sample run {sample_run_id}")
        return
    subgraph_payload = (
        subgraph_row.get("payload")
        if isinstance(subgraph_row.get("payload"), dict)
        else {}
    )
    qa_result = {
        "status": "completed",
        "is_meaningful": result.get("is_meaningful"),
        "skip_reason": result.get("skip_reason") or "",
        "cost_usd": result.get("cost_usd"),
        "llm_usage": result.get("llm_usage"),
        "llm_run_id": llm_run_id,
    }
    def persist() -> None:
        _soft_delete_qa_pairs_for_subgraph(
            client, identity, sample_run_id, subgraph_id, llm_run_id
        )
        client.rest_update(
            identity.access_token,
            "subgraphs",
            _id_filter(subgraph_id),
            {"payload": {**subgraph_payload, "qa_result": qa_result}},
        )
        now = _now_iso()
        rows: list[dict[str, Any]] = []
        for pair_index, pair in enumerate(qa_pairs):
            if not isinstance(pair, dict):
                continue
            question = pair.get("question") or pair.get("text_query")
            sparql_query = pair.get("sparql_query") or pair.get("query")
            if not question or not sparql_query:
                continue
            rows.append(
                _persistence_payload(
                    identity,
                    {
                        "run_id": sample_run_id,
                        "subgraph_id": subgraph_id,
                        "question": str(question),
                        "sparql_query": str(sparql_query),
                        "execution_result": pair.get("execution_results")
                        or pair.get("execution_result")
                        or {},
                        "verification_status": pair.get("verification_status"),
                        "metadata": {
                            "active": True,
                            "generated_at": now,
                            "source": "abstat.llm",
                            "llm_run_id": llm_run_id,
                            "subgraph_index": subgraph_index,
                            "pair_index": pair_index,
                            "model": llm_request.model,
                            "verify_iterations": llm_request.verify_iterations,
                            "focus_entity_qa": llm_request.focus_entity_qa,
                            "cost_usd": result.get("cost_usd"),
                            "subgraph_cost_usd": result.get("cost_usd"),
                            "llm_usage": result.get("llm_usage"),
                            "qa_pair": pair,
                        },
                    },
                )
            )
        if rows:
            client.rest_insert(identity.access_token, "qa_pairs", rows)

    _persist_with_retry("replace", llm_run_id, "qa_pairs", persist)


@api_router.post("/client-logs")
async def _client_logs(payload: dict[str, Any]):
    msg = payload.get("message") or "Unknown client error"
    stack = payload.get("stack")
    url = payload.get("url")
    ctx = payload.get("context")
    out = f"[BROWSER ERROR] {msg}"
    if url:
        out += f"\n  URL: {url}"
    if ctx:
        out += f"\n  Context: {ctx}"
    if stack:
        out += f"\n  Stack:\n{stack}"
    print(out, flush=True)
    return {"status": "ok"}


@api_router.get("/health")
async def _health():
    client = get_supabase_client(required=False)
    if not client.configured:
        return {"ok": True, "supabase_configured": False, "database_ready": False}

    try:
        await asyncio.to_thread(
            client.rest_select,
            "",
            "projects",
            {"select": "id", "limit": "1"},
        )
    except HTTPException as exc:
        return {
            "ok": True,
            "supabase_configured": True,
            "database_ready": False,
            "database_status": exc.status_code,
            "database_error": exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail),
        }

    return {"ok": True, "supabase_configured": True, "database_ready": True}


@api_router.post("/auth/signup")
async def _auth_signup(request: AuthSignupRequest):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(client.auth_signup, request.email, request.password, request.display_name)


@api_router.post("/auth/login")
async def _auth_login(request: AuthLoginRequest):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(client.auth_login, request.email, request.password)


@api_router.post("/auth/refresh")
async def _auth_refresh(request: AuthRefreshRequest):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(client.auth_refresh, request.refresh_token)


@api_router.post("/auth/logout")
async def _auth_logout(user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(client.auth_logout, user.access_token)


@api_router.get("/auth/me")
async def _auth_me(user: SupabaseUser = Depends(require_user)):
    return user.raw


@api_router.get("/projects")
async def _projects(user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(
        client.rest_select,
        user.access_token,
        "projects",
        {"select": "*", "order": "created_at.desc"},
    )


@api_router.post("/projects")
async def _create_project(request: ProjectCreate, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    payload = _json_model_dump(request, exclude_none=True)
    return await asyncio.to_thread(_insert_one, client, user, "projects", payload)


@api_router.get("/projects/{project_id}")
async def _project(project_id: str, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    rows = await asyncio.to_thread(
        client.rest_select,
        user.access_token,
        "projects",
        {"select": "*", "id": f"eq.{project_id}", "limit": "1"},
    )
    return _first_or_404(rows, "Project")


@api_router.patch("/projects/{project_id}")
async def _update_project(project_id: str, request: ProjectUpdate, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    payload = _json_model_dump(request, exclude_unset=True, exclude_none=True)
    return await asyncio.to_thread(_update_one, client, user, "projects", project_id, payload, "Project")


@api_router.delete("/projects/{project_id}")
async def _delete_project(project_id: str, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(_delete_one, client, user, "projects", project_id, "Project")


@api_router.get("/runs")
async def _runs(
    project_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: SupabaseUser = Depends(require_user),
):
    client = get_supabase_client(required=True)
    params: dict[str, Any] = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
    if project_id:
        params["project_id"] = f"eq.{project_id}"
    if kind:
        params["kind"] = f"eq.{kind}"
    return await asyncio.to_thread(client.rest_select, user.access_token, "runs", params)


@api_router.post("/runs")
async def _create_run_endpoint(request: RunCreate, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    payload = _json_model_dump(request, exclude_none=True)
    return await asyncio.to_thread(_create_run, client, user, payload)


@api_router.get("/runs/{run_id}")
async def _run(run_id: str, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    rows = await asyncio.to_thread(
        client.rest_select,
        user.access_token,
        "runs",
        {"select": "*", "id": f"eq.{run_id}", "limit": "1"},
    )
    return _first_or_404(rows, "Run")


@api_router.patch("/runs/{run_id}")
async def _update_run_endpoint(run_id: str, request: RunUpdate, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    payload = _json_model_dump(request, exclude_unset=True, exclude_none=True)
    return await asyncio.to_thread(_update_one, client, user, "runs", run_id, payload, "Run")


@api_router.delete("/runs/{run_id}")
async def _delete_run(run_id: str, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(_delete_one, client, user, "runs", run_id, "Run")


async def _list_run_children(
    run_id: str,
    table: str,
    order: str,
    user: SupabaseUser,
    extra_params: dict[str, Any] | None = None,
):
    client = get_supabase_client(required=True)
    params = {"select": "*", "run_id": f"eq.{run_id}", "order": order}
    if extra_params:
        params.update(extra_params)
    return await asyncio.to_thread(client.rest_select, user.access_token, table, params)


async def _create_run_child(run_id: str, table: str, payload: dict[str, Any], user: SupabaseUser):
    client = get_supabase_client(required=True)
    return await asyncio.to_thread(_insert_one, client, user, table, {"run_id": run_id, **payload})


@api_router.get("/runs/{run_id}/events")
async def _run_events(
    run_id: str,
    after: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    user: SupabaseUser = Depends(require_user),
):
    params: dict[str, Any] = {}
    if after:
        params["created_at"] = f"gt.{after}"
    if limit:
        params["limit"] = str(limit)
    return await _list_run_children(run_id, "run_events", "created_at.asc", user, params)


@api_router.post("/runs/{run_id}/events")
async def _create_run_event(run_id: str, request: EventCreate, user: SupabaseUser = Depends(require_user)):
    return await _create_run_child(run_id, "run_events", _json_model_dump(request, exclude_none=True), user)


@api_router.get("/runs/{run_id}/artifacts")
async def _run_artifacts(run_id: str, user: SupabaseUser = Depends(require_user)):
    return await _list_run_children(run_id, "artifacts", "created_at.desc", user)


@api_router.post("/runs/{run_id}/artifacts")
async def _create_run_artifact(run_id: str, request: ArtifactCreate, user: SupabaseUser = Depends(require_user)):
    return await _create_run_child(run_id, "artifacts", _json_model_dump(request, exclude_none=True), user)


@api_router.get("/runs/{run_id}/subgraphs")
async def _run_subgraphs(run_id: str, user: SupabaseUser = Depends(require_user)):
    return await _list_run_children(run_id, "subgraphs", "subgraph_index.asc", user)


@api_router.post("/runs/{run_id}/subgraphs")
async def _create_run_subgraph(run_id: str, request: SubgraphCreate, user: SupabaseUser = Depends(require_user)):
    return await _create_run_child(run_id, "subgraphs", _json_model_dump(request, exclude_none=True), user)


@api_router.get("/runs/{run_id}/qa-pairs")
async def _run_qa_pairs(
    run_id: str,
    active_only: bool = Query(default=True),
    user: SupabaseUser = Depends(require_user),
):
    rows = await _list_run_children(run_id, "qa_pairs", "created_at.asc", user)
    if active_only:
        rows = [row for row in rows if _is_active_qa_pair(row)]
    return rows


@api_router.post("/runs/{run_id}/qa-pairs")
async def _create_run_qa_pair(run_id: str, request: QAPairCreate, user: SupabaseUser = Depends(require_user)):
    return await _create_run_child(run_id, "qa_pairs", _json_model_dump(request, exclude_none=True), user)


@api_router.get("/abstat/defaults")
async def _abstat_defaults():
    return {
        "sampling": sampling_defaults(),
        "llm": LLMRunRequest(endpoint="").model_dump(),
        "ui": {
            "sampling": sampling_ui_metadata(),
            "llm": llm_ui_metadata(),
        },
        "schemas": {
            "sampling": SamplingRunConfig.model_json_schema(),
            "llm": LLMRunRequest.model_json_schema(),
        },
    }


@api_router.post("/abstat/sample")
async def _abstat_sample(request: ABSTATSampleRunRequest, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    persistence_identity = client.persistence_identity(user.id)
    config = request.config.model_copy(
        update={
            "preprocess": request.config.preprocess.model_copy(update={"persist_cache": False}),
            "mine": request.config.mine.model_copy(update={"output_dir": None}),
        }
    )
    run = await asyncio.to_thread(
        _create_run,
        client,
        user,
        {
            "project_id": request.project_id,
            "kind": "sample",
            "status": "running",
            "title": request.title or f"ABSTAT sample: {config.endpoint}",
            "endpoint": config.endpoint,
            "config": _json_model_dump(config),
            "started_at": _now_iso(),
        },
    )
    run_id = run.get("id")
    if not run_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create run")

    event_sink = _sample_event_sink(client, persistence_identity, run_id)
    if config.run_id is None:
        config = config.model_copy(update={"run_id": run_id})

    try:
        result = await asyncio.to_thread(run_sampling, config, event_sink)
        result_payload = result.model_dump(mode="json")
        persisted = getattr(event_sink, "persisted_subgraphs", set())
        for index, subgraph in enumerate(result_payload.get("subgraphs", [])):
            if index not in persisted and isinstance(subgraph, dict):
                await asyncio.to_thread(
                    _persist_subgraph_best_effort,
                    client,
                    persistence_identity,
                    run_id,
                    index,
                    subgraph,
                )
        if result.output_path:
            await asyncio.to_thread(
                _persist_artifact_best_effort,
                client,
                persistence_identity,
                run_id,
                {
                    "kind": "yaml",
                    "label": "Sampled subgraphs YAML",
                    "storage_path": result.output_path,
                    "metadata": {"source": "abstat.sample"},
                },
            )
        if result.ontology_graph:
            await asyncio.to_thread(
                _persist_artifact_best_effort,
                client,
                persistence_identity,
                run_id,
                {
                    "kind": "graph",
                    "label": "Ontology graph",
                    "metadata": {"source": "abstat.sample"},
                    "payload": result.ontology_graph,
                },
            )
        updated = await asyncio.to_thread(
            _update_run_best_effort,
            client,
            persistence_identity,
            run_id,
            {"status": "completed", "result": result_payload, "completed_at": _now_iso()},
        )
        return {"run": updated or run, "result": result_payload}
    except Exception as exc:
        await asyncio.to_thread(
            _update_run_best_effort,
            client,
            persistence_identity,
            run_id,
            {"status": "failed", "error": str(exc), "completed_at": _now_iso()},
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@api_router.post("/abstat/sample/stream")
async def _abstat_sample_stream(request: ABSTATSampleRunRequest, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    persistence_identity = client.persistence_identity(user.id)
    owner_id = user.id
    config = request.config.model_copy(
        update={
            "preprocess": request.config.preprocess.model_copy(update={"persist_cache": False}),
            "mine": request.config.mine.model_copy(update={"output_dir": None}),
        }
    )
    user_active_count = sum(1 for uid in _active_run_owners.values() if uid == user.id)
    if user_active_count >= 2:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You already have 2 runs in progress. Wait for one to finish before starting another.",
        )
    run = await asyncio.to_thread(
        _create_run,
        client,
        user,
        {
            "project_id": request.project_id,
            "kind": "sample",
            "status": "running",
            "title": request.title or f"ABSTAT sample: {config.endpoint}",
            "endpoint": config.endpoint,
            "config": _json_model_dump(config),
            "started_at": _now_iso(),
        },
    )
    run_id = run.get("id")
    if not run_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create run")

    if config.run_id is None:
        config = config.model_copy(update={"run_id": run_id})

    async def stream():
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop_event = threading.Event()
        skip_event = threading.Event()
        skip_mining_event = _SkipEvent(run_id)
        skip_mining_event.clear()
        _active_skip_events[run_id] = skip_event
        _active_skip_mining_events[run_id] = skip_mining_event
        _active_stop_events[run_id] = stop_event
        _active_run_owners[run_id] = owner_id
        persistent_event_sink = _sample_event_sink(client, persistence_identity, run_id)
        emitted_error_messages: set[str] = set()

        def enqueue(kind: str, payload: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

        def event_sink(event: PipelineEvent) -> None:
            if event.run_id is None:
                event.run_id = run_id
            if event.type == "error" and event.message:
                emitted_error_messages.add(event.message)
            persistent_event_sink(event)
            enqueue("event", event.to_dict())

        def worker() -> None:
            try:
                result = run_sampling(config, event_sink, stop_event, skip_event=skip_event, skip_mining_event=skip_mining_event)
                result_payload = result.model_dump(mode="json")
                run_status = "cancelled" if stop_event.is_set() else "completed"
                persisted = getattr(persistent_event_sink, "persisted_subgraphs", set())
                for index, subgraph in enumerate(result_payload.get("subgraphs", [])):
                    if index not in persisted and isinstance(subgraph, dict):
                        _persist_subgraph_best_effort(
                            client, persistence_identity, run_id, index, subgraph
                        )
                if result.output_path:
                    _persist_artifact_best_effort(
                        client,
                        persistence_identity,
                        run_id,
                        {
                            "kind": "yaml",
                            "label": "Sampled subgraphs YAML",
                            "storage_path": result.output_path,
                            "metadata": {"source": "abstat.sample"},
                        },
                    )
                if result.ontology_graph:
                    _persist_artifact_best_effort(
                        client,
                        persistence_identity,
                        run_id,
                        {
                            "kind": "graph",
                            "label": "Ontology graph",
                            "metadata": {"source": "abstat.sample"},
                            "payload": result.ontology_graph,
                        },
                    )
                updated = _update_run_best_effort(
                    client,
                    persistence_identity,
                    run_id,
                    {"status": run_status, "result": result_payload, "completed_at": _now_iso()},
                )
                enqueue("result", {"run": updated or run, "result": result_payload})
            except Exception as exc:
                _update_run_best_effort(
                    client,
                    persistence_identity,
                    run_id,
                    {"status": "failed", "error": str(exc), "completed_at": _now_iso()},
                )
                if str(exc) not in emitted_error_messages:
                    enqueue("error", {"run_id": run_id, "error": str(exc)})
            finally:
                _active_skip_events.pop(run_id, None)
                mining_ev = _active_skip_mining_events.pop(run_id, None)
                if mining_ev is not None:
                    mining_ev.clear()
                _active_stop_events.pop(run_id, None)
                _active_run_owners.pop(run_id, None)
                enqueue("done", {"run_id": run_id})

        task = asyncio.create_task(asyncio.to_thread(worker))
        yield _sse_message("run.created", {"run": run})
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if kind == "event":
                    yield _sse_message(payload.get("type", "event"), payload)
                elif kind == "result":
                    yield _sse_message("result", payload)
                elif kind == "error":
                    yield _sse_message("error", payload)
                elif kind == "done":
                    yield _sse_message("done", payload)
                    break
        finally:
            # Client disconnected from SSE stream (closed tab, dropped network).
            # The background worker continues executing and persisting events/subgraphs to DB.
            pass

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_stream_headers())


@api_router.post("/abstat/sample/{run_id}/cancel")
async def _cancel_run(run_id: str, user: SupabaseUser = Depends(require_user)):
    stop_ev = _active_stop_events.get(run_id)
    if stop_ev is None:
        raise HTTPException(status_code=404, detail="Run not found or not currently active")
    stop_ev.set()
    skip_ev = _active_skip_events.get(run_id)
    if skip_ev is not None:
        skip_ev.set()
    mining_ev = _active_skip_mining_events.get(run_id)
    if mining_ev is not None:
        mining_ev.set()
    else:
        _SkipEvent.write_sentinel(run_id)
    return {"status": "ok", "run_id": run_id}


@api_router.post("/runs/cleanup-stale")
async def _cleanup_stale_runs(user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    running_rows = await asyncio.to_thread(
        client.rest_select,
        user.access_token,
        "runs",
        {"select": "id", "status": "eq.running"},
    )
    stale_ids = [r["id"] for r in running_rows if r.get("id") not in _active_stop_events]
    if not stale_ids:
        return {"cleaned": 0}
    id_list = ",".join(stale_ids)
    updated = await asyncio.to_thread(
        client.rest_update,
        user.access_token,
        "runs",
        {"id": f"in.({id_list})"},
        {"status": "cancelled", "completed_at": _now_iso()},
    )
    return {"cleaned": len(updated)}


@api_router.post("/abstat/sample/{run_id}/skip-discovery")
async def _skip_discovery(run_id: str, user: SupabaseUser = Depends(require_user)):
    skip_ev = _active_skip_events.get(run_id)
    if skip_ev is None:
        raise HTTPException(status_code=404, detail="Run not found or not in discovery phase")
    skip_ev.set()
    return {"status": "ok", "run_id": run_id}


@api_router.post("/abstat/sample/{run_id}/skip-subgraphs")
async def _skip_subgraphs(run_id: str, user: SupabaseUser = Depends(require_user)):
    skip_ev = _active_skip_mining_events.get(run_id)
    if skip_ev is not None:
        skip_ev.set()
    else:
        _SkipEvent.write_sentinel(run_id)
    return {"status": "ok", "run_id": run_id}


@api_router.post("/abstat/sample/{run_id}/restart-mining")
async def _restart_subgraph_mining(
    run_id: str,
    overwrite: bool = Query(default=False),
    user: SupabaseUser = Depends(require_user),
):
    client = get_supabase_client(required=True)
    persistence_identity = client.persistence_identity(user.id)
    run_rows = await asyncio.to_thread(
        client.rest_select,
        user.access_token,
        "runs",
        {**_id_filter(run_id), "limit": "1"},
    )
    run = _first_or_404(run_rows, "sampling run")
    if run.get("kind") != "sample":
        raise HTTPException(status_code=400, detail="Run is not a sampling run")
    if run_id in _active_stop_events or run.get("status") == "running":
        raise HTTPException(status_code=409, detail="Run is already active")

    subgraph_rows = await asyncio.to_thread(
        client.rest_select,
        user.access_token,
        "subgraphs",
        {**_run_filter(run_id), "select": "id"},
    )
    if subgraph_rows and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Run already has {len(subgraph_rows)} subgraphs; confirm overwrite to replace them",
        )

    pattern_data = (run.get("result") or {}).get("patterns")
    if not isinstance(pattern_data, dict):
        raise HTTPException(
            status_code=409,
            detail="Run has no persisted patterns to restart mining from",
        )

    if subgraph_rows:
        await asyncio.to_thread(
            client.rest_delete,
            user.access_token,
            "subgraphs",
            _run_filter(run_id),
        )

    stored_config = SamplingRunConfig.model_validate(run.get("config") or {})
    config = stored_config.model_copy(
        update={
            "run_id": run_id,
            "mine": stored_config.mine.model_copy(update={"output_dir": None}),
        }
    )
    updated_rows = await asyncio.to_thread(
        client.rest_update,
        user.access_token,
        "runs",
        _id_filter(run_id),
        {
            "status": "running",
            "error": None,
            "completed_at": None,
            "started_at": _now_iso(),
        },
    )
    active_run = _first_or_empty(updated_rows) or run
    owner_id = user.id

    async def stream():
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop_event = threading.Event()
        skip_mining_event = _SkipEvent(run_id)
        skip_mining_event.clear()
        _active_stop_events[run_id] = stop_event
        _active_skip_mining_events[run_id] = skip_mining_event
        _active_run_owners[run_id] = owner_id
        persistent_event_sink = _sample_event_sink(
            client, persistence_identity, run_id
        )

        def enqueue(kind: str, payload: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

        def event_sink(event: PipelineEvent) -> None:
            if event.run_id is None:
                event.run_id = run_id
            persistent_event_sink(event)
            enqueue("event", event.to_dict())

        def worker() -> None:
            try:
                result = run_mining_from_patterns(
                    config,
                    pattern_data,
                    event_sink,
                    stop_event,
                    skip_mining_event,
                )
                result_payload = {
                    **(run.get("result") or {}),
                    **result.model_dump(mode="json"),
                }
                run_status = "cancelled" if stop_event.is_set() else "completed"
                persisted = getattr(persistent_event_sink, "persisted_subgraphs", set())
                for index, subgraph in enumerate(result_payload.get("subgraphs", [])):
                    if index not in persisted and isinstance(subgraph, dict):
                        _persist_subgraph_best_effort(
                            client, persistence_identity, run_id, index, subgraph
                        )
                updated = _update_run_best_effort(
                    client,
                    persistence_identity,
                    run_id,
                    {
                        "status": run_status,
                        "result": result_payload,
                        "completed_at": _now_iso(),
                    },
                )
                enqueue("result", {"run": updated or active_run, "result": result_payload})
            except Exception as exc:
                _update_run_best_effort(
                    client,
                    persistence_identity,
                    run_id,
                    {"status": "failed", "error": str(exc), "completed_at": _now_iso()},
                )
                enqueue("error", {"run_id": run_id, "error": str(exc)})
            finally:
                mining_event = _active_skip_mining_events.pop(run_id, None)
                if mining_event is not None:
                    mining_event.clear()
                _active_stop_events.pop(run_id, None)
                _active_run_owners.pop(run_id, None)
                enqueue("done", {"run_id": run_id})

        asyncio.create_task(asyncio.to_thread(worker))
        yield _sse_message("run.created", {"run": active_run})
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if kind == "event":
                yield _sse_message(payload.get("type", "event"), payload)
            elif kind == "result":
                yield _sse_message("result", payload)
            elif kind == "error":
                yield _sse_message("error", payload)
            elif kind == "done":
                yield _sse_message("done", payload)
                break

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_stream_headers())


@api_router.post("/abstat/llm")
async def _abstat_llm(request: ABSTATLLMRunRequest, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    persistence_identity = client.persistence_identity(user.id)
    llm_request = request.request
    _guard_artifact_path(llm_request.input_yaml_path)
    _guard_artifact_path(llm_request.output_dir)

    run = await asyncio.to_thread(
        _create_run,
        client,
        user,
        {
            "project_id": request.project_id,
            "kind": "llm",
            "status": "running",
            "title": request.title or f"ABSTAT LLM: {llm_request.endpoint}",
            "endpoint": llm_request.endpoint,
            "config": _json_model_dump(llm_request),
            "started_at": _now_iso(),
        },
    )
    run_id = run.get("id")
    if not run_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create run")

    subgraph_row_by_index: dict[int, dict[str, Any]] = {}
    if llm_request.sample_run_id:
        subgraph_rows = await asyncio.to_thread(
            _load_sample_run_subgraph_rows, client, user, llm_request.sample_run_id
        )
        for row in subgraph_rows:
            sg_idx = row.get("subgraph_index")
            if sg_idx is not None:
                try:
                    subgraph_row_by_index[int(sg_idx)] = row
                except (ValueError, TypeError):
                    pass

    def event_sink(event: PipelineEvent) -> None:
        _persist_event_best_effort(client, persistence_identity, run_id, event)
        if event.type == "subgraph.completed" and event.stage == "llm.subgraph":
            data = event.data or {}
            _persist_qa_pairs_for_subgraph_best_effort(
                client,
                persistence_identity,
                llm_request.sample_run_id,
                data.get("subgraph_index"),
                data.get("result") if isinstance(data.get("result"), dict) else {},
                run_id,
                llm_request,
                subgraph_row_by_index,
            )

    try:
        if llm_request.sample_run_id:
            subgraphs = await asyncio.to_thread(_load_sample_run_subgraphs, client, user, llm_request.sample_run_id)
            output_subgraphs, output_path = await asyncio.to_thread(
                process_subgraphs_data,
                subgraphs,
                llm_request.endpoint,
                llm_request.model,
                llm_request.template_path,
                llm_request.output_dir,
                llm_request.timeout,
                llm_request.max_workers,
                llm_request.verify_iterations,
                llm_request.max_subgraphs,
                llm_request.subgraph_indices,
                llm_request.focus_entity_qa,
                llm_request.ents_ratio,
                llm_request.additional_instructions,
                llm_request.introduce_complexity_step,
                llm_request.reword_questions_step,
                f"run:{llm_request.sample_run_id}",
                f"sample-run-{llm_request.sample_run_id}.yaml",
                event_sink,
                kg_title=llm_request.kg_title,
                openrouter_provider=llm_request.openrouter_provider,
                openrouter_allow_fallbacks=llm_request.openrouter_allow_fallbacks,
            )
        else:
            if not llm_request.input_yaml_path:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide sample_run_id or input_yaml_path")
            args = llm_request.model_dump(mode="json", exclude={"run_id", "sample_run_id"})
            output_path = await asyncio.to_thread(process_subgraphs_yaml, **args, event_sink=event_sink)
            output_subgraphs = []

        await asyncio.to_thread(
            _persist_llm_subgraph_results_best_effort,
            client,
            persistence_identity,
            run_id,
            output_subgraphs,
        )

        await asyncio.to_thread(
            _persist_artifact_best_effort,
            client,
            persistence_identity,
            run_id,
            {
                "kind": "yaml",
                "label": "Generated QA results",
                "storage_path": output_path,
                "metadata": {
                    "source": "abstat.llm",
                    "input_yaml_path": llm_request.input_yaml_path,
                    "sample_run_id": llm_request.sample_run_id,
                },
                "payload": output_subgraphs or None,
            },
        )
        total_cost_usd = round(
            sum(
                sg.get("cost_usd", 0.0)
                for sg in output_subgraphs
                if isinstance(sg, dict) and isinstance(sg.get("cost_usd"), (int, float))
            ),
            6,
        ) if output_subgraphs else None
        result = {
            "output_path": output_path,
            "sample_run_id": llm_request.sample_run_id,
            "num_subgraphs": len(output_subgraphs) if output_subgraphs else None,
            "total_cost_usd": total_cost_usd,
        }
        updated = await asyncio.to_thread(
            _update_run_best_effort,
            client,
            persistence_identity,
            run_id,
            {"status": "completed", "result": result, "completed_at": _now_iso()},
        )
        return {"run": updated or run, "output_path": output_path}
    except Exception as exc:
        await asyncio.to_thread(
            _update_run_best_effort,
            client,
            persistence_identity,
            run_id,
            {"status": "failed", "error": str(exc), "completed_at": _now_iso()},
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@api_router.post("/abstat/llm/stream")
async def _abstat_llm_stream(request: ABSTATLLMRunRequest, user: SupabaseUser = Depends(require_user)):
    client = get_supabase_client(required=True)
    persistence_identity = client.persistence_identity(user.id)
    owner_id = user.id
    llm_request = request.request
    _guard_artifact_path(llm_request.input_yaml_path)
    _guard_artifact_path(llm_request.output_dir)

    attach_to_sample_run = bool(llm_request.sample_run_id)
    if attach_to_sample_run:
        run_rows = await asyncio.to_thread(
            client.rest_select,
            user.access_token,
            "runs",
            {**_id_filter(llm_request.sample_run_id), "limit": "1"},
        )
        run = _first_or_404(run_rows, "sample run")
        if run.get("kind") != "sample":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sample_run_id must reference a sampling run")
    else:
        run = await asyncio.to_thread(
            _create_run,
            client,
            user,
            {
                "project_id": request.project_id,
                "kind": "llm",
                "status": "running",
                "title": request.title or f"ABSTAT LLM: {llm_request.endpoint}",
                "endpoint": llm_request.endpoint,
                "config": _json_model_dump(llm_request),
                "started_at": _now_iso(),
            },
        )
    run_id = run.get("id")
    if not run_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to resolve run")

    subgraph_row_by_index: dict[int, dict[str, Any]] = {}
    input_subgraphs: list[dict[str, Any]] | None = None
    if llm_request.sample_run_id:
        subgraph_rows = await asyncio.to_thread(
            _load_sample_run_subgraph_rows, client, user, llm_request.sample_run_id
        )
        for row in subgraph_rows:
            sg_idx = row.get("subgraph_index")
            if sg_idx is not None:
                try:
                    subgraph_row_by_index[int(sg_idx)] = row
                except (ValueError, TypeError):
                    pass
        input_subgraphs = await asyncio.to_thread(
            _load_sample_run_subgraphs, client, user, llm_request.sample_run_id
        )

    async def stream():
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop_event = threading.Event()
        _active_stop_events[run_id] = stop_event
        if llm_request.sample_run_id:
            _active_stop_events[llm_request.sample_run_id] = stop_event
        _active_run_owners[run_id] = owner_id

        def enqueue(kind: str, payload: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

        def event_sink(event: PipelineEvent) -> None:
            if event.run_id is None:
                event.run_id = run_id
            _persist_event_best_effort(client, persistence_identity, run_id, event)
            if event.type == "subgraph.completed" and event.stage == "llm.subgraph":
                data = event.data or {}
                _persist_qa_pairs_for_subgraph_best_effort(
                    client,
                    persistence_identity,
                    llm_request.sample_run_id,
                    data.get("subgraph_index"),
                    data.get("result") if isinstance(data.get("result"), dict) else {},
                    run_id,
                    llm_request,
                    subgraph_row_by_index,
                )
            enqueue("event", event.to_dict())

        def worker() -> None:
            try:
                if llm_request.sample_run_id:
                    output_subgraphs, output_path = process_subgraphs_data(
                        input_subgraphs or [],
                        llm_request.endpoint,
                        llm_request.model,
                        llm_request.template_path,
                        llm_request.output_dir,
                        llm_request.timeout,
                        llm_request.max_workers,
                        llm_request.verify_iterations,
                        llm_request.max_subgraphs,
                        llm_request.subgraph_indices,
                        llm_request.focus_entity_qa,
                        llm_request.ents_ratio,
                        llm_request.additional_instructions,
                        llm_request.introduce_complexity_step,
                        llm_request.reword_questions_step,
                        f"run:{llm_request.sample_run_id}",
                        f"sample-run-{llm_request.sample_run_id}.yaml",
                        event_sink,
                        stop_event,
                        kg_title=llm_request.kg_title,
                        openrouter_provider=llm_request.openrouter_provider,
                        openrouter_allow_fallbacks=llm_request.openrouter_allow_fallbacks,
                    )
                else:
                    if not llm_request.input_yaml_path:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide sample_run_id or input_yaml_path")
                    args = llm_request.model_dump(mode="json", exclude={"run_id", "sample_run_id"})
                    output_path = process_subgraphs_yaml(**args, event_sink=event_sink)
                    output_subgraphs = []

                if not attach_to_sample_run:
                    _persist_llm_subgraph_results_best_effort(
                        client,
                        persistence_identity,
                        run_id,
                        output_subgraphs,
                    )

                _persist_artifact_best_effort(
                    client,
                    persistence_identity,
                    run_id,
                    {
                        "kind": "yaml",
                        "label": "Generated QA results",
                        "storage_path": output_path,
                        "metadata": {
                            "source": "abstat.llm",
                            "input_yaml_path": llm_request.input_yaml_path,
                            "sample_run_id": llm_request.sample_run_id,
                        },
                        "payload": output_subgraphs or None,
                    },
                )
                total_cost_usd = round(
                    sum(
                        sg.get("cost_usd", 0.0)
                        for sg in output_subgraphs
                        if isinstance(sg, dict) and isinstance(sg.get("cost_usd"), (int, float))
                    ),
                    6,
                ) if output_subgraphs else None
                result = {
                    "output_path": output_path,
                    "sample_run_id": llm_request.sample_run_id,
                    "num_subgraphs": len(output_subgraphs) if output_subgraphs else None,
                    "total_cost_usd": total_cost_usd,
                }
                updated = None
                if not attach_to_sample_run:
                    updated = _update_run_best_effort(
                        client,
                        persistence_identity,
                        run_id,
                        {"status": "completed", "result": result, "completed_at": _now_iso()},
                    )
                enqueue("result", {"run": updated or run, "output_path": output_path})
            except Exception as exc:
                if not attach_to_sample_run:
                    _update_run_best_effort(
                        client,
                        persistence_identity,
                        run_id,
                        {"status": "failed", "error": str(exc), "completed_at": _now_iso()},
                    )
                enqueue("error", {"run_id": run_id, "error": str(exc)})
            finally:
                _active_stop_events.pop(run_id, None)
                if llm_request.sample_run_id:
                    _active_stop_events.pop(llm_request.sample_run_id, None)
                _active_run_owners.pop(run_id, None)
                enqueue("done", {"run_id": run_id})

        task = asyncio.create_task(asyncio.to_thread(worker))
        yield _sse_message("run.created", {"run": run})
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if kind == "event":
                    yield _sse_message(payload.get("type", "event"), payload)
                elif kind == "result":
                    yield _sse_message("result", payload)
                elif kind == "error":
                    yield _sse_message("error", payload)
                elif kind == "done":
                    yield _sse_message("done", payload)
                    break
        finally:
            if task.done():
                await task

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_stream_headers())
