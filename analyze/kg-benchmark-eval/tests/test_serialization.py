from __future__ import annotations

import numpy as np
import pytest

from kg_benchmark_eval import (
    Benchmark,
    EvaluationResult,
    Evaluator,
    MetricSelection,
    Ontology,
)
from kg_benchmark_eval.encoders import FrozenEncoder


def test_bundle_round_trip_preserves_metrics_queries_and_arrays(tmp_path):
    benchmark = Benchmark.from_records(
        [
            {
                "id": "q1",
                "question": "Who?",
                "sparql": "SELECT ?s WHERE { ?s a <https://example.org/Person> }",
            },
            {"id": "q2", "question": "Anything?", "sparql": "ASK {}"},
        ],
        name="fixture",
    )
    ontology = Ontology.from_sets(
        classes={"https://example.org/Person"}, properties=set(), name="fixture"
    )
    with Evaluator(
        ontology=ontology,
        encoder=FrozenEncoder(np.eye(2), fingerprint="fixture"),
        cache=None,
    ) as evaluator:
        result = evaluator.evaluate(
            benchmark,
            metrics=MetricSelection.only(
                "diversity",
                "coverage",
                "complexity.operator_counts",
                "complexity.operator_count_std",
            ),
        )

    bundle = tmp_path / "bundle"
    result.save_bundle(bundle)
    loaded = EvaluationResult.load_bundle(bundle)

    assert loaded.to_dict() == result.to_dict()
    assert loaded.queries[0].parsed == result.queries[0].parsed
    assert loaded.queries[0].terms == result.queries[0].terms
    assert loaded.diversity.semantic is not None
    assert loaded.diversity.semantic.embeddings.flags.writeable is False
    with pytest.raises(FileExistsError):
        result.save_bundle(bundle)


def test_bundle_detects_checksum_corruption(tmp_path):
    benchmark = Benchmark.from_records([], name="empty")
    ontology = Ontology.from_sets(classes=set(), properties=set(), name="empty")
    with Evaluator(ontology=ontology, cache=None) as evaluator:
        result = evaluator.evaluate(benchmark)
    bundle = tmp_path / "bundle"
    result.save_bundle(bundle)
    (bundle / "metrics.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum"):
        EvaluationResult.load_bundle(bundle)
