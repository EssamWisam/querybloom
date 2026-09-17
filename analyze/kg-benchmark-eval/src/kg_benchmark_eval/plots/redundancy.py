"""Redundancy rate plots and escaped HTML examples."""

from __future__ import annotations

import html
from collections.abc import Iterable, MutableMapping
from typing import Any

import numpy as np

from ..results import ComparisonResult, EvaluationResult
from .common import COLORS, pyplot, require


def redundancy(
    comparison: ComparisonResult,
    *,
    metadata: MutableMapping[str, object] | None = None,
) -> Any:
    """Render redundancy rates per feature for two evaluated benchmarks."""
    left = comparison.left.redundancy
    right = comparison.right.redundancy
    require((("redundancy.features", left), ("redundancy.features", right)))
    assert left is not None and right is not None
    features = sorted(set(left.features) | set(right.features))
    positions = np.arange(len(features))
    width = 0.38
    plt = pyplot()
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.bar(
        positions - width / 2,
        [left.features[key].rate_pct for key in features],
        width,
        color=COLORS[0],
        label=comparison.left.benchmark.name,
    )
    axis.bar(
        positions + width / 2,
        [right.features[key].rate_pct for key in features],
        width,
        color=COLORS[1],
        label=comparison.right.benchmark.name,
    )
    axis.set_xticks(positions, features)
    axis.set_ylabel("Redundant eligible queries (%)")
    axis.legend()
    figure.tight_layout()
    if metadata is not None:
        metadata.update({"function": "redundancy", "features": features})
    return figure


def redundancy_examples(
    result: EvaluationResult,
    *,
    limit: int = 5,
    exclude: Iterable[str] = ("DISTINCT",),
) -> str:
    """Render a bounded set of redundant-query examples as safe HTML."""
    require((("redundancy.features", result.redundancy),))
    assert result.redundancy is not None
    excluded = set(exclude)
    questions = {query.record.id: query.record.question for query in result.queries}
    rows = []
    for pair in result.redundancy.pairs:
        if pair.feature in excluded or pair.outcome != "redundant":
            continue
        rows.append(
            "<article>"
            f"<h3>{html.escape(pair.feature)}: {html.escape(questions[pair.query_id])}</h3>"
            f"<pre>{html.escape(pair.original_text)}</pre>"
            f"<pre>{html.escape(pair.modified_text)}</pre>"
            "</article>"
        )
        if len(rows) == limit:
            break
    return '<section class="kg-benchmark-redundancy">' + "".join(rows) + "</section>"
