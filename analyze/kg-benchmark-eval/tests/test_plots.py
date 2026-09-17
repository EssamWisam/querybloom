from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import matplotlib
import pytest

matplotlib.use("Agg")

from kg_benchmark_eval import Benchmark, Evaluator, Ontology, plots
from kg_benchmark_eval.results import (
    RedundancyFeatureResult,
    RedundancyPair,
    RedundancyResult,
)


def evaluated(name):
    benchmark = Benchmark.from_records(
        [
            {
                "id": "q1",
                "question": "Who <works>?",
                "sparql": "SELECT ?s WHERE { ?s a <https://example.org/Person> }",
            }
        ],
        name=name,
    )
    ontology = Ontology.from_sets(
        classes={"https://example.org/Person", "https://example.org/Place"},
        properties={"https://example.org/name"},
        name="fixture",
    )
    with Evaluator(ontology=ontology, cache=None) as evaluator:
        return evaluator.evaluate(benchmark)


def test_coverage_gaps_uses_stored_sets_and_seed(tmp_path):
    left = evaluated("left")
    right = evaluated("right")
    comparison = left.compare(right)

    first = plots.coverage_gaps(comparison, sample_size=1, seed=42)
    second = plots.coverage_gaps(comparison, sample_size=1, seed=42)

    assert first is not second
    assert len(first.axes) == 2


def test_semantic_plot_lists_missing_metrics():
    comparison = evaluated("left").compare(evaluated("right"))

    with pytest.raises(plots.MissingMetricError, match="diversity.semantic"):
        plots.semantic_space(comparison)


def test_structural_plot_restores_three_panel_comparison():
    comparison = evaluated("left").compare(evaluated("right"))

    figure = plots.structural_diversity(comparison)

    assert len(figure.axes) == 3
    labels = [label.get_text() for label in figure.axes[0].get_xticklabels()]
    assert "Feature\ncoverage" not in labels
    assert "Entity\nbreadth" in labels
    assert {
        "Class\nevenness",
        "Property\nevenness",
        "Entity\nevenness",
    } <= set(labels)


def test_structural_plot_debug_prints_cross_query_repetitions(capsys):
    comparison = evaluated("left").compare(evaluated("right"))

    plots.structural_diversity(comparison, debug=True)

    assert capsys.readouterr().out == (
        "left:\n"
        "  classes:\n"
        "    (none)\n"
        "  properties:\n"
        "    (none)\n"
        "  entities:\n"
        "    (none)\n"
        "right:\n"
        "  classes:\n"
        "    (none)\n"
        "  properties:\n"
        "    (none)\n"
        "  entities:\n"
        "    (none)\n"
    )


def test_structural_plot_logs_skipped_complexity_metrics(caplog):
    comparison = evaluated("left").compare(evaluated("right"))

    plots.structural_diversity(comparison)

    assert "Skipping output rows complexity distribution" in caplog.text


def test_coverage_gap_tables_have_colored_headers():
    comparison = evaluated("left").compare(evaluated("right"))

    figure = plots.coverage_gaps(comparison)

    assert figure.axes[0].tables[0][0, 0].get_facecolor()[:3] != (1.0, 1.0, 1.0)


def test_redundancy_examples_escapes_question_and_query_text():
    result = evaluated("left")
    redundancy = RedundancyResult(
        features=MappingProxyType(
            {
                "FILTER": RedundancyFeatureResult(
                    rate_pct=100.0,
                    feature_present=1,
                    unchanged_modification=0,
                    eligible=1,
                    redundant=1,
                    failed_pairs=0,
                )
            }
        ),
        pairs=(
            RedundancyPair(
                query_id="q1",
                feature="FILTER",
                original_text="SELECT <unsafe>",
                modified_text="SELECT ?s",
                original_observation_id="a",
                modified_observation_id="b",
                outcome="redundant",
            ),
        ),
    )
    result = replace(result, redundancy=redundancy)

    rendered = plots.redundancy_examples(result)

    assert "Who &lt;works&gt;?" in rendered
    assert "SELECT &lt;unsafe&gt;" in rendered
    assert "<unsafe>" not in rendered
