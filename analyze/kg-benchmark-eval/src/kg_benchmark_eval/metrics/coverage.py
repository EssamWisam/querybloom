"""Coverage metric calculations for ontology and query features."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..preprocessing import FEATURE_KEYS


@dataclass(frozen=True)
class CoverageValue:
    ratio: float
    covered: int
    total: int

    @property
    def raw(self) -> str:
        return f"{self.covered}/{self.total}"


def compute_coverage(
    observed: frozenset[str], universe: frozenset[str]
) -> CoverageValue:
    if not universe:
        return CoverageValue(ratio=0.0, covered=len(observed), total=0)
    covered = len(observed & universe)
    return CoverageValue(
        ratio=round(covered / len(universe), 4),
        covered=covered,
        total=len(universe),
    )


def compute_feature_coverage(
    feature_rows: Sequence[Mapping[str, int]],
) -> CoverageValue:
    used = {key for row in feature_rows for key in FEATURE_KEYS if row.get(key, 0)}
    total = len(FEATURE_KEYS)
    return CoverageValue(
        ratio=round(len(used) / total, 4), covered=len(used), total=total
    )
