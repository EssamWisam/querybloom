from __future__ import annotations

import math

import numpy as np

from kg_benchmark_eval.execution import ExecutionObservation
from kg_benchmark_eval.metrics.coverage import (
    compute_coverage,
    compute_feature_coverage,
)
from kg_benchmark_eval.metrics.diversity import (
    embedding_diversity,
    feature_entropy,
    feature_usage_percentages,
    population_std,
    term_diversity,
)
from kg_benchmark_eval.metrics.redundancy import (
    add_safety_limit,
    modify_query,
    results_match,
)
from kg_benchmark_eval.preprocessing import FEATURE_KEYS


def test_semantic_metrics_use_full_cosine_matrix_without_renormalizing_eigenvalues():
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)

    apd, vendi = embedding_diversity(embeddings)

    assert apd == 1.0
    assert vendi == 2.0
    singleton_apd, singleton_vendi = embedding_diversity(embeddings[:1])
    assert math.isnan(singleton_apd)
    assert singleton_vendi == 1.0


def test_entropy_usage_and_population_std_follow_feature_contract():
    rows = [
        {key: int(key == "SELECT") for key in FEATURE_KEYS},
        {key: int(key in {"SELECT", "FILTER"}) for key in FEATURE_KEYS},
    ]

    assert feature_entropy(rows) == 0.9183
    usage = feature_usage_percentages(rows, [frozenset(), frozenset({"FILTER:REGEX"})])
    assert usage["SELECT"] == 100.0
    assert usage["FILTER"] == 50.0
    assert usage["FILTER:REGEX"] == 50.0
    assert population_std(np.array([0, 2])) == 1.0
    assert math.isnan(population_std(np.array([])))


def test_term_diversity_counts_a_term_once_per_query():
    diversity = term_diversity([("a", "a"), ("b",)])
    assert diversity.richness == 2
    assert diversity.mean_per_query == 1.0
    assert diversity.hill_1 == 2.0
    assert diversity.hill_2 == 2.0
    assert diversity.evenness == 1.0

    diversity = term_diversity([{"a", "b"}, {"a"}])
    assert diversity.richness == 2
    assert diversity.mean_per_query == 1.5
    assert diversity.hill_1 == 1.8899
    assert diversity.hill_2 == 1.8
    assert diversity.evenness == 0.9449
    assert term_diversity([set(), set()]).richness == 0


def test_coverage_preserves_legacy_numerator_when_universe_is_empty():
    missing = compute_coverage(frozenset({"https://example.org/Observed"}), frozenset())
    present = compute_coverage(frozenset({"a", "outside"}), frozenset({"a", "b"}))

    assert (missing.ratio, missing.covered, missing.total, missing.raw) == (
        0.0,
        1,
        0,
        "1/0",
    )
    assert (present.ratio, present.covered, present.total) == (0.5, 1, 2)
    assert compute_feature_coverage([{"SELECT": 1}]).total == len(FEATURE_KEYS)


def test_redundancy_mutations_match_production_helpers():
    query = (
        "SELECT DISTINCT ?s WHERE { ?s ?p ?o . "
        "OPTIONAL { ?s ?p2 ?o2 } FILTER(regex(str(?o), 'x')) } "
        "ORDER BY ?s LIMIT 5"
    )

    assert "DISTINCT" not in modify_query(query, "DISTINCT")
    assert "FILTER" not in modify_query(query, "FILTER")
    assert "OPTIONAL" not in modify_query(query, "OPTIONAL")
    assert "ORDER BY" not in modify_query(query, "ORDER BY")
    assert modify_query(query, "LIMIT").endswith("LIMIT 10")
    assert add_safety_limit("SELECT * WHERE {}") == ("SELECT * WHERE {}\nLIMIT 100000")
    assert add_safety_limit("ASK WHERE { ?s ?p ?o }") == "ASK WHERE { ?s ?p ?o }"


def test_remove_all_filters_does_not_strand_a_dangling_dot():
    query = (
        "SELECT DISTINCT ?firstanswer ?secondanswer WHERE { "
        "?x dblp:authoredBy <https://dblp.org/pid/07/148> . "
        "?x dblp:yearOfPublication ?y . "
        "FILTER(?y > 2000) . "
        "?x dblp:publishedIn ?firstanswer . "
        "?x dblp:title ?secondanswer }"
    )

    modified = modify_query(query, "FILTER")

    assert "FILTER" not in modified
    assert ". ." not in modified
    assert ".  ." not in modified


def test_redundancy_comparison_uses_sets_except_for_order_by():
    first = ExecutionObservation(
        kind="select",
        rows=(
            {"x": {"type": "literal", "value": "1", "datatype": "a"}},
            {"x": {"type": "literal", "value": "2"}},
            {"x": {"type": "literal", "value": "2"}},
        ),
    )
    second = ExecutionObservation(
        kind="select",
        rows=(
            {"x": {"type": "literal", "value": "2"}},
            {"x": {"type": "literal", "value": "1", "datatype": "b"}},
        ),
    )

    assert results_match(first, second, order_sensitive=False) is True
    assert results_match(first, second, order_sensitive=True) is False
    assert (
        results_match(first, ExecutionObservation(kind="ask", boolean=False)) is False
    )
