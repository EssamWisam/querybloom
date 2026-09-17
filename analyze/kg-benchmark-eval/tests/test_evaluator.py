from __future__ import annotations

import numpy as np

from kg_benchmark_eval import (
    Benchmark,
    Evaluator,
    MetricSelection,
    Ontology,
    SparqlEndpoint,
)
from kg_benchmark_eval.encoders import FrozenEncoder


class FailingTransport:
    def __init__(self):
        self.calls = 0

    def execute(self, query, *, endpoint):
        self.calls += 1
        raise AssertionError(f"unexpected request: {query}")

    def close(self):
        pass


def benchmark():
    return Benchmark.from_records(
        [
            {
                "id": "q1",
                "question": "Which people are listed?",
                "sparql": (
                    "SELECT ?person WHERE { ?person a <https://example.org/Person> }"
                ),
            }
        ],
        name="example",
    )


def ontology():
    return Ontology.from_sets(
        classes={"https://example.org/Person"},
        properties=set(),
        name="example",
    )


def test_static_evaluation_returns_typed_shared_results():
    with Evaluator(ontology=ontology(), cache=None) as evaluator:
        result = evaluator.evaluate(benchmark())

    assert result.benchmark.size == 1
    assert result.diversity.structural.unique_template_ratio == 1.0
    assert result.diversity.structural.distinct_classes_per_query == 1.0
    assert result.coverage.classes.raw == "1/1"
    assert result.coverage.features.raw == "1/13"
    assert result.complexity.operator_counts.tolist() == [0]
    assert result.queries[0].terms is not None
    assert result.queries[0].terms.classes == frozenset({"https://example.org/Person"})


def test_static_evaluation_reports_incremental_preprocessing_progress():
    progress = []
    data = Benchmark.from_records(
        [
            {"question": "A", "sparql": "ASK {}"},
            {"question": "B", "sparql": "ASK {}"},
        ],
        name="progress",
    )
    with Evaluator(
        ontology=ontology(), cache=None, progress=lambda *update: progress.append(update)
    ) as evaluator:
        evaluator.evaluate(data)

    assert progress == [("preprocessing", 1, 2), ("preprocessing", 2, 2)]


def test_static_evaluation_uses_tqdm_progress_by_default(monkeypatch):
    created = []

    class ProgressBar:
        n = 0

        def __init__(self, **kwargs):
            self.total = kwargs["total"]
            self.n = 0
            self.closed = False

        def update(self, amount):
            self.n += amount

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "kg_benchmark_eval.evaluator.tqdm",
        lambda **kwargs: created.append(ProgressBar(**kwargs)) or created[-1],
    )
    with Evaluator(ontology=ontology(), cache=None) as evaluator:
        evaluator.evaluate(benchmark())

    assert len(created) == 1
    assert created[0].total == 1
    assert created[0].n == 1
    assert created[0].closed


def test_property_only_selection_makes_no_classification_requests():
    transport = FailingTransport()
    endpoint = SparqlEndpoint(url="https://example.org/sparql", snapshot_id="s1")
    with Evaluator(
        ontology=ontology(),
        classification_endpoint=endpoint,
        transport=transport,
        cache=None,
    ) as evaluator:
        result = evaluator.evaluate(
            benchmark(), metrics=MetricSelection.only("coverage.properties")
        )

    assert result.coverage.properties is not None
    assert transport.calls == 0
    assert result.queries[0].terms is None


def test_counts_without_execution_endpoint_are_disabled_zero_arrays():
    with Evaluator(ontology=ontology(), cache=None) as evaluator:
        result = evaluator.evaluate(
            benchmark(),
            metrics=MetricSelection.only(
                "complexity.row_counts", "complexity.column_counts"
            ),
        )

    assert result.complexity.row_counts.tolist() == [0]
    assert result.complexity.column_counts.tolist() == [0]
    assert result.metric_status["complexity.row_counts"] == "disabled"


def test_semantic_selection_uses_ordered_frozen_embeddings():
    data = Benchmark.from_records(
        [
            {"question": "A", "sparql": "ASK {}"},
            {"question": "B", "sparql": "ASK {}"},
        ],
        name="semantic",
    )
    encoder = FrozenEncoder(np.eye(2), fingerprint="fixture")
    with Evaluator(ontology=ontology(), encoder=encoder, cache=None) as evaluator:
        result = evaluator.evaluate(
            data, metrics=MetricSelection.only("diversity.semantic")
        )

    assert result.diversity.semantic.apd == 1.0
    assert result.diversity.semantic.vendi == 2.0
    assert result.diversity.semantic.embeddings.flags.writeable is False


def test_redundancy_requires_execution_endpoint_before_preprocessing():
    with Evaluator(ontology=ontology(), cache=None) as evaluator:
        try:
            evaluator.evaluate(benchmark(), metrics=MetricSelection.only("redundancy"))
        except ValueError as exc:
            assert "execution endpoint" in str(exc)
        else:
            raise AssertionError("expected configuration error")
