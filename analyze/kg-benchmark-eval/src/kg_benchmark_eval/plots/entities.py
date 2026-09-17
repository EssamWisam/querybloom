"""Entity overlap visualization for evaluation comparisons."""

from __future__ import annotations

from collections import Counter
from collections.abc import MutableMapping
from typing import Any

import numpy as np

from ..results import ComparisonResult
from .common import COLORS, MissingMetricError, pyplot


def entities(
    comparison: ComparisonResult,
    *,
    top_n: int = 20,
    metadata: MutableMapping[str, object] | None = None,
) -> Any:
    datasets = []
    for result in (comparison.left, comparison.right):
        if any(query.terms is None for query in result.queries):
            raise MissingMetricError(
                "missing required metrics: diversity.structural.distinct_entities_per_query"
            )
        per_query = [
            frozenset(query.terms.entities) for query in result.queries if query.terms
        ]
        frequencies = Counter(entity for values in per_query for entity in values)
        datasets.append((result, per_query, frequencies))
    plt = pyplot()
    figure, axes = plt.subplots(1, 2, figsize=(15, 6))
    for (result, per_query, frequencies), color in zip(datasets, COLORS):
        axes[0].hist(
            [len(values) for values in per_query],
            bins=np.arange(-0.5, max((len(values) for values in per_query), default=0) + 1.5),
            alpha=0.55,
            color=color,
            label=result.benchmark.name,
            edgecolor="white",
        )
    axes[0].set_title("Distinct resolved entities per query")
    axes[0].set_xlabel("Entities per query")
    axes[0].set_ylabel("Queries")
    axes[0].legend()
    labels = sorted(
        set(datasets[0][2]) | set(datasets[1][2]),
        key=lambda key: -(datasets[0][2][key] + datasets[1][2][key]),
    )[:top_n]
    positions = np.arange(len(labels))
    left_entities = set(datasets[0][2])
    right_entities = set(datasets[1][2])
    shared = left_entities & right_entities
    left_values = np.asarray([datasets[0][2][key] for key in labels])
    right_values = np.asarray([datasets[1][2][key] for key in labels])
    axes[1].barh(positions, left_values, color=COLORS[0], alpha=0.82, label=datasets[0][0].benchmark.name)
    axes[1].barh(positions, -right_values, color=COLORS[1], alpha=0.82, label=datasets[1][0].benchmark.name)
    for position, key in zip(positions, labels):
        if key in shared:
            axes[1].plot(0, position, marker="D", color="#F2C14E", markersize=5, zorder=4)
    axes[1].axvline(0, color="#333333", linewidth=0.8)
    axes[1].set_yticks(positions, [_short_label(label) for label in labels])
    axes[1].xaxis.set_major_formatter(
        __import__("matplotlib.ticker", fromlist=["FuncFormatter"]).FuncFormatter(
            lambda value, _: f"{abs(value):.0f}"
        )
    )
    axes[1].set_xlabel("Query occurrences")
    axes[1].set_title("Top entities: shared and exclusive")
    axes[1].legend(loc="upper right")
    figure.suptitle("Entity diversity", fontsize=15, fontweight="bold")
    figure.tight_layout()
    if metadata is not None:
        metadata.update({"function": "entities", "top_n": top_n})
    return figure


def _short_label(value: str) -> str:
    return value.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
