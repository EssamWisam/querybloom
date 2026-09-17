"""Orchestrate reproducible benchmark evaluation and metric computation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, cast

import numpy as np
import numpy.typing as npt
from tqdm.auto import tqdm
from typing_extensions import Self

from .benchmark import Benchmark
from .cache import CacheMissError, CacheStore, embedding_cache_key
from .config import METRIC_IDS, CacheConfig, MetricSelection, SparqlEndpoint
from .encoders import EmbeddingEncoder, validate_embeddings
from .execution import (
    ExecutionObservation,
    HttpxSparqlTransport,
    SparqlTransport,
    count_observation,
    execution_cache_identity,
    failure_observation,
    normalize_sparql_results,
)
from .metrics.coverage import compute_coverage, compute_feature_coverage
from .metrics.diversity import (
    embedding_diversity,
    feature_entropy,
    feature_usage_percentages,
    filter_template_ratio,
    operator_counts,
    population_std,
    term_diversity,
    unique_template_ratio,
)
from .metrics.redundancy import (
    REDUNDANCY_FEATURES,
    add_safety_limit,
    modify_query,
    pair_outcome,
)
from .ontology import Ontology
from .preprocessing import QueryPreprocessor
from .resolution import TermResolver
from .results import (
    ComplexityResult,
    CoverageResult,
    Diagnostic,
    DiversityResult,
    EvaluationResult,
    MetricStatus,
    QueryAnalysis,
    RedundancyFeatureResult,
    RedundancyPair,
    RedundancyResult,
    SemanticDiversity,
    StructuralDiversity,
    readonly_array,
)

ProgressCallback = Callable[[str, int, int], None]

logger = logging.getLogger(__name__)


class Evaluator:
    """Evaluate benchmarks against a configured ontology and optional services."""

    def __init__(
        self,
        *,
        ontology: Ontology,
        classification_endpoint: SparqlEndpoint | None = None,
        execution_endpoint: SparqlEndpoint | None = None,
        encoder: EmbeddingEncoder | None = None,
        cache: CacheConfig | None = None,
        transport: SparqlTransport | None = None,
        progress: ProgressCallback | None = None,
        count_concurrency: int = 7,
        redundancy_concurrency: int = 2,
    ) -> None:
        if count_concurrency < 1 or redundancy_concurrency < 1:
            raise ValueError("concurrency values must be positive")
        self.ontology = ontology
        self.classification_endpoint = classification_endpoint
        self.execution_endpoint = execution_endpoint
        self.encoder = encoder
        self.progress = progress or self._tqdm_progress
        self._progress_bars: dict[str, Any] = {}
        self.count_concurrency = count_concurrency
        self.redundancy_concurrency = redundancy_concurrency
        self._preprocessor = QueryPreprocessor()
        self._cache = CacheStore(cache) if cache is not None else None
        self._owns_transport = transport is None and (
            classification_endpoint is not None or execution_endpoint is not None
        )
        self._transport = (
            transport
            if transport is not None
            else HttpxSparqlTransport()
            if self._owns_transport
            else None
        )
        self._closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        for bar in self._progress_bars.values():
            bar.close()
        self._progress_bars.clear()
        if self._cache is not None:
            self._cache.close()
        if self._owns_transport and self._transport is not None:
            self._transport.close()
        self._closed = True

    def evaluate(
        self,
        benchmark: Benchmark,
        *,
        metrics: MetricSelection | None = None,
    ) -> EvaluationResult:
        if self._closed:
            raise RuntimeError("evaluator is closed")
        selection = metrics or MetricSelection.static()
        selected = selection.metric_ids
        semantic_requested = any(
            metric.startswith("diversity.semantic") for metric in selected
        )
        redundancy_requested = "redundancy.features" in selected
        if semantic_requested and self.encoder is None:
            raise ValueError("semantic metrics require an encoder")
        if redundancy_requested and self.execution_endpoint is None:
            raise ValueError("redundancy metrics require an execution endpoint")

        statuses: dict[str, MetricStatus] = {
            metric: "not_requested" for metric in METRIC_IDS
        }
        diagnostics: list[Diagnostic] = []
        need_text = any(
            metric.startswith(
                (
                    "diversity.structural",
                    "coverage.features",
                    "complexity.operator",
                    "redundancy",
                )
            )
            for metric in selected
        )
        term_diversity_requested = any(
            metric.startswith(
                (
                    "diversity.structural.class_",
                    "diversity.structural.property_",
                    "diversity.structural.entity_",
                )
            )
            and metric
            not in {
                "diversity.structural.distinct_entities_per_query",
                "diversity.structural.distinct_classes_per_query",
                "diversity.structural.distinct_properties_per_query",
            }
            for metric in selected
        )
        need_parse = any(
            metric
            in {
                "diversity.structural.distinct_entities_per_query",
                "diversity.structural.distinct_classes_per_query",
                "diversity.structural.distinct_properties_per_query",
                "coverage.classes",
                "coverage.properties",
            }
            for metric in selected
        ) or term_diversity_requested
        need_resolution = any(
            metric
            in {
                "diversity.structural.distinct_entities_per_query",
                "diversity.structural.distinct_classes_per_query",
                "coverage.classes",
            }
            for metric in selected
        ) or term_diversity_requested
        resolver = (
            TermResolver(
                ontology=self.ontology,
                endpoint=self.classification_endpoint,
                transport=self._transport,
            )
            if need_resolution
            else None
        )

        query_analyses: list[QueryAnalysis] = []
        for evaluation_index, record in enumerate(benchmark.records, start=1):
            normalized = self._preprocessor.normalize(
                record.sparql, benchmark.normalization
            )
            raw_analysis = (
                self._preprocessor.analyze(record.sparql) if need_text else None
            )
            execution_analysis = (
                self._preprocessor.analyze(normalized) if redundancy_requested else None
            )
            parsed = self._preprocessor.parse(normalized) if need_parse else None
            terms = (
                resolver.resolve(parsed)
                if resolver is not None and parsed is not None
                else None
            )
            if parsed is not None and parsed.parse_status == "failed":
                logger.warning("Using empty parsed terms for query %s", record.id)
                diagnostics.append(
                    Diagnostic(
                        code="parse_failed",
                        stage="preprocessing",
                        message=parsed.error or "SPARQL parsing failed",
                        query_id=record.id,
                        source=benchmark.source_path,
                        source_line=record.source_line,
                        evaluation_index=evaluation_index,
                        fallback_contribution="empty parsed terms and zero triples",
                    )
                )
            if terms is not None and terms.degraded:
                logger.warning("Using ontology fallback for query %s term resolution", record.id)
                diagnostics.append(
                    Diagnostic(
                        code="degraded_term_resolution",
                        stage="resolution",
                        message="one or more URI classification lookups were unavailable",
                        query_id=record.id,
                        source=benchmark.source_path,
                        source_line=record.source_line,
                        evaluation_index=evaluation_index,
                        endpoint_identity=(
                            self.classification_endpoint.identity
                            if self.classification_endpoint is not None
                            else None
                        ),
                        fallback_contribution="ontology-index fallback",
                    )
                )
            query_analyses.append(
                QueryAnalysis(
                    record=record,
                    evaluation_index=evaluation_index,
                    normalized_sparql=normalized,
                    parsed=parsed,
                    terms=terms,
                    raw_features=raw_analysis.features if raw_analysis else None,
                    execution_features=(
                        execution_analysis.features if execution_analysis else None
                    ),
                    template=raw_analysis.template if raw_analysis else None,
                    filter_templates=(
                        raw_analysis.filter_templates if raw_analysis else None
                    ),
                    filter_subtypes=(
                        raw_analysis.filter_subtypes if raw_analysis else None
                    ),
                )
            )
            self._progress("preprocessing", evaluation_index, benchmark.size)

        semantic = self._evaluate_semantic(benchmark, selected, statuses)
        structural, complexity, coverage = self._evaluate_static(
            benchmark, query_analyses, selected, statuses
        )

        redundancy_work = self._build_redundancy_work(query_analyses)
        execution_requested = any(
            metric
            in {
                "complexity.row_counts",
                "complexity.column_counts",
                "complexity.row_count_std",
                "complexity.column_count_std",
            }
            for metric in selected
        )
        requested_queries: set[str] = set()
        query_labels: dict[str, str] = {}
        for query in query_analyses:
            label = self._describe_query_source(query, benchmark)
            query_labels.setdefault(query.normalized_sparql, label)
        if execution_requested and self.execution_endpoint is not None:
            requested_queries.update(
                query.normalized_sparql for query in query_analyses
            )
        if redundancy_requested:
            for query, feature, original, modified, unchanged in redundancy_work:
                if not unchanged:
                    requested_queries.update((original, modified))
                    label = self._describe_query_source(query, benchmark)
                    query_labels.setdefault(original, label)
                    query_labels.setdefault(
                        modified, f"{label} (redundancy feature={feature})"
                    )
        observations = self._execute_queries(
            requested_queries,
            allow_failure_cache=redundancy_requested and not execution_requested,
            max_workers=(
                self.redundancy_concurrency
                if redundancy_requested
                else self.count_concurrency
            ),
            query_labels=query_labels,
        )
        complexity = self._add_execution_complexity(
            complexity,
            query_analyses,
            observations,
            selected,
            statuses,
            diagnostics,
        )
        redundancy = (
            self._evaluate_redundancy(redundancy_work, observations, statuses)
            if redundancy_requested
            else None
        )

        provenance = MappingProxyType(
            {
                "package_version": "0.1.0",
                "metric_definition_version": "1",
                "ontology_fingerprint": self.ontology.fingerprint,
                "classification_endpoint": (
                    dict(self.classification_endpoint.identity)
                    if self.classification_endpoint is not None
                    else None
                ),
                "execution_endpoint": (
                    dict(self.execution_endpoint.identity)
                    if self.execution_endpoint is not None
                    else None
                ),
                "encoder": (
                    dict(self.encoder.identity.to_dict())
                    if self.encoder is not None and semantic_requested
                    else None
                ),
                "cache_policy": self._cache.config.policy
                if self._cache
                else "disabled",
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return EvaluationResult(
            benchmark=benchmark,
            diversity=DiversityResult(semantic=semantic, structural=structural),
            complexity=complexity,
            coverage=coverage,
            redundancy=redundancy,
            queries=tuple(query_analyses),
            metric_status=MappingProxyType(statuses),
            diagnostics=tuple(diagnostics),
            provenance=provenance,
        )

    def _evaluate_semantic(
        self,
        benchmark: Benchmark,
        selected: frozenset[str],
        statuses: dict[str, MetricStatus],
    ) -> SemanticDiversity | None:
        if not any(metric.startswith("diversity.semantic") for metric in selected):
            return None
        assert self.encoder is not None
        questions = tuple(record.question for record in benchmark.records)
        if not questions:
            embeddings: npt.NDArray[np.floating[Any]] = np.empty(
                (0, 0), dtype=np.float64
            )
            embeddings.setflags(write=False)
        else:
            key = embedding_cache_key(questions, self.encoder.identity.to_dict())
            cached = self._cache.get_array("embeddings", key) if self._cache else None
            if cached is None:
                embeddings = validate_embeddings(
                    np.asarray(self.encoder.encode(questions)), len(questions)
                )
                if self._cache is not None:
                    self._cache.put_array("embeddings", key, embeddings)
            else:
                embeddings = validate_embeddings(
                    cast(npt.NDArray[np.floating[Any]], cached), len(questions)
                )
        apd, vendi = embedding_diversity(embeddings)
        for metric, value in (
            ("diversity.semantic.apd", apd),
            ("diversity.semantic.vendi", vendi),
        ):
            if metric in selected:
                statuses[metric] = "undefined" if np.isnan(value) else "ok"
        return SemanticDiversity(
            apd=apd,
            vendi=vendi,
            embeddings=embeddings,
            encoder_identity=self.encoder.identity,
        )

    def _evaluate_static(
        self,
        benchmark: Benchmark,
        queries: list[QueryAnalysis],
        selected: frozenset[str],
        statuses: dict[str, MetricStatus],
    ) -> tuple[StructuralDiversity, ComplexityResult, CoverageResult]:
        feature_rows = [
            query.raw_features for query in queries if query.raw_features is not None
        ]
        subtype_rows = [
            query.filter_subtypes or frozenset()
            for query in queries
            if query.raw_features is not None
        ]
        templates = [query.template for query in queries if query.template is not None]
        filter_templates = [
            template for query in queries for template in (query.filter_templates or ())
        ]
        observed_entities = frozenset(
            entity
            for query in queries
            if query.terms is not None
            for entity in query.terms.entities
        )
        observed_classes = frozenset(
            value
            for query in queries
            if query.terms is not None
            for value in query.terms.classes
        )
        observed_properties = frozenset(
            value
            for query in queries
            if query.parsed is not None
            for value in query.parsed.properties
        )
        class_sets = [
            query.terms.classes for query in queries if query.terms is not None
        ]
        property_sets = [
            query.parsed.properties for query in queries if query.parsed is not None
        ]
        entity_sets = [
            query.terms.entities for query in queries if query.terms is not None
        ]
        class_coverage = (
            compute_coverage(observed_classes, self.ontology.classes)
            if "coverage.classes" in selected
            else None
        )
        property_coverage = (
            compute_coverage(observed_properties, self.ontology.properties)
            if "coverage.properties" in selected
            else None
        )
        feature_coverage = (
            compute_feature_coverage(feature_rows)
            if "coverage.features" in selected
            else None
        )
        for metric in selected:
            if metric.startswith(
                ("diversity.structural", "coverage", "complexity.operator")
            ):
                statuses[metric] = "ok"
        if class_coverage is not None and (
            self.ontology.missing_classes
            or any(query.terms and query.terms.degraded for query in queries)
        ):
            statuses["coverage.classes"] = "degraded"
        if property_coverage is not None and self.ontology.missing_properties:
            statuses["coverage.properties"] = "degraded"

        usage = (
            feature_usage_percentages(feature_rows, subtype_rows)
            if feature_rows
            else {}
        )
        class_diversity = term_diversity(class_sets)
        property_diversity = term_diversity(property_sets)
        entity_diversity = term_diversity(entity_sets)
        structural = StructuralDiversity(
            unique_template_ratio=(
                unique_template_ratio(templates)
                if "diversity.structural.unique_template_ratio" in selected
                else None
            ),
            distinct_entities_per_query=(
                len(observed_entities) / benchmark.size if benchmark.size else 0.0
            )
            if "diversity.structural.distinct_entities_per_query" in selected
            else None,
            filter_template_ratio=(
                filter_template_ratio(filter_templates)
                if "diversity.structural.filter_template_ratio" in selected
                else None
            ),
            feature_entropy_bits=(
                feature_entropy(feature_rows)
                if "diversity.structural.feature_entropy_bits" in selected
                else None
            ),
            feature_usage_pct=(
                MappingProxyType(usage)
                if "diversity.structural.feature_usage_pct" in selected
                else None
            ),
            filter_subtype_keys=tuple(
                sorted(key for key in usage if key.startswith("FILTER:"))
            ),
            distinct_classes_per_query=(
                (
                    class_coverage
                    or compute_coverage(observed_classes, self.ontology.classes)
                ).covered
                / benchmark.size
                if benchmark.size
                else 0.0
            )
            if "diversity.structural.distinct_classes_per_query" in selected
            else None,
            distinct_properties_per_query=(
                (
                    property_coverage
                    or compute_coverage(observed_properties, self.ontology.properties)
                ).covered
                / benchmark.size
                if benchmark.size
                else 0.0
            )
            if "diversity.structural.distinct_properties_per_query" in selected
            else None,
            class_richness=(
                class_diversity.richness
                if "diversity.structural.class_richness" in selected
                else None
            ),
            property_richness=(
                property_diversity.richness
                if "diversity.structural.property_richness" in selected
                else None
            ),
            entity_richness=(
                entity_diversity.richness
                if "diversity.structural.entity_richness" in selected
                else None
            ),
            class_mean_per_query=(
                class_diversity.mean_per_query
                if "diversity.structural.class_mean_per_query" in selected
                else None
            ),
            property_mean_per_query=(
                property_diversity.mean_per_query
                if "diversity.structural.property_mean_per_query" in selected
                else None
            ),
            entity_mean_per_query=(
                entity_diversity.mean_per_query
                if "diversity.structural.entity_mean_per_query" in selected
                else None
            ),
            class_hill_1=(
                class_diversity.hill_1
                if "diversity.structural.class_hill_1" in selected
                else None
            ),
            property_hill_1=(
                property_diversity.hill_1
                if "diversity.structural.property_hill_1" in selected
                else None
            ),
            entity_hill_1=(
                entity_diversity.hill_1
                if "diversity.structural.entity_hill_1" in selected
                else None
            ),
            class_hill_2=(
                class_diversity.hill_2
                if "diversity.structural.class_hill_2" in selected
                else None
            ),
            property_hill_2=(
                property_diversity.hill_2
                if "diversity.structural.property_hill_2" in selected
                else None
            ),
            entity_hill_2=(
                entity_diversity.hill_2
                if "diversity.structural.entity_hill_2" in selected
                else None
            ),
            class_evenness=(
                class_diversity.evenness
                if "diversity.structural.class_evenness" in selected
                else None
            ),
            property_evenness=(
                property_diversity.evenness
                if "diversity.structural.property_evenness" in selected
                else None
            ),
            entity_evenness=(
                entity_diversity.evenness
                if "diversity.structural.entity_evenness" in selected
                else None
            ),
            distinct_entities=observed_entities,
        )
        operators = (
            operator_counts(feature_rows)
            if any(metric.startswith("complexity.operator") for metric in selected)
            else None
        )
        if operators is not None:
            operators.setflags(write=False)
        operator_std = population_std(operators) if operators is not None else None
        if (
            "complexity.operator_count_std" in selected
            and operator_std is not None
            and np.isnan(operator_std)
        ):
            statuses["complexity.operator_count_std"] = "undefined"
        return (
            structural,
            ComplexityResult(
                operator_counts=(
                    operators if "complexity.operator_counts" in selected else None
                ),
                operator_count_std=(
                    operator_std
                    if "complexity.operator_count_std" in selected
                    else None
                ),
            ),
            CoverageResult(
                classes=class_coverage,
                properties=property_coverage,
                features=feature_coverage,
                class_universe=self.ontology.classes,
                property_universe=self.ontology.properties,
                covered_classes=(
                    observed_classes & self.ontology.classes
                    if self.ontology.classes
                    else observed_classes
                ),
                covered_properties=(
                    observed_properties & self.ontology.properties
                    if self.ontology.properties
                    else observed_properties
                ),
            ),
        )

    def _build_redundancy_work(
        self, queries: list[QueryAnalysis]
    ) -> list[tuple[QueryAnalysis, str, str, str, bool]]:
        work = []
        for query in queries:
            features = query.execution_features or {}
            for feature in REDUNDANCY_FEATURES:
                if not features.get(feature, 0):
                    continue
                original = query.normalized_sparql
                modified = modify_query(original, feature)
                unchanged = modified.strip() == original.strip()
                if not unchanged:
                    modified = add_safety_limit(modified)
                work.append((query, feature, original, modified, unchanged))
        return work

    def _describe_query_source(
        self, query: QueryAnalysis, benchmark: Benchmark
    ) -> str:
        parts = [f"query_id={query.record.id}", f"evaluation_index={query.evaluation_index}"]
        if benchmark.source_path is not None:
            parts.append(f"source={benchmark.source_path}:{query.record.source_line}")
        return ", ".join(parts)

    def _execute_queries(
        self,
        queries: Iterable[str],
        *,
        allow_failure_cache: bool,
        max_workers: int,
        query_labels: Mapping[str, str] | None = None,
    ) -> dict[str, ExecutionObservation]:
        unique = tuple(dict.fromkeys(queries))
        if not unique:
            return {}
        if self.execution_endpoint is None or self._transport is None:
            return {}
        endpoint = self.execution_endpoint
        transport = self._transport
        labels = query_labels or {}

        def execute(query: str) -> tuple[str, ExecutionObservation]:
            key = execution_cache_identity(query, endpoint)
            if self._cache is not None:
                try:
                    cached = self._cache.get_json("execution_success", key)
                except CacheMissError:
                    if not allow_failure_cache:
                        raise
                    cached = None
                if cached is None and allow_failure_cache:
                    cached = self._cache.get_json("redundancy_failure", key)
                if cached is not None:
                    return query, _observation_from_payload(cached)
            try:
                observation = transport.execute(query, endpoint=endpoint)
            except Exception as exc:  # noqa: BLE001 - transport boundary
                logger.warning(
                    "SPARQL execution failed for %s; recording a failed observation\nquery:\n%s",
                    labels.get(query, "unknown source"),
                    query,
                    exc_info=True,
                )
                observation = failure_observation(str(exc))
            if observation.kind == "failure":
                logger.warning(
                    "Failed SPARQL observation for %s: %s\nquery:\n%s",
                    labels.get(query, "unknown source"),
                    observation.error,
                    query,
                )
            if self._cache is not None:
                if observation.kind != "failure":
                    self._cache.put_json(
                        "execution_success", key, _observation_payload(observation)
                    )
                elif allow_failure_cache:
                    self._cache.put_json(
                        "redundancy_failure", key, _observation_payload(observation)
                    )
            return query, observation

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(execute, query) for query in unique]
            pairs = []
            for completed, future in enumerate(as_completed(futures), start=1):
                pairs.append(future.result())
                self._progress("execution", completed, len(unique))
        return dict(pairs)

    def _add_execution_complexity(
        self,
        complexity: ComplexityResult,
        queries: list[QueryAnalysis],
        observations: Mapping[str, ExecutionObservation],
        selected: frozenset[str],
        statuses: dict[str, MetricStatus],
        diagnostics: list[Diagnostic],
    ) -> ComplexityResult:
        count_metrics = {
            "complexity.row_counts",
            "complexity.column_counts",
            "complexity.row_count_std",
            "complexity.column_count_std",
        }
        if not selected & count_metrics:
            return complexity
        rows: npt.NDArray[np.int64]
        columns: npt.NDArray[np.int64]
        execution_status: tuple[str, ...]
        observation_ids: tuple[str | None, ...]
        if self.execution_endpoint is None:
            rows = readonly_array(np.zeros(len(queries), dtype=np.int64))
            columns = readonly_array(np.zeros(len(queries), dtype=np.int64))
            execution_status = tuple("disabled" for _ in queries)
            observation_ids = (None,) * len(queries)
            for metric in selected & count_metrics:
                statuses[metric] = "disabled"
        else:
            row_values: list[int] = []
            column_values: list[int] = []
            execution_status_list: list[str] = []
            observation_id_list: list[str | None] = []
            for query in queries:
                observation = observations[query.normalized_sparql]
                row_count, column_count, status = count_observation(
                    query.normalized_sparql, observation
                )
                row_values.append(row_count)
                column_values.append(column_count)
                execution_status_list.append(status)
                observation_id_list.append(observation.id)
                if status == "failed":
                    logger.warning(
                        "Using zero row and column counts for failed query %s",
                        query.record.id,
                    )
                    diagnostics.append(
                        Diagnostic(
                            code="execution_failed",
                            stage="complexity",
                            message=observation.error or "unavailable query result",
                            query_id=query.record.id,
                            source=query.record.id,
                            source_line=query.record.source_line,
                            evaluation_index=query.evaluation_index,
                            endpoint_identity=self.execution_endpoint.identity,
                            fallback_contribution="row_count=0,column_count=0",
                        )
                    )
            rows = readonly_array(np.asarray(row_values, dtype=np.int64))
            columns = readonly_array(np.asarray(column_values, dtype=np.int64))
            execution_status = tuple(execution_status_list)
            observation_ids = tuple(observation_id_list)
            for metric in selected & count_metrics:
                statuses[metric] = "ok"
        row_std = population_std(rows)
        column_std = population_std(columns)
        for metric, value in (
            ("complexity.row_count_std", row_std),
            ("complexity.column_count_std", column_std),
        ):
            if metric in selected and np.isnan(value):
                statuses[metric] = "undefined"
        return ComplexityResult(
            operator_counts=complexity.operator_counts,
            row_counts=rows if "complexity.row_counts" in selected else None,
            column_counts=(columns if "complexity.column_counts" in selected else None),
            operator_count_std=complexity.operator_count_std,
            row_count_std=(row_std if "complexity.row_count_std" in selected else None),
            column_count_std=(
                column_std if "complexity.column_count_std" in selected else None
            ),
            execution_status=execution_status,
            observation_ids=observation_ids,
        )

    def _evaluate_redundancy(
        self,
        work: list[tuple[QueryAnalysis, str, str, str, bool]],
        observations: Mapping[str, ExecutionObservation],
        statuses: dict[str, MetricStatus],
    ) -> RedundancyResult:
        counters = {
            feature: {
                "feature_present": 0,
                "unchanged_modification": 0,
                "eligible": 0,
                "redundant": 0,
                "failed_pairs": 0,
            }
            for feature in REDUNDANCY_FEATURES
        }
        pairs: list[RedundancyPair] = []
        for query, feature, original, modified, unchanged in work:
            values = counters[feature]
            values["feature_present"] += 1
            if unchanged:
                values["unchanged_modification"] += 1
                pairs.append(
                    RedundancyPair(
                        query_id=query.record.id,
                        feature=feature,
                        original_text=original,
                        modified_text=modified,
                        original_observation_id=None,
                        modified_observation_id=None,
                        outcome="unchanged_modification",
                    )
                )
                continue
            values["eligible"] += 1
            original_observation = observations[original]
            modified_observation = observations[modified]
            outcome = pair_outcome(
                original_observation, modified_observation, feature=feature
            )
            if outcome == "redundant":
                values["redundant"] += 1
            elif outcome == "failed":
                values["failed_pairs"] += 1
            pairs.append(
                RedundancyPair(
                    query_id=query.record.id,
                    feature=feature,
                    original_text=original,
                    modified_text=modified,
                    original_observation_id=original_observation.id,
                    modified_observation_id=modified_observation.id,
                    outcome=outcome,
                )
            )
        summaries = {}
        for feature, values in counters.items():
            eligible = values["eligible"]
            summaries[feature] = RedundancyFeatureResult(
                rate_pct=(100 * values["redundant"] / eligible if eligible else 0.0),
                **values,
            )
        statuses["redundancy.features"] = "ok"
        return RedundancyResult(
            features=MappingProxyType(summaries), pairs=tuple(pairs)
        )

    def _progress(self, stage: str, completed: int, total: int) -> None:
        self.progress(stage, completed, total)

    def _tqdm_progress(self, stage: str, completed: int, total: int) -> None:
        bar = self._progress_bars.get(stage)
        if bar is None or completed < bar.n:
            if bar is not None:
                bar.close()
            bar = tqdm(total=total, desc=stage.capitalize(), unit="query")
            self._progress_bars[stage] = bar
        bar.update(completed - bar.n)


def _observation_payload(observation: ExecutionObservation) -> dict[str, object]:
    return {
        "kind": observation.kind,
        "head_vars": list(observation.head_vars),
        "rows": [
            {variable: dict(binding) for variable, binding in row.items()}
            for row in observation.rows
        ],
        "boolean": observation.boolean,
        "error": observation.error,
        "observed_at": observation.observed_at,
    }


def _observation_from_payload(payload: Mapping[str, object]) -> ExecutionObservation:
    kind = payload.get("kind")
    if kind == "ask":
        boolean = payload.get("boolean")
        return ExecutionObservation(
            kind="ask",
            boolean=boolean if isinstance(boolean, bool) else None,
            observed_at=str(payload.get("observed_at", "")),
        )
    if kind == "failure":
        return ExecutionObservation(
            kind="failure",
            error=str(payload.get("error", "cached failure")),
            observed_at=str(payload.get("observed_at", "")),
        )
    return normalize_sparql_results(
        {
            "head": {"vars": payload.get("head_vars", [])},
            "results": {"bindings": payload.get("rows", [])},
        }
    )
