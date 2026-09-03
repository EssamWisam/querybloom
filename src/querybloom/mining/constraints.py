"""Shared structural constraints for mined subgraph queries."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def parallel_edge_pairs(
    edges: Sequence[Mapping[str, Any]],
) -> list[tuple[int, int]]:
    """Return edge pairs that must use distinct targets."""
    pairs: list[tuple[int, int]] = []
    for right_index, right in enumerate(edges):
        for left_index, left in enumerate(edges[:right_index]):
            if (
                left.get("s") == right.get("s")
                and left.get("p") == right.get("p")
                and left.get("o") != right.get("o")
            ):
                pairs.append((left_index, right_index))
    return pairs