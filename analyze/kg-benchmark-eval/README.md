# kg-benchmark-eval

`kg-benchmark-eval` evaluates paired natural-language questions and SPARQL
queries. It provides reproducible structural, semantic, coverage, complexity,
and feature-redundancy metrics without depending on QueryBloom or this source
repository.

## Install

```bash
pip install kg-benchmark-eval
pip install 'kg-benchmark-eval[semantic,plots,tables]'
```

For development with the existing `m1` interpreter:

```bash
uv venv --python "$CONDA_PREFIX/bin/python" .venv
uv sync --extra semantic --extra plots --extra tables --group dev
uv run pytest
uv run ruff check src tests examples
uv run mypy src/kg_benchmark_eval
uv build
```

## Example

```python
from kg_benchmark_eval import Benchmark, Evaluator, MetricSelection, Ontology

benchmark = Benchmark.from_records(
    [{
        "id": "q1",
        "question": "Which people are listed?",
        "sparql": "SELECT ?person WHERE { ?person a <https://example.org/Person> }",
    }],
    name="example",
)
ontology = Ontology.from_sets(
    classes={"https://example.org/Person"},
    properties=set(),
    name="example",
)

with Evaluator(ontology=ontology, cache=None) as evaluator:
    result = evaluator.evaluate(benchmark, metrics=MetricSelection.static())

print(result.coverage.classes.raw)
print(result.diversity.structural.unique_template_ratio)
```

`evaluate()` defaults to static metrics. `MetricSelection.all()` additionally
requires an embedding encoder and execution endpoint. Query execution failures
contribute zero row/column counts and non-redundant eligible pairs; inspect
`result.diagnostics` and metric statuses before publishing scores.

The package preserves the documented heuristic feature/path detection,
formatting-sensitive templates, set-based redundancy comparison, and the
modified-query-only 100,000-row safety cap. See
[`docs/metric_definitions.md`](docs/metric_definitions.md) and
[`docs/migration.md`](docs/migration.md) for formulas and intentional corrections.