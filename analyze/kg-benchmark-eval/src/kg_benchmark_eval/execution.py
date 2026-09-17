"""SPARQL endpoint transport and normalized execution observations."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlencode

import httpx

from .config import SparqlEndpoint

logger = logging.getLogger(__name__)

Binding = Mapping[str, str]
ResultRow = Mapping[str, Binding]


@dataclass(frozen=True)
class ExecutionObservation:
    """Immutable normalized result or failure from one SPARQL request."""

    kind: Literal["select", "ask", "failure"]
    head_vars: tuple[str, ...] = ()
    rows: tuple[ResultRow, ...] = ()
    boolean: bool | None = None
    error: str | None = None
    observed_at: str = ""

    @property
    def id(self) -> str:
        payload = {
            "kind": self.kind,
            "head_vars": self.head_vars,
            "rows": [
                {name: dict(binding) for name, binding in row.items()}
                for row in self.rows
            ],
            "boolean": self.boolean,
            "error": self.error,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class SparqlTransport(Protocol):
    """Protocol implemented by transports that execute SPARQL requests."""

    def execute(
        self, query: str, *, endpoint: SparqlEndpoint
    ) -> ExecutionObservation: ...

    def close(self) -> None: ...


class HttpxSparqlTransport:
    """Execute SPARQL requests through a synchronous ``httpx`` client."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(headers=headers)

    def execute(self, query: str, *, endpoint: SparqlEndpoint) -> ExecutionObservation:
        data: list[tuple[str, str]] = [("query", query)]
        data.extend(("default-graph-uri", graph) for graph in endpoint.default_graphs)
        data.extend(("named-graph-uri", graph) for graph in endpoint.named_graphs)
        try:
            response = self._client.post(
                endpoint.url,
                content=urlencode(data, doseq=True).encode("utf-8"),
                headers={
                    "Accept": "application/sparql-results+json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=endpoint.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return failure_observation(
                    "SPARQL endpoint returned a non-object payload"
                )
            return normalize_sparql_results(payload)
        except Exception as exc:  # noqa: BLE001 - transport failures are observations
            logger.warning("SPARQL request to %s failed", endpoint.url, exc_info=True)
            return failure_observation(str(exc))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def normalize_sparql_results(payload: Mapping[str, object]) -> ExecutionObservation:
    observed_at = _now()
    boolean = payload.get("boolean")
    if isinstance(boolean, bool):
        return ExecutionObservation(
            kind="ask", boolean=boolean, observed_at=observed_at
        )

    head = payload.get("head", {})
    results = payload.get("results")
    if not isinstance(head, Mapping) or not isinstance(results, Mapping):
        return failure_observation("malformed SPARQL Results JSON", observed_at)
    raw_vars = head.get("vars", [])
    raw_rows = results.get("bindings")
    if not isinstance(raw_vars, list) or not all(
        isinstance(value, str) for value in raw_vars
    ):
        return failure_observation("malformed SPARQL head.vars", observed_at)
    if not isinstance(raw_rows, list):
        return failure_observation("malformed SPARQL results.bindings", observed_at)

    rows: list[ResultRow] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            return failure_observation("malformed SPARQL result row", observed_at)
        frozen_row: dict[str, Binding] = {}
        for variable, binding in row.items():
            if not isinstance(variable, str) or not isinstance(binding, Mapping):
                return failure_observation("malformed SPARQL binding", observed_at)
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in binding.items()
            ):
                return failure_observation(
                    "malformed SPARQL binding value", observed_at
                )
            frozen_row[variable] = MappingProxyType(dict(binding))
        rows.append(MappingProxyType(frozen_row))
    return ExecutionObservation(
        kind="select",
        head_vars=tuple(raw_vars),
        rows=tuple(rows),
        observed_at=observed_at,
    )


def failure_observation(
    error: str, observed_at: str | None = None
) -> ExecutionObservation:
    """Create a normalized failed observation and log its error."""
    logger.warning("Recording failed SPARQL observation: %s", error)
    return ExecutionObservation(
        kind="failure", error=error, observed_at=observed_at or _now()
    )


def count_observation(
    query: str, observation: ExecutionObservation
) -> tuple[int, int, Literal["ok", "failed"]]:
    if observation.kind == "failure":
        return 0, 0, "failed"
    is_ask = bool(re.search(r"\bASK\b", query, re.IGNORECASE))
    if is_ask:
        if observation.kind != "ask":
            return 0, 0, "failed"
        return 1, 1, "ok"
    if observation.kind != "select":
        return 0, 0, "failed"
    row_count = len(observation.rows)
    column_count = (
        len(observation.rows[0]) if observation.rows else len(observation.head_vars)
    )
    return row_count, column_count, "ok"


def execution_cache_identity(query: str, endpoint: SparqlEndpoint) -> str:
    payload = {
        "kind": "execution",
        "schema_version": 1,
        "endpoint": dict(endpoint.identity),
        "query": query,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
