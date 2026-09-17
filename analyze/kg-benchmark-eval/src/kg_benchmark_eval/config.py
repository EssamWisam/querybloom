"""Configuration models for endpoints, caching, and metric selection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

CachePolicy = Literal["use", "refresh", "offline"]

METRIC_IDS = frozenset(
    {
        "diversity.semantic.apd",
        "diversity.semantic.vendi",
        "diversity.structural.unique_template_ratio",
        "diversity.structural.distinct_entities_per_query",
        "diversity.structural.filter_template_ratio",
        "diversity.structural.feature_entropy_bits",
        "diversity.structural.feature_usage_pct",
        "diversity.structural.distinct_classes_per_query",
        "diversity.structural.distinct_properties_per_query",
        "diversity.structural.class_richness",
        "diversity.structural.property_richness",
        "diversity.structural.entity_richness",
        "diversity.structural.class_mean_per_query",
        "diversity.structural.property_mean_per_query",
        "diversity.structural.entity_mean_per_query",
        "diversity.structural.class_hill_1",
        "diversity.structural.property_hill_1",
        "diversity.structural.entity_hill_1",
        "diversity.structural.class_hill_2",
        "diversity.structural.property_hill_2",
        "diversity.structural.entity_hill_2",
        "diversity.structural.class_evenness",
        "diversity.structural.property_evenness",
        "diversity.structural.entity_evenness",
        "complexity.operator_counts",
        "complexity.row_counts",
        "complexity.column_counts",
        "complexity.operator_count_std",
        "complexity.row_count_std",
        "complexity.column_count_std",
        "coverage.classes",
        "coverage.properties",
        "coverage.features",
        "redundancy.features",
    }
)

_STATIC_IDS = frozenset(
    metric
    for metric in METRIC_IDS
    if not metric.startswith("diversity.semantic")
    and not metric.startswith("redundancy")
    and metric
    not in {
        "complexity.row_counts",
        "complexity.column_counts",
        "complexity.row_count_std",
        "complexity.column_count_std",
    }
)


@dataclass(frozen=True)
class SparqlEndpoint:
    """An identifiable SPARQL endpoint and request configuration."""

    url: str
    snapshot_id: str
    default_graphs: tuple[str, ...] = ()
    named_graphs: tuple[str, ...] = ()
    timeout: float = 60.0
    access_scope: str = "public"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("endpoint URL must not contain credentials")
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must be a nonempty string")
        if not self.access_scope.strip():
            raise ValueError("access_scope must be a nonempty string")
        if self.timeout <= 0:
            raise ValueError("endpoint timeout must be positive")

    @property
    def identity(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "url": self.url,
                "snapshot_id": self.snapshot_id,
                "default_graphs": self.default_graphs,
                "named_graphs": self.named_graphs,
                "timeout": self.timeout,
                "access_scope": self.access_scope,
            }
        )


@dataclass(frozen=True)
class CacheConfig:
    """Policy and storage settings for evaluation artifacts."""

    directory: Path
    policy: CachePolicy = "use"
    memory_entries: int = 256

    def __post_init__(self) -> None:
        if self.policy not in {"use", "refresh", "offline"}:
            raise ValueError(f"unknown cache policy: {self.policy!r}")
        if self.memory_entries < 1:
            raise ValueError("memory_entries must be positive")


@dataclass(frozen=True)
class MetricSelection:
    """The exact metric IDs requested for an evaluation."""

    metric_ids: frozenset[str]

    @classmethod
    def only(cls, *names: str) -> MetricSelection:
        """Expand metric names or namespaces into a validated selection."""
        selected: set[str] = set()
        invalid: list[str] = []
        for name in names:
            matches = {
                metric
                for metric in METRIC_IDS
                if metric == name or metric.startswith(name + ".")
            }
            if not matches:
                invalid.append(name)
            selected.update(matches)
        if invalid:
            valid = ", ".join(sorted(METRIC_IDS))
            raise ValueError(
                f"unknown metric selection {invalid!r}; valid metric IDs: {valid}"
            )
        return cls(frozenset(selected))

    @classmethod
    def static(cls) -> MetricSelection:
        """Select metrics that need neither endpoint execution nor embeddings."""
        return cls(_STATIC_IDS)

    @classmethod
    def all(cls) -> MetricSelection:
        """Select every supported metric."""
        return cls(METRIC_IDS)

    def includes(self, name: str) -> bool:
        """Return whether an exact metric ID is selected."""
        return name in self.metric_ids
