"""Comprehensiveness metrics: class, property, and feature coverage."""

import numpy as np

from ._cache import disk_cache

from .parsing import (
    analyze_sparql_features,
    parse_and_extract_rdflib_metrics,
    FEATURE_KEYS,
)

# absolute import — ontology_loader sits one level above this package,
# on the same sys.path the notebook uses (the analyze/ directory).
from ontology_loader import load_ontology_classes, load_ontology_properties


def class_coverage(queries, kg_name, endpoint="dblp", kgs_data_dir=None):
    """Fraction of ontology classes exercised by the benchmark queries.

    Returns:
        (ratio, benchmark_count, ontology_count)
    """
    benchmark_classes = set()
    for q in queries:
        m = parse_and_extract_rdflib_metrics(q, endpoint)
        benchmark_classes.update(m["classes"])

    ontology_classes = load_ontology_classes(kg_name, kgs_data_dir)
    if not ontology_classes:
        return 0.0, len(benchmark_classes), 0
    # Only count classes that are actually in the KG ontology (exclude
    # meta-level URIs like owl:Class, rdfs:Class leaked by entity-type
    # resolution).
    benchmark_classes = benchmark_classes & ontology_classes
    ratio = len(benchmark_classes) / len(ontology_classes)
    return round(ratio, 4), len(benchmark_classes), len(ontology_classes)


def property_coverage(queries, kg_name, endpoint="dblp", kgs_data_dir=None):
    """Fraction of ontology properties exercised by the benchmark queries.

    Returns:
        (ratio, benchmark_count, ontology_count)
    """
    benchmark_props = set()
    for q in queries:
        m = parse_and_extract_rdflib_metrics(q, endpoint)
        benchmark_props.update(m["properties"])

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


@disk_cache("comprehensiveness")
def measure_comprehensiveness(queries, kg_name, endpoint="dblp", kgs_data_dir=None):
    """Compute all comprehensiveness metrics for one benchmark.

    Returns:
        dict with scalar ratios and raw counts.
    """
    cc, cc_bench, cc_onto = class_coverage(queries, kg_name, endpoint, kgs_data_dir)
    pc, pc_bench, pc_onto = property_coverage(queries, kg_name, endpoint, kgs_data_dir)
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
