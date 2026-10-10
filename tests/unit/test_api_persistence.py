import logging

import pytest
from fastapi import HTTPException

from querybloom.api import router
from querybloom.api.supabase import SupabaseClient, SupabasePersistenceIdentity, SupabaseSettings
from querybloom.events import PipelineEvent


SERVICE_KEY = "server-only-service-key"
IDENTITY = SupabasePersistenceIdentity(owner_id="owner-123", access_token=SERVICE_KEY)


def test_persistence_identity_requires_service_role_key():
    client = SupabaseClient(
        SupabaseSettings(url="https://example.supabase.co", anon_key="anon", service_role_key="")
    )

    with pytest.raises(HTTPException) as exc_info:
        client.persistence_identity("owner-123")

    assert exc_info.value.status_code == 503


def test_service_role_is_used_for_apikey_and_authorization_headers():
    client = SupabaseClient(
        SupabaseSettings(
            url="https://example.supabase.co",
            anon_key="anon",
            service_role_key=SERVICE_KEY,
        )
    )

    headers = client._headers(access_token=SERVICE_KEY)

    assert headers["apikey"] == SERVICE_KEY
    assert headers["Authorization"] == f"Bearer {SERVICE_KEY}"


def test_subgraph_persistence_retries_401_and_keeps_owner(monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []

        def rest_insert(self, access_token, table, payload):
            self.calls.append((access_token, table, payload))
            if len(self.calls) < 3:
                raise HTTPException(status_code=401, detail="expired")
            return [{"id": "subgraph-1"}]

    client = Client()
    delays = []
    monkeypatch.setattr(router.time, "sleep", delays.append)

    succeeded = router._persist_subgraph_best_effort(
        client, IDENTITY, "run-123", 7, {"support": 4, "types": ["A", "B"]}
    )

    assert succeeded is True
    assert len(client.calls) == 3
    assert delays == [0.25, 0.5]
    assert all(call[0] == SERVICE_KEY for call in client.calls)
    assert client.calls[-1][2]["owner_id"] == "owner-123"


def test_failed_subgraph_is_logged_and_not_marked_persisted(monkeypatch, caplog):
    class Client:
        def __init__(self):
            self.calls = 0

        def rest_insert(self, access_token, table, payload):
            self.calls += 1
            raise HTTPException(status_code=401, detail="expired")

    client = Client()
    monkeypatch.setattr(router.time, "sleep", lambda _delay: None)
    sink = router._sample_event_sink(client, IDENTITY, "run-456")
    event = PipelineEvent(
        type="subgraph.discovered",
        stage="mining",
        data={"index": 2, "subgraph": {"support": 1}},
    )

    with caplog.at_level(logging.ERROR, logger=router.__name__):
        sink(event)

    assert client.calls == 3
    assert sink.persisted_subgraphs == set()
    assert "operation=insert" in caplog.text
    assert "run_id=run-456" in caplog.text
    assert "table=subgraphs" in caplog.text
    assert "status=401" in caplog.text
    assert SERVICE_KEY not in caplog.text


def test_meaningless_qa_result_is_persisted_without_qa_pair_rows():
    class Client:
        def __init__(self):
            self.updates = []
            self.inserts = []

        def rest_select(self, _access_token, _table, _params):
            return []

        def rest_update(self, access_token, table, filters, payload):
            self.updates.append((access_token, table, filters, payload))
            return [{"id": "subgraph-1"}]

        def rest_insert(self, access_token, table, payload):
            self.inserts.append((access_token, table, payload))
            return []

    client = Client()
    result = {
        "is_meaningful": False,
        "skip_reason": "No useful domain question can be generated.",
        "qa_pairs": [],
        "cost_usd": 0.002,
        "llm_usage": {"total_tokens": 42},
    }

    router._persist_qa_pairs_for_subgraph_best_effort(
        client,
        IDENTITY,
        "sample-run-1",
        3,
        result,
        "llm-run-1",
        router.LLMRunRequest(endpoint="https://example.test/sparql"),
        {
            3: {
                "id": "subgraph-1",
                "payload": {"support": 7, "types": ["Example"]},
            }
        },
    )

    assert client.inserts == []
    qa_result = {
        "status": "completed",
        "is_meaningful": False,
        "skip_reason": "No useful domain question can be generated.",
        "cost_usd": 0.002,
        "llm_usage": {"total_tokens": 42},
        "llm_run_id": "llm-run-1",
    }
    assert client.updates == [
        (
            SERVICE_KEY,
            "subgraphs",
            {"id": "eq.subgraph-1"},
            {
                "payload": {
                    "support": 7,
                    "types": ["Example"],
                    "qa_result": qa_result,
                    "qa_results_by_model": {"openai/gpt-5.4": qa_result},
                }
            },
        )
    ]


def test_generation_replaces_only_the_same_model():
    class Client:
        def __init__(self):
            self.updated_ids = []

        def rest_select(self, _access_token, _table, _params):
            return [
                {"id": "same", "metadata": {"model": "openai/gpt-5.4", "active": True}},
                {"id": "other", "metadata": {"model": "openrouter/x/y", "active": True}},
                {"id": "legacy", "metadata": {"active": True}},
                {"id": "old", "metadata": {"model": "openai/gpt-5.4", "active": False}},
            ]

        def rest_update(self, _access_token, _table, filters, _payload):
            self.updated_ids.append(filters["id"])
            return []

    client = Client()
    router._soft_delete_qa_pairs_for_subgraph(
        client, IDENTITY, "sample-run-1", "subgraph-1", "llm-run-2", "openai/gpt-5.4"
    )

    assert client.updated_ids == ["eq.same"]


def test_generation_with_new_model_keeps_existing_model_results():
    class Client:
        def __init__(self):
            self.updates = []

        def rest_select(self, _access_token, _table, _params):
            return []

        def rest_update(self, _access_token, table, _filters, payload):
            self.updates.append((table, payload))
            return []

        def rest_insert(self, _access_token, _table, _payload):
            return []

    existing_gpt_result = {"status": "completed", "is_meaningful": True, "llm_run_id": "llm-old"}
    client = Client()
    router._persist_qa_pairs_for_subgraph_best_effort(
        client,
        IDENTITY,
        "sample-run-1",
        3,
        {"is_meaningful": True, "qa_pairs": []},
        "llm-run-2",
        router.LLMRunRequest(endpoint="https://example.test/sparql", model="openrouter/x/y"),
        {
            3: {
                "id": "subgraph-1",
                "payload": {
                    "qa_results_by_model": {"openai/gpt-5.4": existing_gpt_result},
                    "qa_result": existing_gpt_result,
                },
            }
        },
    )

    _table, payload = client.updates[0]
    assert payload["payload"]["qa_results_by_model"]["openai/gpt-5.4"] == existing_gpt_result
    assert payload["payload"]["qa_results_by_model"]["openrouter/x/y"]["llm_run_id"] == "llm-run-2"


def test_generation_keeps_legacy_qa_result_as_its_own_model():
    class Client:
        def __init__(self):
            self.updates = []

        def rest_select(self, _access_token, _table, _params):
            return []

        def rest_update(self, _access_token, table, _filters, payload):
            self.updates.append((table, payload))
            return []

        def rest_insert(self, _access_token, _table, _payload):
            return []

    legacy_result = {"status": "completed", "is_meaningful": True, "llm_run_id": "llm-old"}
    client = Client()
    router._persist_qa_pairs_for_subgraph_best_effort(
        client,
        IDENTITY,
        "sample-run-1",
        3,
        {"is_meaningful": True, "qa_pairs": []},
        "llm-run-2",
        router.LLMRunRequest(endpoint="https://example.test/sparql", model="openrouter/x/y"),
        {3: {"id": "subgraph-1", "payload": {"qa_result": legacy_result}}},
    )

    _table, payload = client.updates[0]
    assert payload["payload"]["qa_results_by_model"][""] == legacy_result
    assert payload["payload"]["qa_results_by_model"]["openrouter/x/y"]["llm_run_id"] == "llm-run-2"
