"""Validated benchmark records and deterministic benchmark sampling."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

NormalizationProfile = Literal["standard", "qald9"]

logger = logging.getLogger(__name__)


class BenchmarkValidationError(ValueError):
    """Raised when benchmark records cannot form valid question/query pairs."""


@dataclass(frozen=True)
class QueryRecord:
    """A single natural-language question and its SPARQL query."""

    id: str
    question: str
    sparql: str
    source_line: int


@dataclass(frozen=True)
class SamplingManifest:
    """Reproducibility details for a sampled benchmark."""

    seed: int
    source_size: int
    selected_ids: tuple[str, ...]


@dataclass(frozen=True)
class Benchmark:
    """An immutable, validated collection of NL-to-SPARQL records."""

    records: tuple[QueryRecord, ...]
    name: str
    normalization: NormalizationProfile
    source_path: str | None = None
    source_checksum: str | None = None
    sampling: SamplingManifest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise BenchmarkValidationError("benchmark name must be a nonempty string")
        if self.normalization not in ("standard", "qald9"):
            raise BenchmarkValidationError(
                f"unknown normalization profile: {self.normalization!r}"
            )
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            raise BenchmarkValidationError("benchmark record IDs must be unique")

    @property
    def size(self) -> int:
        return len(self.records)

    @property
    def ordered_ids(self) -> tuple[str, ...]:
        return tuple(record.id for record in self.records)

    @property
    def fingerprint(self) -> str:
        payload = {
            "normalization": self.normalization,
            "records": [
                {
                    "id": record.id,
                    "question": record.question,
                    "sparql": record.sparql,
                    "source_line": record.source_line,
                }
                for record in self.records
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        *,
        name: str,
        question_key: str = "question",
        query_key: str = "sparql",
        id_key: str = "id",
        normalization: str = "auto",
    ) -> Benchmark:
        """Load and validate records from a JSON Lines benchmark file."""
        source = Path(path).expanduser().resolve()
        raw = source.read_bytes()
        records: list[Mapping[str, Any]] = []
        source_lines: list[int] = []
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.error("Malformed benchmark JSON at %s:%s", source, line_number, exc_info=True)
                raise BenchmarkValidationError(
                    f"{source}:{line_number}: malformed JSON: {exc.msg}"
                ) from exc
            if not isinstance(value, Mapping):
                raise BenchmarkValidationError(
                    f"{source}:{line_number}: expected a JSON object"
                )
            records.append(value)
            source_lines.append(line_number)

        profile = _resolve_normalization(normalization, source.name, allow_auto=True)
        return cls._from_records(
            records,
            name=name,
            question_key=question_key,
            query_key=query_key,
            id_key=id_key,
            normalization=profile,
            source_path=str(source),
            source_checksum=hashlib.sha256(raw).hexdigest(),
            source_lines=source_lines,
        )

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        name: str,
        question_key: str = "question",
        query_key: str = "sparql",
        id_key: str = "id",
        normalization: str = "standard",
    ) -> Benchmark:
        """Build a benchmark from in-memory record mappings."""
        profile = _resolve_normalization(normalization, None, allow_auto=False)
        materialized = list(records)
        return cls._from_records(
            materialized,
            name=name,
            question_key=question_key,
            query_key=query_key,
            id_key=id_key,
            normalization=profile,
            source_path=None,
            source_checksum=None,
            source_lines=list(range(1, len(materialized) + 1)),
        )

    @classmethod
    def _from_records(
        cls,
        records: list[Mapping[str, Any]],
        *,
        name: str,
        question_key: str,
        query_key: str,
        id_key: str,
        normalization: NormalizationProfile,
        source_path: str | None,
        source_checksum: str | None,
        source_lines: list[int],
    ) -> Benchmark:
        validated: list[QueryRecord] = []
        seen_ids: set[str] = set()
        source_label = source_path or "<records>"
        for position, (record, source_line) in enumerate(
            zip(records, source_lines, strict=True), start=1
        ):
            if not isinstance(record, Mapping):
                raise BenchmarkValidationError(
                    f"{source_label}:{source_line}: expected a mapping"
                )
            question = _required_text(record, question_key, source_label, source_line)
            sparql = _required_text(record, query_key, source_label, source_line)
            raw_id = record.get(id_key)
            if raw_id is None:
                record_id = f"source-{position}"
            elif not isinstance(raw_id, str) or not raw_id.strip():
                raise BenchmarkValidationError(
                    f"{source_label}:{source_line}: {id_key!r} must be a nonempty string"
                )
            else:
                record_id = raw_id
            if record_id in seen_ids:
                raise BenchmarkValidationError(
                    f"{source_label}:{source_line}: duplicate record ID {record_id!r}"
                )
            seen_ids.add(record_id)
            validated.append(QueryRecord(record_id, question, sparql, source_line))
        return cls(
            records=tuple(validated),
            name=name,
            normalization=normalization,
            source_path=source_path,
            source_checksum=source_checksum,
        )


def balance_benchmarks(
    left: Benchmark, right: Benchmark, *, seed: int = 40
) -> tuple[Benchmark, Benchmark]:
    """Deterministically sample the larger benchmark to equalize both sizes."""
    if left.size == right.size:
        return left, right
    rng = random.Random(seed)
    target_size = min(left.size, right.size)
    if left.size > target_size:
        left = _sample_benchmark(left, target_size, seed, rng)
    else:
        right = _sample_benchmark(right, target_size, seed, rng)
    return left, right


def _sample_benchmark(
    benchmark: Benchmark, size: int, seed: int, rng: random.Random
) -> Benchmark:
    sampled = tuple(rng.sample(benchmark.records, size))
    manifest = SamplingManifest(
        seed=seed,
        source_size=benchmark.size,
        selected_ids=tuple(record.id for record in sampled),
    )
    return replace(benchmark, records=sampled, sampling=manifest)


def _required_text(
    record: Mapping[str, Any], key: str, source: str, source_line: int
) -> str:
    if key not in record:
        raise BenchmarkValidationError(f"{source}:{source_line}: missing field {key!r}")
    value = record[key]
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(
            f"{source}:{source_line}: {key!r} must be a nonempty string"
        )
    return value


def _resolve_normalization(
    normalization: str, basename: str | None, *, allow_auto: bool
) -> NormalizationProfile:
    if normalization == "auto":
        if not allow_auto:
            raise BenchmarkValidationError(
                "in-memory benchmarks require an explicit normalization profile"
            )
        return (
            "qald9"
            if basename and re.search(r"qald[-_]?9", basename, re.IGNORECASE)
            else "standard"
        )
    if normalization not in ("standard", "qald9"):
        raise BenchmarkValidationError(
            f"unknown normalization profile: {normalization!r}"
        )
    return normalization  # type: ignore[return-value]
