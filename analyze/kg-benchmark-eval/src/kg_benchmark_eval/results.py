"""Immutable result models and portable result-table conversions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, TypeVar, cast

import numpy as np
import numpy.typing as npt

from .benchmark import Benchmark, QueryRecord
from .encoders import EncoderIdentity
from .metrics.coverage import CoverageValue
from .preprocessing import ParsedQuery
from .resolution import ResolvedTerms

MetricStatus = Literal["ok", "not_requested", "disabled", "undefined", "degraded"]


@dataclass(frozen=True)
class Diagnostic:
    """A recoverable evaluation problem and its fallback contribution."""

    code: str
    stage: str
    message: str
    query_id: str | None = None
    source: str | None = None
    source_line: int | None = None
    evaluation_index: int | None = None
    endpoint_identity: Mapping[str, object] | None = None
    fallback_contribution: str | None = None


@dataclass(frozen=True)
class QueryAnalysis:
    """All derived artifacts for one evaluated benchmark record."""

    record: QueryRecord
    evaluation_index: int
    normalized_sparql: str
    parsed: ParsedQuery | None
    terms: ResolvedTerms | None
    raw_features: Mapping[str, int] | None
    execution_features: Mapping[str, int] | None
    template: str | None
    filter_templates: tuple[str, ...] | None
    filter_subtypes: frozenset[str] | None


@dataclass(frozen=True)
class SemanticDiversity:
    """Embedding-based diversity metrics and their source embeddings."""

    apd: float
    vendi: float
    embeddings: npt.NDArray[np.floating]
    encoder_identity: EncoderIdentity


@dataclass(frozen=True)
class StructuralDiversity:
    """Query-structure diversity metrics and observed entity terms."""

    unique_template_ratio: float | None = None
    distinct_entities_per_query: float | None = None
    filter_template_ratio: float | None = None
    feature_entropy_bits: float | None = None
    feature_usage_pct: Mapping[str, float] | None = None
    filter_subtype_keys: tuple[str, ...] = ()
    distinct_classes_per_query: float | None = None
    distinct_properties_per_query: float | None = None
    class_richness: int | None = None
    property_richness: int | None = None
    entity_richness: int | None = None
    class_mean_per_query: float | None = None
    property_mean_per_query: float | None = None
    entity_mean_per_query: float | None = None
    class_hill_1: float | None = None
    property_hill_1: float | None = None
    entity_hill_1: float | None = None
    class_hill_2: float | None = None
    property_hill_2: float | None = None
    entity_hill_2: float | None = None
    class_evenness: float | None = None
    property_evenness: float | None = None
    entity_evenness: float | None = None
    distinct_entities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DiversityResult:
    """Semantic and structural diversity results."""

    semantic: SemanticDiversity | None
    structural: StructuralDiversity


@dataclass(frozen=True)
class ComplexityResult:
    """Per-query complexity measurements and aggregate variation."""

    operator_counts: npt.NDArray[np.int64] | None = None
    row_counts: npt.NDArray[np.int64] | None = None
    column_counts: npt.NDArray[np.int64] | None = None
    operator_count_std: float | None = None
    row_count_std: float | None = None
    column_count_std: float | None = None
    execution_status: tuple[str, ...] = ()
    observation_ids: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class CoverageResult:
    """Class, property, and feature coverage against their universes."""

    classes: CoverageValue | None = None
    properties: CoverageValue | None = None
    features: CoverageValue | None = None
    class_universe: frozenset[str] = frozenset()
    property_universe: frozenset[str] = frozenset()
    covered_classes: frozenset[str] = frozenset()
    covered_properties: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RedundancyFeatureResult:
    """Redundancy counts and rate for one query feature."""

    rate_pct: float
    feature_present: int
    unchanged_modification: int
    eligible: int
    redundant: int
    failed_pairs: int


@dataclass(frozen=True)
class RedundancyPair:
    """Original and modified executions used for a redundancy check."""

    query_id: str
    feature: str
    original_text: str
    modified_text: str
    original_observation_id: str | None
    modified_observation_id: str | None
    outcome: Literal["redundant", "changed", "failed", "unchanged_modification"]


@dataclass(frozen=True)
class RedundancyResult:
    """Redundancy summaries and individual modified-query outcomes."""

    features: Mapping[str, RedundancyFeatureResult]
    pairs: tuple[RedundancyPair, ...]


@dataclass(frozen=True)
class EvaluationResult:
    """Complete, immutable output from evaluating one benchmark."""

    benchmark: Benchmark
    diversity: DiversityResult
    complexity: ComplexityResult
    coverage: CoverageResult
    redundancy: RedundancyResult | None
    queries: tuple[QueryAnalysis, ...]
    metric_status: Mapping[str, MetricStatus]
    diagnostics: tuple[Diagnostic, ...]
    provenance: Mapping[str, object]

    def compare(self, other: EvaluationResult) -> ComparisonResult:
        """Create a compatible comparison, validating shared dependencies."""
        if (
            (self.coverage.classes is not None or self.coverage.properties is not None)
            and (
                other.coverage.classes is not None
                or other.coverage.properties is not None
            )
            and self.provenance.get("ontology_fingerprint")
            != other.provenance.get("ontology_fingerprint")
        ):
            raise ValueError(
                "coverage comparison requires matching ontology fingerprints"
            )
        left_semantic = self.diversity.semantic
        right_semantic = other.diversity.semantic
        if (
            left_semantic is not None
            and right_semantic is not None
            and left_semantic.encoder_identity != right_semantic.encoder_identity
        ):
            raise ValueError("semantic comparison requires matching encoder identities")
        return ComparisonResult(self, other)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible metric summary."""
        metrics: dict[str, object] = {}
        for metric_id in sorted(self.metric_status):
            value = _metric_value(self, metric_id)
            if isinstance(value, float) and not math.isfinite(value):
                value = None
            elif isinstance(value, np.ndarray):
                value = value.tolist()
            elif isinstance(value, CoverageValue):
                value = {
                    "ratio": value.ratio,
                    "covered": value.covered,
                    "total": value.total,
                    "raw": value.raw,
                }
            else:
                value = _json_value(value)
            metrics[metric_id] = {
                "value": value,
                "status": self.metric_status[metric_id],
            }
        return {
            "benchmark": {
                "name": self.benchmark.name,
                "size": self.benchmark.size,
                "fingerprint": self.benchmark.fingerprint,
                "ordered_ids": list(self.benchmark.ordered_ids),
            },
            "metrics": metrics,
            "provenance": _json_value(self.provenance),
        }

    def save_bundle(self, directory: str | Path, *, overwrite: bool = False) -> None:
        """Persist this result in the portable evaluation-bundle format."""
        from .serialization import save_bundle

        save_bundle(self, Path(directory), overwrite=overwrite)

    @classmethod
    def load_bundle(cls, directory: str | Path) -> EvaluationResult:
        """Load an evaluation result from a portable bundle directory."""
        from .serialization import load_bundle

        return load_bundle(Path(directory))

    def to_dataframe(self) -> Any:
        """Return metric values and statuses as a pandas DataFrame."""
        try:
            pd = import_module("pandas")
        except ImportError as exc:
            raise ImportError(
                "table export requires kg-benchmark-eval[tables]"
            ) from exc
        rows: list[dict[str, object]] = []
        metrics = cast(Mapping[str, Mapping[str, object]], self.to_dict()["metrics"])
        for metric_id, entry in metrics.items():
            rows.append(
                {
                    "benchmark": self.benchmark.name,
                    "metric_id": metric_id,
                    **entry,
                }
            )
        return pd.DataFrame(rows)


@dataclass(frozen=True)
class ComparisonResult:
    """A validated pair of evaluation results for comparison plots and tables."""

    left: EvaluationResult
    right: EvaluationResult

    def to_dataframe(self) -> Any:
        """Return the two results' metrics in one pandas DataFrame."""
        try:
            pd = import_module("pandas")
        except ImportError as exc:
            raise ImportError(
                "table export requires kg-benchmark-eval[tables]"
            ) from exc
        return pd.concat(
            [self.left.to_dataframe(), self.right.to_dataframe()], ignore_index=True
        )


def immutable_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(values))


ArrayDType = TypeVar("ArrayDType", bound=np.generic)


def readonly_array(values: npt.NDArray[ArrayDType]) -> npt.NDArray[ArrayDType]:
    array = np.asarray(values)
    array.setflags(write=False)
    return array


def _metric_value(result: EvaluationResult, metric_id: str) -> object:
    value: object = result
    for part in metric_id.split("."):
        if part == "features" and isinstance(value, RedundancyResult):
            return {key: feature.rate_pct for key, feature in value.features.items()}
        value = getattr(value, part, None)
        if value is None:
            break
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        values = sorted(value) if isinstance(value, (frozenset, set)) else value
        return [_json_value(item) for item in values]
    if isinstance(value, np.generic):
        return value.item()
    return value
