import re
import os
import sys
import numpy as np
from collections import defaultdict
import rdflib
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.term import URIRef, Variable, Literal

try:
    from querybloom.executor.sparql_executor import execute_sparql_query
except Exception:
    execute_sparql_query = None

# Cache for entity class lookups to avoid duplicate SPARQL round-trips
_ENTITY_TYPE_CACHE = {}


def _normalize_uri_escapes(sparql):
    """Remove SPARQL-style backslash escapes inside angle-bracket URIs."""
    return re.sub(
        r"<([^>]*)>",
        lambda m: "<" + re.sub(r"\\([!'()*+,;=:/?#@$_\-.~])", r"\1", m.group(1)) + ">",
        sparql,
    )


def get_entity_classes(entity_uri, endpoint="dblp"):
    if not execute_sparql_query:
        return set()

    entity_uri = _normalize_uri_escapes(f"<{entity_uri}>")[1:-1]

    if entity_uri in _ENTITY_TYPE_CACHE:
        return _ENTITY_TYPE_CACHE[entity_uri]

    query = f"SELECT DISTINCT ?t WHERE {{ <{entity_uri}> a ?t }}"
    try:
        res = execute_sparql_query(query, endpoint=endpoint)
        if res.get("success") and res.get("results"):
            classes = set(r["t"]["value"] for r in res["results"] if "t" in r)
            _ENTITY_TYPE_CACHE[entity_uri] = classes
            return classes
    except Exception:
        pass

    _ENTITY_TYPE_CACHE[entity_uri] = set()
    return set()


def get_query_body(sparql):
    """Isolate the query body without PREFIX definitions to focus on the pattern."""
    return re.sub(r"PREFIX.*?\n", "", sparql, flags=re.IGNORECASE).strip()


def analyze_sparql_features(sparql):
    """Check for the presence of exact SPARQL 1.1 structural features."""
    upper_sparql = sparql.upper()
    body = get_query_body(sparql)
    upper_body = body.upper()

    # 0. Query form
    has_select = 1 if re.search(r"\bSELECT\b", upper_sparql) else 0
    has_ask = 1 if re.search(r"\bASK\b", upper_sparql) else 0

    # 1. Structural features
    has_optional = 1 if "OPTIONAL" in upper_body else 0
    has_union = 1 if "UNION" in upper_body else 0
    has_minus = 1 if "MINUS" in upper_body else 0
    has_filter = 1 if "FILTER" in upper_body else 0

    # 2. Aggregations & Grouping
    has_groupby = 1 if "GROUP BY" in upper_body else 0
    has_count = 1 if "COUNT(" in upper_body else 0

    # 3. Modifiers
    has_orderby = 1 if "ORDER BY" in upper_body else 0
    has_limit = 1 if "LIMIT" in upper_body else 0

    # 4. Property Paths (complex paths using *, +, |, /)
    sanitized = re.sub(r"<[^>]+>", "URI", body)
    sanitized = re.sub(r'".*?"(\^\^<.*?>)?', "LITERAL", sanitized)
    has_property_path = (
        1 if re.search(r"(:[a-zA-Z0-9_]+|URI)[\s]*[\*\+\|\/]", sanitized) else 0
    )

    # 5. EXISTS / NOT EXISTS
    has_exists = 1 if re.search(r"\bEXISTS\b", upper_body) else 0

    return {
        "SELECT": has_select,
        "ASK": has_ask,
        "OPTIONAL": has_optional,
        "UNION": has_union,
        "FILTER": has_filter,
        "EXISTS": has_exists,
        "GROUP BY": has_groupby,
        "ORDER BY": has_orderby,
        "LIMIT": has_limit,
        "Property Paths": has_property_path,
    }


def analyze_query_size(sparql, endpoint="dblp"):
    """Analyze the exact size of the query in variables and triples using rdflib."""
    metrics = parse_and_extract_rdflib_metrics(sparql, endpoint)
    return {
        "num_variables": len(metrics["variables"]),
        "num_triples": metrics["num_triples"],
        "num_classes": len(metrics["classes"]),
    }


def parse_and_extract_rdflib_metrics(sparql, endpoint="dblp"):
    """Uses rdflib to accurately parse entities, properties, variables, and triple count."""
    sparql = _normalize_uri_escapes(sparql)

    metrics = {
        "num_triples": 0,
        "variables": set(),
        "entities": [],
        "classes": set(),
        "properties": set(),
    }

    try:
        parsed = parseQuery(sparql)
        algebra = translateQuery(parsed).algebra
    except Exception:
        # Fallback for completely malformed queries, though benchmark queries should parse
        return metrics

    def walk_algebra(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "triples" and v is not None:
                    # Count each exact triple pattern
                    metrics["num_triples"] += len(v)
                    for triple in v:
                        s, p, o = triple[:3]

                        if str(
                            p
                        ) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" and isinstance(
                            o, URIRef
                        ):
                            metrics["classes"].add(str(o))

                        # Process Subject and Object as Entities/Variables/Literals
                        for term in [s, o]:
                            if isinstance(term, URIRef) or isinstance(term, Literal):
                                metrics["entities"].append(str(term))
                            elif isinstance(term, Variable):
                                metrics["variables"].add(str(term))

                        # Process Predicate as Property/Variable
                        if isinstance(p, URIRef):
                            metrics["properties"].add(str(p))
                        elif isinstance(p, Variable):
                            metrics["variables"].add(str(p))
                else:
                    walk_algebra(v)
        elif isinstance(node, list):
            for item in node:
                walk_algebra(item)

    walk_algebra(algebra)

    # Dynamically resolve types of any specific entity instances found
    for entity in set(metrics["entities"]):
        if entity.startswith("http"):  # Only query valid URIs
            entity_classes = get_entity_classes(entity, endpoint)
            metrics["classes"].update(entity_classes)

    # At least 1 triple if parsed successfully but somehow missed
    metrics["num_triples"] = max(1, metrics["num_triples"])
    return metrics


def aggregate_sparql_metrics(queries):
    """Aggregate all objective SPARQL features across queries."""
    if not queries:
        return {}

    feature_metrics = defaultdict(list)
    size_metrics = defaultdict(list)

    unique_entities = set()
    total_entities_count = 0
    unique_relations = set()
    unique_classes = set()

    for q in queries:
        features = analyze_sparql_features(q)
        for k, v in features.items():
            feature_metrics[k].append(v)

        rdflib_metrics = parse_and_extract_rdflib_metrics(q)

        # We can extract the sizes directly now
        size_metrics["num_variables"].append(len(rdflib_metrics["variables"]))
        size_metrics["num_triples"].append(rdflib_metrics["num_triples"])
        size_metrics["num_classes"].append(len(rdflib_metrics["classes"]))

        unique_entities.update(rdflib_metrics["entities"])
        total_entities_count += len(rdflib_metrics["entities"])
        unique_relations.update(rdflib_metrics["properties"])
        unique_classes.update(rdflib_metrics["classes"])

    agg = {}

    # Features are binary, so the mean is the percentage (ratio) of queries containing that feature.
    for feature_name, v_list in feature_metrics.items():
        # Convert to percentage
        agg[f"feat_{feature_name}"] = round(float(np.mean(v_list) * 100), 1)

    for size_name, v_list in size_metrics.items():
        agg[f"{size_name}_mean"] = round(float(np.mean(v_list)), 2)
        agg[f"{size_name}_median"] = round(float(np.median(v_list)), 2)
        agg[f"{size_name}_std"] = round(float(np.std(v_list)), 2)

    # Template uniqueness
    templates = []
    for q in queries:
        body = get_query_body(q)
        body = re.sub(r"\?[a-zA-Z0-9_]+", "?VAR", body)
        body = re.sub(r"<[^>]+>", "<URI>", body)
        body = re.sub(r'".*?"(\^\^<.*?>)?|[\'0-9]+', "<LITERAL>", body)
        body = re.sub(r"\b[a-zA-Z0-9_]+:[a-zA-Z0-9_]+\b", "PREFIX:NAME", body)
        templates.append(body.strip())

    agg["unique_templates_ratio"] = round(len(set(templates)) / len(queries), 3)
    agg["num_unique_entities"] = len(unique_entities)
    agg["num_total_entities"] = total_entities_count
    agg["unique_to_total_entities_ratio"] = (
        round(len(unique_entities) / total_entities_count, 3)
        if total_entities_count > 0
        else 0
    )
    agg["entities_per_query"] = (
        round(total_entities_count / len(queries), 3) if len(queries) > 0 else 0
    )
    agg["num_unique_relations"] = len(unique_relations)
    agg["num_unique_classes"] = len(unique_classes)

    return agg


def measure_syntactic_diversity(data1, data2):
    """
    Measure rigorous objective SPARQL diversity across two benchmarks.
    """
    queries1 = [item.get("sparql", "") for item in data1 if "sparql" in item]
    queries2 = [item.get("sparql", "") for item in data2 if "sparql" in item]

    return {
        "benchmark1": aggregate_sparql_metrics(queries1),
        "benchmark2": aggregate_sparql_metrics(queries2),
        "bm1_size": len(queries1),
        "bm2_size": len(queries2),
    }
