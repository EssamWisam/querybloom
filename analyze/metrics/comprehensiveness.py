"""Comprehensiveness metrics: class, property, and feature coverage."""

import numpy as np

from ._cache import disk_cache

from .parsing import (
    analyze_sparql_features,
    parse_and_extract_rdflib_metrics,
    resolve_terms,
    FEATURE_KEYS,
)

# absolute import — ontology_loader sits one level above this package,
# on the same sys.path the notebook uses (the analyze/ directory).
from ontology_loader import load_ontology_classes, load_ontology_properties


def gather_coverage_sets(
    queries, endpoint="dblp", kg_name=None, kgs_data_dir=None, query_source=None
):
    """Pool properties and classes referenced by the benchmark queries."""
    ontology_classes = (
        load_ontology_classes(kg_name, kgs_data_dir) if kg_name else set()
    )
    classes, properties = set(), set()
    for query_index, query in enumerate(queries, start=1):
        metrics = parse_and_extract_rdflib_metrics(
            query, endpoint, query_source, query_index
        )
        resolve_terms(
            metrics,
            endpoint,
            kg_name,
            kgs_data_dir,
            query_source,
            query_index,
            ontology_classes,
        )
        classes.update(metrics["classes"])
        properties.update(metrics["properties"])
    return classes, properties


def class_coverage(
    queries, kg_name, endpoint="dblp", kgs_data_dir=None, query_source=None
):
    """Fraction of ontology classes exercised by the benchmark queries.

    Returns:
        (ratio, benchmark_count, ontology_count)
    """
    benchmark_classes, _ = gather_coverage_sets(
        queries, endpoint, kg_name, kgs_data_dir, query_source
    )

    ontology_classes = load_ontology_classes(kg_name, kgs_data_dir)
    if not ontology_classes:
        return 0.0, len(benchmark_classes), 0
    # Only count classes that are actually in the KG ontology (exclude
    # meta-level URIs like owl:Class, rdfs:Class leaked by entity-type
    # resolution).
    benchmark_classes = benchmark_classes & ontology_classes
    ratio = len(benchmark_classes) / len(ontology_classes)
    return round(ratio, 4), len(benchmark_classes), len(ontology_classes)


def property_coverage(
    queries, kg_name, endpoint="dblp", kgs_data_dir=None, query_source=None
):
    """Fraction of ontology properties exercised by the benchmark queries.

    Returns:
        (ratio, benchmark_count, ontology_count)
    """
    benchmark_props = set()
    for query_index, query in enumerate(queries, start=1):
        metrics = parse_and_extract_rdflib_metrics(
            query, endpoint, query_source, query_index
        )
        benchmark_props.update(metrics["properties"])

    ontology_props = load_ontology_properties(kg_name, kgs_data_dir)
    if not ontology_props:
        return 0.0, len(benchmark_props), 0
    # Only count properties that are actually in the KG ontology (exclude
    # meta-level URIs like rdf:type leaked by parsing).
    benchmark_props = benchmark_props & ontology_props
    ratio = len(benchmark_props) / len(ontology_props)
    return round(ratio, 4), len(benchmark_props), len(ontology_props)


def feature_coverage(queries):
    """Fraction of tracked SPARQL 1.1 features used at least once in the benchmark.

    Returns:
        (ratio, used_count, total_tracked)
    """
    used = set()
    for q in queries:
        feats = analyze_sparql_features(q)
        for k, v in feats.items():
            if v:
                used.add(k)
    total = len(FEATURE_KEYS)
    return round(len(used) / total, 4), len(used), total


@disk_cache("comprehensiveness_v4")
def measure_comprehensiveness(
    queries,
    kg_name,
    endpoint="dblp",
    kgs_data_dir=None,
    rewrite_cache=False,
    query_source=None,
):
    """Compute all comprehensiveness metrics for one benchmark.

    Set ``rewrite_cache=True`` to recompute and replace the matching disk cache.

    Returns:
        dict with scalar ratios and raw counts.
    """
    cc, cc_bench, cc_onto = class_coverage(
        queries, kg_name, endpoint, kgs_data_dir, query_source
    )
    pc, pc_bench, pc_onto = property_coverage(
        queries, kg_name, endpoint, kgs_data_dir, query_source
    )
    fc, fc_used, fc_total = feature_coverage(queries)

    n_queries = len(queries)
    return {
        "class_coverage": cc,
        "class_coverage_raw": f"{cc_bench}/{cc_onto}",
        "property_coverage": pc,
        "property_coverage_raw": f"{pc_bench}/{pc_onto}",
        "feature_coverage": fc,
        "feature_coverage_raw": f"{fc_used}/{fc_total}",
        "n_queries": n_queries,
        "n_bench_classes": cc_bench,
        "n_bench_properties": pc_bench,
    }
