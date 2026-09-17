"""Semantic and structural diversity metric calculations."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from ..preprocessing import FEATURE_KEYS


def embedding_diversity(embeddings: npt.NDArray[np.floating]) -> tuple[float, float]:
    if embeddings.ndim != 2:
        raise ValueError("embeddings must be a two-dimensional matrix")
    if not np.isfinite(embeddings).all():
        raise ValueError("embeddings must contain only finite values")
    count = len(embeddings)
    if count == 0:
        return math.nan, math.nan
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, rtol=1e-6, atol=1e-8):
        raise ValueError("embedding rows must be L2-normalized")

    similarity = embeddings @ embeddings.T
    if count < 2:
        apd = math.nan
    else:
        upper_triangle = np.triu(np.ones((count, count), dtype=bool), k=1)
        apd = round(float(np.mean(1 - similarity[upper_triangle])), 4)
    eigenvalues = np.linalg.eigvalsh(similarity / count)
    positive = eigenvalues[eigenvalues > 0]
    vendi = round(float(np.exp(-np.sum(positive * np.log(positive)))), 4)
    return apd, vendi


def unique_template_ratio(templates: Sequence[str]) -> float:
    return round(len(set(templates)) / len(templates), 4) if templates else 0.0


def filter_template_ratio(templates: Sequence[str]) -> float:
    return round(len(set(templates)) / len(templates), 4) if templates else 0.0


@dataclass(frozen=True)
class TermDiversity:
    """Document-frequency diversity summaries for one resolved term type."""

    richness: int
    mean_per_query: float
    hill_1: float
    hill_2: float
    evenness: float


def term_diversity(term_sets: Sequence[Collection[str]]) -> TermDiversity:
    """Return richness and Hill diversity from per-query term presence."""
    frequencies = Counter(
        term for terms in term_sets for term in set(terms)
    )
    mentions = sum(frequencies.values())
    richness = len(frequencies)
    mean_per_query = mentions / len(term_sets) if term_sets else 0.0
    if not mentions:
        return TermDiversity(0, mean_per_query, 0.0, 0.0, 0.0)
    probabilities = np.fromiter(frequencies.values(), dtype=np.float64) / mentions
    hill_1 = float(np.exp(-np.sum(probabilities * np.log(probabilities))))
    hill_2 = float(1 / np.sum(probabilities**2))
    return TermDiversity(
        richness=richness,
        mean_per_query=round(mean_per_query, 4),
        hill_1=round(hill_1, 4),
        hill_2=round(hill_2, 4),
        evenness=round(hill_1 / richness, 4),
    )


def feature_entropy(feature_rows: Sequence[Mapping[str, int]]) -> float:
    if not feature_rows:
        return 0.0
    matrix = np.asarray(
        [[row.get(key, 0) for key in FEATURE_KEYS] for row in feature_rows],
        dtype=np.float64,
    )
    column_means = matrix.mean(axis=0)
    total = float(column_means.sum())
    if total == 0:
        return 0.0
    probabilities = column_means / total
    probabilities = probabilities[probabilities > 0]
    return round(float(-np.sum(probabilities * np.log2(probabilities))), 4)


def feature_usage_percentages(
    feature_rows: Sequence[Mapping[str, int]],
    filter_subtypes: Sequence[frozenset[str]],
) -> dict[str, float]:
    count = len(feature_rows)
    if count == 0:
        return {key: 0.0 for key in FEATURE_KEYS}
    percentages = {
        key: round(100 * sum(row.get(key, 0) for row in feature_rows) / count, 1)
        for key in FEATURE_KEYS
    }
    subtype_counts: dict[str, int] = {}
    for query_subtypes in filter_subtypes:
        for subtype in query_subtypes:
            subtype_counts[subtype] = subtype_counts.get(subtype, 0) + 1
    percentages.update(
        {
            subtype: round(100 * subtype_count / count, 1)
            for subtype, subtype_count in subtype_counts.items()
        }
    )
    return percentages


def operator_counts(
    feature_rows: Sequence[Mapping[str, int]],
) -> npt.NDArray[np.int64]:
    structural = tuple(key for key in FEATURE_KEYS if key not in {"SELECT", "ASK"})
    return np.asarray(
        [sum(row.get(key, 0) for key in structural) for row in feature_rows],
        dtype=np.int64,
    )


def population_std(values: npt.ArrayLike) -> float:
    array = np.asarray(values)
    if array.size == 0:
        return math.nan
    return round(float(np.std(array, ddof=0)), 4)
