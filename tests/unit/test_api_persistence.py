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
