from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from kg_benchmark_eval import CacheConfig
from kg_benchmark_eval.cache import (
    CacheCorruptionError,
    CacheMissError,
    CacheStore,
    embedding_cache_key,
)


def test_embedding_key_preserves_question_order():
    identity = {"model_id": "frozen", "revision": "1"}

    assert embedding_cache_key(("a", "b"), identity) != embedding_cache_key(
        ("b", "a"), identity
    )


def test_json_and_array_round_trip(tmp_path):
    with CacheStore(CacheConfig(tmp_path)) as cache:
        cache.put_json("parsed", "key", {"ok": True, "values": [1, 2]})
        cache.put_array("embeddings", "matrix", np.eye(2, dtype=np.float32))

        assert cache.get_json("parsed", "key") == {"ok": True, "values": [1, 2]}
        matrix = cache.get_array("embeddings", "matrix")
        assert matrix is not None
        np.testing.assert_array_equal(matrix, np.eye(2, dtype=np.float32))
        assert matrix.flags.writeable is False


def test_refresh_bypasses_hits_and_offline_requires_them(tmp_path):
    with CacheStore(CacheConfig(tmp_path)) as cache:
        cache.put_json("kind", "key", {"value": 1})

    with CacheStore(CacheConfig(tmp_path, policy="refresh")) as cache:
        assert cache.get_json("kind", "key") is None

    with CacheStore(CacheConfig(tmp_path, policy="offline")) as cache:
        assert cache.get_json("kind", "key") == {"value": 1}
        with pytest.raises(CacheMissError, match="missing"):
            cache.get_json("kind", "missing")


def test_corrupt_json_is_miss_online_and_error_offline(tmp_path):
    with CacheStore(CacheConfig(tmp_path)) as cache:
        cache.put_json("kind", "key", {"value": 1})

    database = sqlite3.connect(tmp_path / "cache.sqlite3")
    database.execute(
        "UPDATE artifacts SET payload = ? WHERE kind = ? AND key = ?",
        ("not-json", "kind", "key"),
    )
    database.commit()
    database.close()

    with CacheStore(CacheConfig(tmp_path)) as cache:
        assert cache.get_json("kind", "key") is None
    with (
        CacheStore(CacheConfig(tmp_path, policy="offline")) as cache,
        pytest.raises((CacheMissError, CacheCorruptionError)),
    ):
        cache.get_json("kind", "key")
