"""Public interface for KG Benchmark Evaluation."""

from .benchmark import (
    Benchmark,
    BenchmarkValidationError,
    QueryRecord,
    SamplingManifest,
    balance_benchmarks,
)
from .config import CacheConfig, MetricSelection, SparqlEndpoint
from .evaluator import Evaluator
from .ontology import Ontology, OntologyLoadError
from .results import EvaluationResult

__all__ = [
    "Benchmark",
    "BenchmarkValidationError",
    "CacheConfig",
    "EvaluationResult",
    "Evaluator",
    "MetricSelection",
    "Ontology",
    "OntologyLoadError",
    "QueryRecord",
    "SamplingManifest",
    "SparqlEndpoint",
    "balance_benchmarks",
]

__version__ = "0.1.0"
