"""Semantic and structural diversity comparison plots."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, MutableMapping
from importlib import import_module
from typing import Any

import numpy as np
import numpy.typing as npt

from ..preprocessing import FEATURE_KEYS
from ..results import ComparisonResult, EvaluationResult
from .common import COLORS, MissingMetricError, pyplot, require

logger = logging.getLogger(__name__)


def semantic_space(
    comparison: ComparisonResult,
    *,
    trim_outlier_pct: float = 5.0,
    seed: int = 42,
    metadata: MutableMapping[str, object] | None = None,
) -> Any:
    """Render two t-SNE projections of retained question embeddings."""
    left = comparison.left.diversity.semantic
    right = comparison.right.diversity.semantic
    require(
        (("diversity.semantic (left)", left), ("diversity.semantic (right)", right))
    )
    assert left is not None and right is not None
    left_kept, left_ids = _trim(
        left.embeddings, trim_outlier_pct, comparison.left.benchmark.ordered_ids
    )
    right_kept, right_ids = _trim(
        right.embeddings, trim_outlier_pct, comparison.right.benchmark.ordered_ids
    )
    if (
        len(left_kept) == 0
        or len(right_kept) == 0
        or len(left_kept) + len(right_kept) < 2
    ):
        raise MissingMetricError(
            "semantic_space requires at least two retained points and both groups"
        )
    try:
        manifold = import_module("sklearn.manifold")
    except ImportError as exc:
        raise ImportError(
            "semantic plotting requires kg-benchmark-eval[plots]"
        ) from exc
    combined = np.vstack((left_kept, right_kept))
    perplexity = min(30, len(combined) - 1)
    coordinates = manifold.TSNE(
        n_components=2,
        random_state=seed,
        perplexity=perplexity,
        init="random",
        learning_rate="auto",
    ).fit_transform(combined)
    plt = pyplot()
    with plt.rc_context({"axes.spines.top": False, "axes.spines.right": False}):
        figure, axes = plt.subplots(1, 2, figsize=(14, 6), sharex=True, sharey=True)
        split = len(left_kept)
        for axis, points, result, semantic, color in (
            (axes[0], coordinates[:split], comparison.left, left, COLORS[0]),
            (axes[1], coordinates[split:], comparison.right, right, COLORS[1]),
        ):
            axis.scatter(
                points[:, 0],
                points[:, 1],
                color=color,
                alpha=0.75,
                edgecolor="white",
                linewidth=0.45,
                s=48,
            )
            axis.set_title(
                f"{result.benchmark.name}\nAPD {semantic.apd:.4g} | Vendi {semantic.vendi:.4g}"
            )
            axis.set_xlabel("t-SNE dimension 1")
        axes[0].set_ylabel("t-SNE dimension 2")
        figure.suptitle("Semantic diversity", fontweight="bold")
        figure.tight_layout()
    if metadata is not None:
        metadata.update(
            {
                "function": "semantic_space",
                "seed": seed,
                "trim_outlier_pct": trim_outlier_pct,
                "retained_ids": {"left": left_ids, "right": right_ids},
                "coordinates": coordinates.tolist(),
                "perplexity": perplexity,
            }
        )
    return figure


def structural_diversity(
    comparison: ComparisonResult,
    *,
    complexity: str = "histogram",
    redundancy_hatching: bool = True,
    debug: bool = False,
    metadata: MutableMapping[str, object] | None = None,
) -> Any:
    """Render diversity summaries, complexity distributions, and feature usage."""
    if complexity not in {"histogram", "kde"}:
        raise ValueError("complexity must be 'histogram' or 'kde'")
    left = comparison.left
    right = comparison.right
    require(
        (
            (
                "diversity.structural.feature_usage_pct",
                left.diversity.structural.feature_usage_pct,
            ),
            (
                "diversity.structural.feature_usage_pct",
                right.diversity.structural.feature_usage_pct,
            ),
            ("complexity.operator_counts", left.complexity.operator_counts),
            ("complexity.operator_counts", right.complexity.operator_counts),
        )
    )
    left_usage = left.diversity.structural.feature_usage_pct or {}
    right_usage = right.diversity.structural.feature_usage_pct or {}
    repetitions = _novelty_repetitions(left, right) if debug else None
    if repetitions is not None:
        print(_format_novelty_repetitions(repetitions))
    features = [
        feature
        for feature in FEATURE_KEYS
        if feature not in {"COUNT", "DISTINCT", "EXISTS"}
        and max(left_usage.get(feature, 0), right_usage.get(feature, 0)) >= 5
    ]
    plt = pyplot()
    with plt.rc_context({"axes.spines.top": False, "axes.spines.right": False}):
        figure = plt.figure(figsize=(21, 6))
        grid = figure.add_gridspec(1, 3, width_ratios=(3.1, 3.0, 3.2), wspace=0.28)
        radar_axis = figure.add_subplot(grid[0], projection="polar")
        complexity_axis = figure.add_subplot(grid[1])
        feature_axis = figure.add_subplot(grid[2])
        _summary_radar(radar_axis, left, right)
        _complexity_panel(complexity_axis, left, right, complexity)
        positions = np.arange(len(features))
        for result, usage, color, sign in (
            (left, left_usage, COLORS[0], 1),
            (right, right_usage, COLORS[1], -1),
        ):
            values = np.asarray([usage.get(key, 0) for key in features])
            fractions = np.asarray(
                [_redundancy_fraction(result, key) for key in features]
            ) if redundancy_hatching else np.zeros(len(features))
            solid = values * (1 - fractions)
            redundant = values * fractions
            feature_axis.bar(
                positions, sign * solid, 0.58, color=color, alpha=0.85,
                edgecolor="white", linewidth=0.5,
            )
            feature_axis.bar(
                positions, sign * redundant, 0.58, bottom=sign * solid,
                color=color, alpha=0.85, edgecolor="white", linewidth=0.5,
                hatch="///",
            )
        feature_axis.axhline(0, color="#333333", linewidth=0.8)
        feature_axis.set_xticks(positions, features, rotation=45, ha="right")
        feature_axis.set_ylabel("Queries (%)")
        feature_axis.set_title("(c) Feature coverage")
        feature_axis.yaxis.set_major_formatter(
            import_module("matplotlib.ticker").FuncFormatter(lambda value, _: f"{abs(value):.0f}")
        )
        handles = [
            import_module("matplotlib.patches").Patch(color=color, label=result.benchmark.name)
            for result, color in ((left, COLORS[0]), (right, COLORS[1]))
        ]
        if redundancy_hatching and (left.redundancy or right.redundancy):
            handles.append(
                import_module("matplotlib.patches").Patch(
                    facecolor="white", edgecolor="#555555", hatch="///",
                    label="Redundant portion",
                )
            )
        figure.legend(handles=handles, loc="lower center", ncol=len(handles), frameon=False)
        figure.subplots_adjust(bottom=0.2)
    if metadata is not None:
        metadata.update(
            {
                "function": "structural_diversity",
                "complexity": complexity,
                "redundancy_hatching": redundancy_hatching,
                "repetitions": repetitions,
            }
        )
    return figure


def _trim(
    matrix: npt.NDArray[np.floating[Any]],
    percentage: float,
    ids: tuple[str, ...],
) -> tuple[npt.NDArray[np.floating[Any]], list[str]]:
    if len(matrix) == 0 or percentage <= 0:
        return matrix, list(ids)
    distances = np.linalg.norm(matrix - matrix.mean(axis=0), axis=1)
    threshold = np.percentile(distances, 100 - percentage)
    mask = distances <= threshold
    return matrix[mask], [record_id for record_id, keep in zip(ids, mask) if keep]


def _complexity_panel(
    axis: Any, left: EvaluationResult, right: EvaluationResult, mode: str
) -> None:
    distributions = (
        ("Operators", left.complexity.operator_counts, right.complexity.operator_counts),
        ("Output rows", left.complexity.row_counts, right.complexity.row_counts),
        ("Columns", left.complexity.column_counts, right.complexity.column_counts),
    )
    for position, (label, left_values, right_values) in enumerate(distributions):
        if left_values is None or right_values is None:
            logger.warning(
                "Skipping %s complexity distribution because values are unavailable "
                "for one or both benchmarks",
                label.lower(),
            )
            continue
        if mode == "kde":
            _kde_pair(axis, position, left_values, right_values)
        else:
            _split_histogram(axis, position, left_values, right_values)
    axis.set_xticks(range(3), [item[0] for item in distributions])
    axis.set_xlim(-0.65, 2.65)
    axis.set_ylabel("Count per query")
    axis.set_title("(b) Complexity spread")


def _summary_radar(axis: Any, left: EvaluationResult, right: EvaluationResult) -> None:
    left_coverage = left.coverage
    right_coverage = right.coverage
    use_breadth = (
        left_coverage.properties is not None
        and right_coverage.properties is not None
        and left_coverage.properties.ratio < 0.10
        and right_coverage.properties.ratio < 0.10
    )
    labels = (
        "Template\nratio", "Entity\nbreadth", "Feature\nentropy",
        "Class\n" + ("breadth" if use_breadth else "coverage"),
        "Property\n" + ("breadth" if use_breadth else "coverage"),
        "Class\nevenness", "Property\nevenness", "Entity\nevenness",
    )
    values = [_summary_values(result, use_breadth) for result in (left, right)]
    scales = [max(pair[0], pair[1], 1e-9) for pair in zip(*values)]
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)
    axis.set_theta_offset(np.pi / 2)
    axis.set_theta_direction(-1)
    for result_values, result, color in zip(values, (left, right), COLORS):
        normalized = [value / scale for value, scale in zip(result_values, scales)]
        axis.plot(np.r_[angles, angles[0]], normalized + normalized[:1], color=color, linewidth=2)
        axis.fill(np.r_[angles, angles[0]], normalized + normalized[:1], color=color, alpha=0.13)
        axis.scatter(angles, normalized, color=color, s=28, zorder=3)
        for angle, radius, raw in zip(angles, normalized, result_values):
            axis.annotate(f"{raw:.2g}", (angle, radius), xytext=(0, 7), textcoords="offset points", ha="center", color=color, fontsize=7)
    axis.set_thetagrids(np.degrees(angles), labels, fontsize=8)
    axis.set_ylim(0, 1.18)
    axis.set_yticklabels([])
    axis.set_title("(a) Diversity & comprehensiveness", pad=22)


def _summary_values(result: EvaluationResult, use_breadth: bool) -> list[float]:
    structural = result.diversity.structural
    class_value = (
        structural.distinct_classes_per_query
        if use_breadth
        else result.coverage.classes.ratio if result.coverage.classes else None
    )
    property_value = (
        structural.distinct_properties_per_query
        if use_breadth
        else result.coverage.properties.ratio if result.coverage.properties else None
    )
    return [
        _metric_or_zero(result, "unique_template_ratio", structural.unique_template_ratio),
        _metric_or_zero(
            result,
            "distinct_entities_per_query",
            structural.distinct_entities_per_query,
        ),
        _metric_or_zero(result, "feature_entropy_bits", structural.feature_entropy_bits),
        _metric_or_zero(result, "class_breadth" if use_breadth else "coverage.classes.ratio", class_value),
        _metric_or_zero(result, "property_breadth" if use_breadth else "coverage.properties.ratio", property_value),
        _metric_or_zero(result, "class_evenness", structural.class_evenness),
        _metric_or_zero(result, "property_evenness", structural.property_evenness),
        _metric_or_zero(result, "entity_evenness", structural.entity_evenness),
    ]


def _novelty_repetitions(
    left: EvaluationResult, right: EvaluationResult
) -> dict[str, dict[str, dict[str, int]]]:
    """Return terms repeated across queries, counted once in each query."""
    return {
        result.benchmark.name: {
            "classes": _repeated_terms(
                query.terms.classes
                for query in result.queries
                if query.terms is not None
            ),
            "properties": _repeated_terms(
                query.parsed.properties
                for query in result.queries
                if query.parsed is not None
            ),
            "entities": _repeated_terms(
                query.terms.entities
                for query in result.queries
                if query.terms is not None
            ),
        }
        for result in (left, right)
    }


def _format_novelty_repetitions(
    repetitions: dict[str, dict[str, dict[str, int]]]
) -> str:
    """Format the novelty debug report one benchmark and term type per line."""
    lines: list[str] = []
    for benchmark, categories in repetitions.items():
        lines.append(f"{benchmark}:")
        for category, terms in categories.items():
            lines.append(f"  {category}:")
            lines.extend(
                f"    {term}: {count}" for term, count in terms.items()
            )
            if not terms:
                lines.append("    (none)")
    return "\n".join(lines)


def _repeated_terms(term_sets: Iterable[Iterable[str]]) -> dict[str, int]:
    counts = Counter(term for terms in term_sets for term in set(terms))
    return {term: counts[term] for term in sorted(counts) if counts[term] > 1}


def _metric_or_zero(
    result: EvaluationResult, metric_name: str, value: float | None
) -> float:
    if value is not None:
        return value
    logger.warning(
        "Using 0.0 for unavailable %s metric in benchmark %r",
        metric_name,
        result.benchmark.name,
    )
    return 0.0


def _redundancy_fraction(result: EvaluationResult, feature: str) -> float:
    if result.redundancy is None or feature not in result.redundancy.features:
        return 0.0
    return result.redundancy.features[feature].rate_pct / 100.0


def _split_histogram(axis: Any, position: int, left: npt.ArrayLike, right: npt.ArrayLike) -> None:
    for values, side, color in ((left, -1, COLORS[0]), (right, 1, COLORS[1])):
        array = np.asarray(values, dtype=float)
        if len(array) == 0:
            continue
        cap = 10
        counts, edges = np.histogram(np.clip(array, 0, cap), bins=np.arange(-0.5, cap + 1.5))
        widths = counts / max(counts.max(), 1) * 0.42
        axis.barh(edges[:-1] + 0.5, side * widths, left=position, height=0.82, color=color, alpha=0.72)
        axis.plot(position, np.median(array), "o", color="white", markeredgecolor="#333333", markersize=6, zorder=4)
    axis.set_ylim(-0.5, 10.5)
    axis.set_yticks((0, 2, 4, 6, 8, 10), ("0", "2", "4", "6", "8", "10+"))


def _kde_pair(axis: Any, position: int, left: npt.ArrayLike, right: npt.ArrayLike) -> None:
    try:
        gaussian_kde = import_module("scipy.stats").gaussian_kde
    except ImportError as exc:
        raise ImportError("KDE plotting requires kg-benchmark-eval[plots]") from exc
    for values, side, color in ((left, -1, COLORS[0]), (right, 1, COLORS[1])):
        array = np.asarray(values, dtype=float)
        if len(array) < 2 or np.std(array) == 0:
            continue
        domain = np.linspace(0, max(10, np.percentile(array, 95)), 200)
        density = gaussian_kde(array)(domain)
        width = density / max(density.max(), 1e-9) * 0.42
        axis.plot(position + side * width, domain, color=color, linewidth=1.5)
        axis.fill_betweenx(domain, position, position + side * width, color=color, alpha=0.2)
