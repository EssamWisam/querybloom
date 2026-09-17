"""Coverage-gap and comprehensiveness comparison plots."""

from __future__ import annotations

import logging
import random
from collections.abc import MutableMapping, Sequence
from typing import Any

import numpy as np

from ..results import ComparisonResult
from .common import COLORS, pyplot, require

logger = logging.getLogger(__name__)


def coverage_gaps(
    comparison: ComparisonResult,
    *,
    sample_size: int = 8,
    seed: int = 42,
    metadata: MutableMapping[str, object] | None = None,
) -> Any:
    """Render sampled class and property coverage gaps for two results."""
    left = comparison.left.coverage
    right = comparison.right.coverage
    require(
        (
            ("coverage.classes", left.classes),
            ("coverage.classes", right.classes),
            ("coverage.properties", left.properties),
            ("coverage.properties", right.properties),
        )
    )
    rng = random.Random(seed)
    class_columns = _gap_columns(
        left.covered_classes,
        right.covered_classes,
        left.class_universe,
        sample_size,
        rng,
    )
    property_columns = _gap_columns(
        left.covered_properties,
        right.covered_properties,
        left.property_universe,
        sample_size,
        rng,
    )
    plt = pyplot()
    with plt.rc_context({"axes.spines.top": False, "axes.spines.right": False}):
        figure, axes = plt.subplots(2, 1, figsize=(14, 7))
        for axis, title, columns in (
            (axes[0], "Class coverage gaps", class_columns),
            (axes[1], "Property coverage gaps", property_columns),
        ):
            axis.axis("off")
            rows = max((len(values) for values in columns), default=0)
            padded = [
                [_short_label(value) for value in values] + [""] * (rows - len(values))
                for values in columns
            ]
            table = axis.table(
                cellText=list(zip(*padded)) if rows else [["", "", ""]],
                colLabels=(
                    f"Only {comparison.left.benchmark.name} ({len(columns[0])})",
                    f"Only {comparison.right.benchmark.name} ({len(columns[1])})",
                    f"In neither ({len(columns[2])})",
                ),
                loc="center",
                cellLoc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 1.4)
            for column, color in enumerate((COLORS[0], COLORS[1], "#6B7280")):
                table[0, column].set_facecolor(color)
                table[0, column].set_text_props(color="white", fontweight="bold")
            for row in range(1, max(rows, 1) + 1):
                for column in range(3):
                    cell = table[row, column]
                    cell.set_facecolor("#F3F4F6" if row % 2 == 0 else "white")
                    cell.set_edgecolor("#D1D5DB")
            axis.set_title(title, fontweight="bold", pad=12)
        figure.suptitle("Coverage gaps", fontsize=15, fontweight="bold")
        figure.tight_layout(rect=(0, 0, 1, 0.96))
    if metadata is not None:
        metadata.update(
            {"function": "coverage_gaps", "seed": seed, "sample_size": sample_size}
        )
    return figure


def comprehensiveness(
    comparison: ComparisonResult,
    *,
    metadata: MutableMapping[str, object] | None = None,
) -> Any:
    """Render coverage ratios or structural breadth when coverage is sparse."""
    left = comparison.left.coverage
    right = comparison.right.coverage
    require(
        (
            ("coverage.classes", left.classes),
            ("coverage.classes", right.classes),
            ("coverage.properties", left.properties),
            ("coverage.properties", right.properties),
            ("coverage.features", left.features),
            ("coverage.features", right.features),
        )
    )
    assert left.classes and left.properties and left.features
    assert right.classes and right.properties and right.features
    low_coverage = left.properties.ratio < 0.10 and right.properties.ratio < 0.10
    if low_coverage:
        require(
            (
                (
                    "diversity.structural.distinct_classes_per_query (left)",
                    comparison.left.diversity.structural.distinct_classes_per_query,
                ),
                (
                    "diversity.structural.distinct_classes_per_query (right)",
                    comparison.right.diversity.structural.distinct_classes_per_query,
                ),
                (
                    "diversity.structural.distinct_properties_per_query (left)",
                    comparison.left.diversity.structural.distinct_properties_per_query,
                ),
                (
                    "diversity.structural.distinct_properties_per_query (right)",
                    comparison.right.diversity.structural.distinct_properties_per_query,
                ),
            )
        )
        logger.info(
            "Using structural breadth metrics for comprehensiveness plot because "
            "both property coverage ratios are below 0.10"
        )
        labels = ("Class breadth", "Property breadth", "Feature coverage")
        left_values = [
            comparison.left.diversity.structural.distinct_classes_per_query,
            comparison.left.diversity.structural.distinct_properties_per_query,
            left.features.ratio,
        ]
        right_values = [
            comparison.right.diversity.structural.distinct_classes_per_query,
            comparison.right.diversity.structural.distinct_properties_per_query,
            right.features.ratio,
        ]
        scales = [max(a, b, 1e-9) for a, b in zip(left_values, right_values)]
    else:
        labels = ("Class coverage", "Property coverage", "Feature coverage")
        left_values = [left.classes.ratio, left.properties.ratio, left.features.ratio]
        right_values = [
            right.classes.ratio,
            right.properties.ratio,
            right.features.ratio,
        ]
        scales = [1.0, 1.0, 1.0]
    figure = _radar(comparison, labels, left_values, right_values, scales)
    if metadata is not None:
        metadata.update(
            {
                "function": "comprehensiveness",
                "mode": "breadth" if low_coverage else "coverage",
                "scales": scales,
            }
        )
    return figure


def _gap_columns(
    left: frozenset[str],
    right: frozenset[str],
    universe: frozenset[str],
    sample_size: int,
    rng: random.Random,
) -> list[list[str]]:
    groups = (left - right, right - left, universe - (left | right))
    result = []
    for group in groups:
        population = sorted(group)
        if len(population) > sample_size:
            population = rng.sample(population, sample_size)
        result.append(population)
    return result


def _short_label(value: str) -> str:
    return value.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _radar(
    comparison: ComparisonResult,
    labels: Sequence[str],
    left_values: Sequence[float],
    right_values: Sequence[float],
    scales: Sequence[float],
) -> Any:
    plt = pyplot()
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles += angles[:1]
    figure, axis = plt.subplots(figsize=(6, 6), subplot_kw={"polar": True})
    for values, result, color in (
        (left_values, comparison.left, COLORS[0]),
        (right_values, comparison.right, COLORS[1]),
    ):
        normalized = [value / scale for value, scale in zip(values, scales)]
        normalized += normalized[:1]
        axis.plot(angles, normalized, color=color, label=result.benchmark.name)
        axis.fill(angles, normalized, color=color, alpha=0.12)
    axis.set_xticks(angles[:-1], labels)
    axis.set_ylim(0, 1)
    axis.legend(loc="upper right")
    figure.tight_layout()
    return figure
