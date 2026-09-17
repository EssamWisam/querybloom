"""Persistent and in-memory cache support for evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt
from typing_extensions import Self

from .config import CacheConfig

logger = logging.getLogger(__name__)


class CacheMissError(LookupError):
    """Raised when offline mode cannot supply a required artifact."""


class CacheCorruptionError(IOError):
    """Raised when an offline artifact fails integrity validation."""


def embedding_cache_key(
    questions: tuple[str, ...], encoder_identity: Mapping[str, object]
) -> str:
    return artifact_key(
        "embeddings",
        1,
        {"questions": list(questions), "encoder": dict(encoder_identity)},
    )


def artifact_key(kind: str, schema_version: int, values: Mapping[str, object]) -> str:
    payload = {"kind": kind, "schema_version": schema_version, **values}
    encoded = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CacheStore:
    """Store JSON and NumPy artifacts according to a cache policy."""

    def __init__(self, config: CacheConfig) -> None:
        self.config = config
        self.directory = config.directory.expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.array_directory = self.directory / "arrays"
        self.array_directory.mkdir(exist_ok=True)
        self._connection = sqlite3.connect(
            self.directory / "cache.sqlite3", check_same_thread=False
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                kind TEXT NOT NULL,
                key TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                dependencies TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (kind, key)
            )
            """
        )
        self._connection.commit()
        self._memory: OrderedDict[tuple[str, str], object] = OrderedDict()
        self._lock = threading.RLock()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def get_json(self, kind: str, key: str) -> dict[str, object] | None:
        if self.config.policy == "refresh":
            return None
        memory_key = (kind, key)
        with self._lock:
            cached = self._memory_get(memory_key)
            if cached is not None:
                return dict(cast(Mapping[str, object], cached))
            row = self._connection.execute(
                "SELECT payload FROM artifacts WHERE kind = ? AND key = ?",
                (kind, key),
            ).fetchone()
        if row is None:
            self._miss(kind, key)
            return None
        try:
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                raise TypeError("cached JSON payload is not an object")
        except (json.JSONDecodeError, TypeError) as exc:
            if self.config.policy == "offline":
                logger.error("Offline cache JSON artifact %s:%s is corrupt", kind, key, exc_info=True)
                raise CacheCorruptionError(
                    f"corrupt offline cache artifact {kind}:{key}: {exc}"
                ) from exc
            logger.warning("Discarding corrupt cache JSON artifact %s:%s", kind, key, exc_info=True)
            with self._lock:
                self._connection.execute(
                    "DELETE FROM artifacts WHERE kind = ? AND key = ?", (kind, key)
                )
                self._connection.commit()
            return None
        with self._lock:
            self._memory_put(memory_key, payload)
        return dict(payload)

    def put_json(
        self,
        kind: str,
        key: str,
        payload: Mapping[str, object],
        *,
        schema_version: int = 1,
        status: str = "success",
        dependencies: Mapping[str, object] | None = None,
    ) -> None:
        encoded_payload = _canonical_json(dict(payload))
        encoded_dependencies = _canonical_json(dict(dependencies or {}))
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO artifacts
                    (kind, key, schema_version, created_at, status, dependencies, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, key) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    created_at = excluded.created_at,
                    status = excluded.status,
                    dependencies = excluded.dependencies,
                    payload = excluded.payload
                """,
                (
                    kind,
                    key,
                    schema_version,
                    datetime.now(timezone.utc).isoformat(),
                    status,
                    encoded_dependencies,
                    encoded_payload,
                ),
            )
            self._memory_put((kind, key), dict(payload))

    def get_array(self, kind: str, key: str) -> npt.NDArray[np.generic] | None:
        metadata = self.get_json(kind, key)
        if metadata is None:
            return None
        try:
            path = self.directory / str(metadata["path"])
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
                raise ValueError("checksum mismatch")
            matrix = cast(npt.NDArray[np.generic], np.load(path, allow_pickle=False))
            if (
                list(matrix.shape) != metadata["shape"]
                or str(matrix.dtype) != metadata["dtype"]
            ):
                raise ValueError("shape or dtype mismatch")
            matrix.setflags(write=False)
            return matrix
        except (OSError, ValueError, KeyError) as exc:
            if self.config.policy == "offline":
                logger.error("Offline cache array artifact %s:%s is corrupt", kind, key, exc_info=True)
                raise CacheCorruptionError(
                    f"corrupt offline array artifact {kind}:{key}: {exc}"
                ) from exc
            logger.warning("Discarding corrupt cache array artifact %s:%s", kind, key, exc_info=True)
            return None

    def put_array(
        self,
        kind: str,
        key: str,
        array: npt.NDArray[np.generic],
        *,
        dependencies: Mapping[str, object] | None = None,
    ) -> None:
        materialized = np.asarray(array)
        with tempfile.NamedTemporaryFile(
            dir=self.array_directory, suffix=".npy", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            np.save(temporary, materialized, allow_pickle=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            raw = temporary_path.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            destination = self.array_directory / f"{checksum}.npy"
            os.replace(temporary_path, destination)
            self.put_json(
                kind,
                key,
                {
                    "path": str(destination.relative_to(self.directory)),
                    "sha256": checksum,
                    "shape": list(materialized.shape),
                    "dtype": str(materialized.dtype),
                },
                dependencies=dependencies,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

    def _miss(self, kind: str, key: str) -> None:
        if self.config.policy == "offline":
            raise CacheMissError(f"missing offline cache artifact {kind}:{key}")

    def _memory_get(self, key: tuple[str, str]) -> object | None:
        value = self._memory.get(key)
        if value is not None:
            self._memory.move_to_end(key)
        return value

    def _memory_put(self, key: tuple[str, str], value: object) -> None:
        self._memory[key] = value
        self._memory.move_to_end(key)
        while len(self._memory) > self.config.memory_entries:
            self._memory.popitem(last=False)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
