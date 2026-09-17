from __future__ import annotations

import httpx
import pytest

from kg_benchmark_eval import SparqlEndpoint
from kg_benchmark_eval.execution import (
    HttpxSparqlTransport,
    count_observation,
    normalize_sparql_results,
)


def test_endpoint_identity_requires_snapshot_and_excludes_credentials():
    endpoint = SparqlEndpoint(
        url="https://example.org/sparql",
        snapshot_id="snapshot-1",
        access_scope="public",
    )

    assert endpoint.identity["snapshot_id"] == "snapshot-1"
    assert endpoint.identity["url"] == "https://example.org/sparql"
    with pytest.raises(ValueError, match="snapshot_id"):
        SparqlEndpoint(url="https://example.org/sparql", snapshot_id="")
    with pytest.raises(ValueError, match="credentials"):
        SparqlEndpoint(url="https://user:secret@example.org/sparql", snapshot_id="x")


def test_normalize_select_retains_binding_metadata_and_empty_head_vars():
    observation = normalize_sparql_results(
        {
            "head": {"vars": ["name", "age"]},
            "results": {
                "bindings": [
                    {
                        "name": {"type": "literal", "value": "Ada", "xml:lang": "en"},
                    }
                ]
            },
        }
    )

    assert observation.kind == "select"
    assert observation.rows[0]["name"]["xml:lang"] == "en"
    assert count_observation("SELECT * WHERE {}", observation) == (1, 1, "ok")

    empty = normalize_sparql_results(
        {"head": {"vars": ["name", "age"]}, "results": {"bindings": []}}
    )
    assert count_observation("SELECT * WHERE {}", empty) == (0, 2, "ok")


def test_successful_ask_false_counts_as_one():
    observation = normalize_sparql_results({"head": {}, "boolean": False})

    assert observation.kind == "ask"
    assert observation.boolean is False
    assert count_observation("ASK { ?s ?p ?o }", observation) == (1, 1, "ok")


def test_malformed_payload_is_a_failure_observation():
    observation = normalize_sparql_results({"head": {}, "results": {"bindings": None}})

    assert observation.kind == "failure"
    assert count_observation("SELECT * WHERE {}", observation) == (0, 0, "failed")


def test_transport_exception_becomes_failure_observation():
    def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    endpoint = SparqlEndpoint(url="https://example.org/sparql", snapshot_id="s1")
    client = httpx.Client(transport=httpx.MockTransport(fail))
    transport = HttpxSparqlTransport(client=client)

    observation = transport.execute("ASK {}", endpoint=endpoint)

    assert observation.kind == "failure"
    assert "timed out" in (observation.error or "")
    transport.close()
