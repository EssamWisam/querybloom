"""Read and write portable evaluation-result bundles."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

import numpy as np
import numpy.typing as npt

from .benchmark import Benchmark, QueryRecord, SamplingManifest
from .encoders import EncoderIdentity
from .metrics.coverage import CoverageValue
from .preprocessing import ParsedQuery
from .resolution import ResolvedTerms
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
)

BUNDLE_SCHEMA_VERSION = 1


def save_bundle(
    result: EvaluationResult, directory: Path, *, overwrite: bool = False
) -> None:
    if directory.exists():
        if not overwrite:
            raise FileExistsError(f"bundle already exists: {directory}")
        shutil.rmtree(directory)
    arrays = directory / "arrays"
    evidence = directory / "evidence"
    arrays.mkdir(parents=True)
    evidence.mkdir()

    array_files: dict[str, str] = {}
    semantic = result.diversity.semantic
    if semantic is not None:
        _save_array(arrays / "embeddings.npy", semantic.embeddings)
        array_files["embeddings"] = "arrays/embeddings.npy"
    for name, array in (
        ("operator_counts", result.complexity.operator_counts),
        ("row_counts", result.complexity.row_counts),
        ("column_counts", result.complexity.column_counts),
    ):
        if array is not None:
            _save_array(arrays / f"{name}.npy", array)
            array_files[name] = f"arrays/{name}.npy"

    _write_json(directory / "metrics.json", _metrics_payload(result))
    _write_json_lines(
        directory / "queries.jsonl", (_query_payload(query) for query in result.queries)
    )
    _write_json_lines(
        directory / "diagnostics.jsonl",
        (_diagnostic_payload(diagnostic) for diagnostic in result.diagnostics),
    )
    _write_json_lines(
        directory / "redundancy_pairs.jsonl",
        (
            asdict(pair)
            for pair in (result.redundancy.pairs if result.redundancy else ())
        ),
    )
    _write_json(
        evidence / "ontology.json",
        {
            "fingerprint": result.provenance.get("ontology_fingerprint"),
            "classes": sorted(result.coverage.class_universe),
            "properties": sorted(result.coverage.property_universe),
        },
    )

    files = sorted(
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file()
    )
    checksums = {name: _sha256(directory / name) for name in files}
    benchmark = result.benchmark
    manifest = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "benchmark": {
            "name": benchmark.name,
            "normalization": benchmark.normalization,
            "source_path": benchmark.source_path,
            "source_checksum": benchmark.source_checksum,
            "records": [asdict(record) for record in benchmark.records],
            "sampling": asdict(benchmark.sampling) if benchmark.sampling else None,
        },
        "metric_status": dict(result.metric_status),
        "provenance": _json_value(result.provenance),
        "arrays": array_files,
        "files": checksums,
    }
    _write_json(directory / "manifest.json", manifest)


def load_bundle(directory: Path) -> EvaluationResult:
    manifest = _read_json(directory / "manifest.json")
    if manifest.get("bundle_schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported bundle schema version")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise TypeError("bundle manifest has no file checksums")
    for filename, expected in files.items():
        path = directory / filename
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"bundle checksum mismatch: {filename}")

    benchmark_data = _mapping(manifest["benchmark"])
    sampling_data = benchmark_data.get("sampling")
    sampling = (
        SamplingManifest(
            seed=_int(_mapping(sampling_data)["seed"]),
            source_size=_int(_mapping(sampling_data)["source_size"]),
            selected_ids=_string_tuple(_mapping(sampling_data)["selected_ids"]),
        )
        if sampling_data is not None
        else None
    )
    benchmark = Benchmark(
        records=tuple(
            QueryRecord(
                id=str(_mapping(record)["id"]),
                question=str(_mapping(record)["question"]),
                sparql=str(_mapping(record)["sparql"]),
                source_line=_int(_mapping(record)["source_line"]),
            )
            for record in _list(benchmark_data["records"])
        ),
        name=str(benchmark_data["name"]),
        normalization=cast(
            Literal["standard", "qald9"], str(benchmark_data["normalization"])
        ),
        source_path=_optional_str(benchmark_data.get("source_path")),
        source_checksum=_optional_str(benchmark_data.get("source_checksum")),
        sampling=sampling,
    )
    metrics = _read_json(directory / "metrics.json")
    arrays = _mapping(manifest.get("arrays", {}))
    semantic_data = metrics.get("semantic")
    semantic = None
    if semantic_data is not None:
        semantic_mapping = _mapping(semantic_data)
        identity_data = dict(_mapping(semantic_mapping["encoder_identity"]))
        identity_data["library_versions"] = tuple(
            tuple(item) for item in identity_data["library_versions"]
        )
        semantic = SemanticDiversity(
            apd=_float_or_nan(semantic_mapping.get("apd")),
            vendi=_float_or_nan(semantic_mapping.get("vendi")),
            embeddings=cast(
                npt.NDArray[np.floating[Any]],
                _load_array(directory / str(arrays["embeddings"])),
            ),
            encoder_identity=EncoderIdentity(**identity_data),
        )
    structural_data = _mapping(metrics["structural"])
    structural = StructuralDiversity(
        unique_template_ratio=_optional_float(
            structural_data.get("unique_template_ratio")
        ),
        distinct_entities_per_query=_optional_float(
            structural_data.get("distinct_entities_per_query")
        ),
        filter_template_ratio=_optional_float(
            structural_data.get("filter_template_ratio")
        ),
        feature_entropy_bits=_optional_float(
            structural_data.get("feature_entropy_bits")
        ),
        feature_usage_pct=(
            MappingProxyType(
                {
                    str(key): float(value)
                    for key, value in _mapping(
                        structural_data["feature_usage_pct"]
                    ).items()
                }
            )
            if structural_data.get("feature_usage_pct") is not None
            else None
        ),
        filter_subtype_keys=_string_tuple(
            structural_data.get("filter_subtype_keys", [])
        ),
        distinct_classes_per_query=_optional_float(
            structural_data.get("distinct_classes_per_query")
        ),
        distinct_properties_per_query=_optional_float(
            structural_data.get("distinct_properties_per_query")
        ),
        class_richness=_optional_int(structural_data.get("class_richness")),
        property_richness=_optional_int(structural_data.get("property_richness")),
        entity_richness=_optional_int(structural_data.get("entity_richness")),
        class_mean_per_query=_optional_float(structural_data.get("class_mean_per_query")),
        property_mean_per_query=_optional_float(structural_data.get("property_mean_per_query")),
        entity_mean_per_query=_optional_float(structural_data.get("entity_mean_per_query")),
        class_hill_1=_optional_float(structural_data.get("class_hill_1")),
        property_hill_1=_optional_float(structural_data.get("property_hill_1")),
        entity_hill_1=_optional_float(structural_data.get("entity_hill_1")),
        class_hill_2=_optional_float(structural_data.get("class_hill_2")),
        property_hill_2=_optional_float(structural_data.get("property_hill_2")),
        entity_hill_2=_optional_float(structural_data.get("entity_hill_2")),
        class_evenness=_optional_float(structural_data.get("class_evenness")),
        property_evenness=_optional_float(structural_data.get("property_evenness")),
        entity_evenness=_optional_float(structural_data.get("entity_evenness")),
        distinct_entities=_string_frozenset(
            structural_data.get("distinct_entities", [])
        ),
    )
    complexity_data = _mapping(metrics["complexity"])
    complexity = ComplexityResult(
        operator_counts=_optional_int_array(directory, arrays, "operator_counts"),
        row_counts=_optional_int_array(directory, arrays, "row_counts"),
        column_counts=_optional_int_array(directory, arrays, "column_counts"),
        operator_count_std=_optional_float_or_nan(
            complexity_data.get("operator_count_std")
        ),
        row_count_std=_optional_float_or_nan(complexity_data.get("row_count_std")),
        column_count_std=_optional_float_or_nan(
            complexity_data.get("column_count_std")
        ),
        execution_status=_string_tuple(complexity_data.get("execution_status", [])),
        observation_ids=_optional_string_tuple(
            complexity_data.get("observation_ids", [])
        ),
    )
    coverage_data = _mapping(metrics["coverage"])
    coverage = CoverageResult(
        classes=_coverage_value(coverage_data.get("classes")),
        properties=_coverage_value(coverage_data.get("properties")),
        features=_coverage_value(coverage_data.get("features")),
        class_universe=_string_frozenset(coverage_data.get("class_universe", [])),
        property_universe=_string_frozenset(coverage_data.get("property_universe", [])),
        covered_classes=_string_frozenset(coverage_data.get("covered_classes", [])),
        covered_properties=_string_frozenset(
            coverage_data.get("covered_properties", [])
        ),
    )
    queries = tuple(
        _query_from_payload(payload)
        for payload in _read_json_lines(directory / "queries.jsonl")
    )
    diagnostics = tuple(
        Diagnostic(**payload)
        for payload in _read_json_lines(directory / "diagnostics.jsonl")
    )
    redundancy = _redundancy_from_payload(
        metrics.get("redundancy"),
        _read_json_lines(directory / "redundancy_pairs.jsonl"),
    )
    return EvaluationResult(
        benchmark=benchmark,
        diversity=DiversityResult(semantic=semantic, structural=structural),
        complexity=complexity,
        coverage=coverage,
        redundancy=redundancy,
        queries=queries,
        metric_status=MappingProxyType(
            {
                str(key): cast(MetricStatus, value)
                for key, value in _mapping(manifest["metric_status"]).items()
            }
        ),
        diagnostics=diagnostics,
        provenance=MappingProxyType(dict(_mapping(manifest["provenance"]))),
    )


def _metrics_payload(result: EvaluationResult) -> dict[str, object]:
    structural = result.diversity.structural
    complexity = result.complexity
    coverage = result.coverage
    return {
        "semantic": (
            {
                "apd": _finite(result.diversity.semantic.apd),
                "vendi": _finite(result.diversity.semantic.vendi),
                "encoder_identity": _json_value(
                    asdict(result.diversity.semantic.encoder_identity)
                ),
            }
            if result.diversity.semantic is not None
            else None
        ),
        "structural": {
            "unique_template_ratio": structural.unique_template_ratio,
            "distinct_entities_per_query": structural.distinct_entities_per_query,
            "filter_template_ratio": structural.filter_template_ratio,
            "feature_entropy_bits": structural.feature_entropy_bits,
            "feature_usage_pct": _json_value(structural.feature_usage_pct),
            "filter_subtype_keys": list(structural.filter_subtype_keys),
            "distinct_classes_per_query": structural.distinct_classes_per_query,
            "distinct_properties_per_query": structural.distinct_properties_per_query,
            "class_richness": structural.class_richness,
            "property_richness": structural.property_richness,
            "entity_richness": structural.entity_richness,
            "class_mean_per_query": structural.class_mean_per_query,
            "property_mean_per_query": structural.property_mean_per_query,
            "entity_mean_per_query": structural.entity_mean_per_query,
            "class_hill_1": structural.class_hill_1,
            "property_hill_1": structural.property_hill_1,
            "entity_hill_1": structural.entity_hill_1,
            "class_hill_2": structural.class_hill_2,
            "property_hill_2": structural.property_hill_2,
            "entity_hill_2": structural.entity_hill_2,
            "class_evenness": structural.class_evenness,
            "property_evenness": structural.property_evenness,
            "entity_evenness": structural.entity_evenness,
            "distinct_entities": sorted(structural.distinct_entities),
        },
        "complexity": {
            "operator_count_std": _finite(complexity.operator_count_std),
            "row_count_std": _finite(complexity.row_count_std),
            "column_count_std": _finite(complexity.column_count_std),
            "execution_status": list(complexity.execution_status),
            "observation_ids": list(complexity.observation_ids),
        },
        "coverage": {
            "classes": asdict(coverage.classes) if coverage.classes else None,
            "properties": asdict(coverage.properties) if coverage.properties else None,
            "features": asdict(coverage.features) if coverage.features else None,
            "class_universe": sorted(coverage.class_universe),
            "property_universe": sorted(coverage.property_universe),
            "covered_classes": sorted(coverage.covered_classes),
            "covered_properties": sorted(coverage.covered_properties),
        },
        "redundancy": (
            {key: asdict(value) for key, value in result.redundancy.features.items()}
            if result.redundancy
            else None
        ),
    }


def _query_payload(query: QueryAnalysis) -> dict[str, object]:
    return {
        "record": asdict(query.record),
        "evaluation_index": query.evaluation_index,
        "normalized_sparql": query.normalized_sparql,
        "parsed": asdict(query.parsed) if query.parsed else None,
        "terms": asdict(query.terms) if query.terms else None,
        "raw_features": _json_value(query.raw_features),
        "execution_features": _json_value(query.execution_features),
        "template": query.template,
        "filter_templates": query.filter_templates,
        "filter_subtypes": sorted(query.filter_subtypes)
        if query.filter_subtypes
        else [],
    }


def _query_from_payload(payload: Mapping[str, object]) -> QueryAnalysis:
    record_data = _mapping(payload["record"])
    parsed_data = payload.get("parsed")
    terms_data = payload.get("terms")
    parsed = None
    if parsed_data is not None:
        values = _mapping(parsed_data)
        parsed = ParsedQuery(
            num_triples=_int(values["num_triples"]),
            variables=_string_frozenset(values["variables"]),
            raw_entities=_string_tuple(values["raw_entities"]),
            literals=_string_tuple(values["literals"]),
            syntactic_classes=_string_frozenset(values["syntactic_classes"]),
            properties=_string_frozenset(values["properties"]),
            parse_status=cast(Literal["ok", "failed"], str(values["parse_status"])),
            error=_optional_str(values.get("error")),
        )
    terms = None
    if terms_data is not None:
        values = _mapping(terms_data)
        terms = ResolvedTerms(
            entities=_string_tuple(values["entities"]),
            classes=_string_frozenset(values["classes"]),
            evidence_ids=_string_tuple(values["evidence_ids"]),
            degraded=bool(values["degraded"]),
        )
    return QueryAnalysis(
        record=QueryRecord(
            id=str(record_data["id"]),
            question=str(record_data["question"]),
            sparql=str(record_data["sparql"]),
            source_line=_int(record_data["source_line"]),
        ),
        evaluation_index=_int(payload["evaluation_index"]),
        normalized_sparql=str(payload["normalized_sparql"]),
        parsed=parsed,
        terms=terms,
        raw_features=_optional_int_mapping(payload.get("raw_features")),
        execution_features=_optional_int_mapping(payload.get("execution_features")),
        template=_optional_str(payload.get("template")),
        filter_templates=(
            _string_tuple(payload["filter_templates"])
            if payload.get("filter_templates") is not None
            else None
        ),
        filter_subtypes=_string_frozenset(payload.get("filter_subtypes", [])),
    )


def _redundancy_from_payload(
    summary: object, pairs: list[dict[str, Any]]
) -> RedundancyResult | None:
    if summary is None:
        return None
    features = {
        str(key): RedundancyFeatureResult(**_mapping(value))
        for key, value in _mapping(summary).items()
    }
    return RedundancyResult(
        features=MappingProxyType(features),
        pairs=tuple(RedundancyPair(**pair) for pair in pairs),
    )


def _diagnostic_payload(diagnostic: Diagnostic) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "stage": diagnostic.stage,
        "message": diagnostic.message,
        "query_id": diagnostic.query_id,
        "source": diagnostic.source,
        "source_line": diagnostic.source_line,
        "evaluation_index": diagnostic.evaluation_index,
        "endpoint_identity": _json_value(diagnostic.endpoint_identity),
        "fallback_contribution": diagnostic.fallback_contribution,
    }


def _save_array(path: Path, array: npt.NDArray[np.generic]) -> None:
    with path.open("wb") as stream:
        np.save(stream, array, allow_pickle=False)


def _load_array(path: Path) -> npt.NDArray[np.generic]:
    array = cast(npt.NDArray[np.generic], np.load(path, allow_pickle=False))
    array.setflags(write=False)
    return array


def _optional_int_array(
    directory: Path, arrays: Mapping[str, object], name: str
) -> npt.NDArray[np.int64] | None:
    path = arrays.get(name)
    if path is None:
        return None
    return cast(npt.NDArray[np.int64], _load_array(directory / str(path)))


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            _json_value(value),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_json_lines(path: Path, values: Iterable[object]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for value in values:
            stream.write(
                json.dumps(
                    _json_value(value),
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("bundle field must be an object")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("bundle field must be an array")
    return value


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else _float(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _float_or_nan(value: object) -> float:
    return math.nan if value is None else _float(value)


def _optional_float_or_nan(value: object) -> float | None:
    return None if value is None else _float(value)


def _coverage_value(value: object) -> CoverageValue | None:
    return CoverageValue(**_mapping(value)) if value is not None else None


def _optional_int_mapping(value: object) -> Mapping[str, int] | None:
    if value is None:
        return None
    return MappingProxyType(
        {str(key): _int(item) for key, item in _mapping(value).items()}
    )


def _int(value: object) -> int:
    if not isinstance(value, (str, int, float)):
        raise TypeError("bundle field must be numeric")
    return int(value)


def _float(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise TypeError("bundle field must be numeric")
    return float(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in _list(value))


def _optional_string_tuple(value: object) -> tuple[str | None, ...]:
    return tuple(None if item is None else str(item) for item in _list(value))


def _string_frozenset(value: object) -> frozenset[str]:
    return frozenset(str(item) for item in _list(value))


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_value(item) for item in sorted(value)]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value
