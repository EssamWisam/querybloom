from __future__ import annotations

import os
from pathlib import Path

from kg_benchmark_eval import (
    Benchmark,
    CacheConfig,
    Evaluator,
    MetricSelection,
    Ontology,
    SparqlEndpoint,
    balance_benchmarks,
    plots,
)
from kg_benchmark_eval.encoders import SentenceTransformerEncoder


def main() -> None:
    data_root = Path(os.environ["BENCHMARK_DATA_ROOT"])
    schema_root = Path(os.environ["KG_INDEX_ROOT"])
    generated = Benchmark.from_jsonl(
        data_root / "04-30-21-dbpedia-qlever-gemini31propreview_sample600.jsonl",
        name="QueryBloom",
        normalization="standard",
    )
    qald = Benchmark.from_jsonl(
        data_root / "qald9-test.jsonl", name="QALD-9", normalization="qald9"
    )
    generated, qald = balance_benchmarks(generated, qald, seed=40)
    ontology = Ontology.from_directory(schema_root, kg="dbpedia")
    classification = SparqlEndpoint(
        url=os.environ["DBPEDIA_CLASSIFICATION_URL"],
        snapshot_id=os.environ["DBPEDIA_CLASSIFICATION_SNAPSHOT"],
    )
    execution = SparqlEndpoint(
        url=os.environ["DBPEDIA_EXECUTION_URL"],
        snapshot_id=os.environ["DBPEDIA_EXECUTION_SNAPSHOT"],
    )
    encoder = SentenceTransformerEncoder(
        model_id="BAAI/bge-large-en-v1.5",
        revision=os.environ["BGE_MODEL_REVISION"],
        device="cpu",
    )
    with Evaluator(
        ontology=ontology,
        classification_endpoint=classification,
        execution_endpoint=execution,
        encoder=encoder,
        cache=CacheConfig(Path(".cache/kg-benchmark-eval")),
    ) as evaluator:
        generated_result = evaluator.evaluate(generated, metrics=MetricSelection.all())
        qald_result = evaluator.evaluate(qald, metrics=MetricSelection.all())

    generated_result.save_bundle(Path("artifacts/querybloom"))
    qald_result.save_bundle(Path("artifacts/qald9"))
    comparison = generated_result.compare(qald_result)
    output = Path("figures/qald9")
    output.mkdir(parents=True, exist_ok=True)
    figures = {
        "semantic_space": plots.semantic_space(comparison, trim_outlier_pct=5, seed=42),
        "structural_diversity": plots.structural_diversity(
            comparison, complexity="histogram"
        ),
        "coverage_gaps": plots.coverage_gaps(comparison, sample_size=8, seed=42),
        "entities": plots.entities(comparison, top_n=20),
    }
    for name, figure in figures.items():
        figure.savefig(output / f"{name}.pdf", bbox_inches="tight")


if __name__ == "__main__":
    main()
