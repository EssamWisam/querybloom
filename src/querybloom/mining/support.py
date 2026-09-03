"""SPARQL support calculation and label lookup utilities for subgraph mining."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from querybloom.executor.sparql_executor import execute_sparql_query as execute
from querybloom.mining.constraints import parallel_edge_pairs
from querybloom.mining.utils import extract_binding_rows


def get_support(
    endpoint: str,
    types: Set[str],
    edges: List[Tuple[str, str, str]],
    timeout: int = 10,
    pbar: Any = None,
    limit: Optional[int] = None,
) -> int:
    """
    Returns the number of instances matching the subgraph pattern.
    Handles both entity-to-entity edges and entity-to-literal (attribute) edges.
    """
    sorted_types = sorted(list(types))
    type_to_var = {t: f"?v{i}" for i, t in enumerate(sorted_types)}

    clauses = []
    # Type constraints
    for t, var in type_to_var.items():
        clauses.append(f"{var} a <{t}> .")

    edge_data = [{"s": s, "p": p, "o": o} for s, p, o in edges]

    # Structure constraints
    for s, p, o in edges:
        v_s = type_to_var[s]

        # Check if this is an attribute edge (object is a datatype, not an entity type)
        if o not in type_to_var:
            # Attribute edge: entity -> literal
            clauses.append(f"{v_s} <{p}> ?literalValue{len(clauses)} .")
        else:
            # Regular edge: entity -> entity
            v_o = type_to_var[o]
            clauses.append(f"{v_s} <{p}> {v_o} .")

    for left_index, right_index in parallel_edge_pairs(edge_data):
        left_target = edge_data[left_index]["o"]
        right_target = edge_data[right_index]["o"]
        if left_target in type_to_var and right_target in type_to_var:
            clauses.append(
                f"FILTER({type_to_var[left_target]} != {type_to_var[right_target]})"
            )

    query_body = "\n".join(clauses)

    if limit is not None:
        # Optimization: Use LIMIT inner query to stop early
        query = f"""
         SELECT (COUNT(*) as ?count) WHERE {{
             {{
                 SELECT * WHERE {{
                     {query_body}
                 }} LIMIT {limit}
             }}
         }}
         """
    else:
        query = f"""
         SELECT (COUNT(*) as ?count) WHERE {{
             {query_body}
         }}
         """

    res = execute(query, endpoint=endpoint, timeout=timeout)

    if not res.get("success"):
        if pbar is not None:
            pbar.write(f"  [Skipped] Timeout or Error ({timeout}s)")
        return 0

    try:
        bindings = res.get("results", [])
        val = None
        if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
            records = bindings.to_dict("records")
            if records:
                val = records[0].get("count")
        elif isinstance(bindings, list) and bindings:
            val = bindings[0].get("count", {}).get("value") if isinstance(bindings[0], dict) and isinstance(bindings[0].get("count"), dict) else bindings[0].get("count")
        elif isinstance(bindings, dict) and "results" in bindings and "bindings" in bindings["results"]:
            if bindings["results"]["bindings"]:
                val = bindings["results"]["bindings"][0].get("count", {}).get("value")

        if val is not None:
            return int(val)
    except Exception:
        pass

    return 0


def get_type_label(
    endpoint: str,
    type_uri: str,
    abstat_labels: Optional[Dict[str, str]] = None,
    timeout: int = 10,
) -> Optional[str]:
    """
    Get the rdfs:label for a type URI from cache or knowledge graph.
    """
    if abstat_labels and type_uri in abstat_labels:
        return abstat_labels[type_uri]

    query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?label WHERE {{
        <{type_uri}> rdfs:label ?label .
        FILTER(LANG(?label) = "en" || LANG(?label) = "")
    }}
    ORDER BY DESC(LANG(?label) = "en")
    LIMIT 1
    """

    res = execute(query, endpoint=endpoint, timeout=timeout)

    if res.get("success"):
        bindings = res.get("results", [])
        if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
            records = bindings.to_dict("records")
            if records:
                return records[0].get("label")
        elif isinstance(bindings, list) and bindings:
            lbl = bindings[0].get("label")
            if isinstance(lbl, dict):
                return lbl.get("value")
            return lbl
        elif isinstance(bindings, dict) and "results" in bindings:
            if bindings["results"].get("bindings"):
                return bindings["results"]["bindings"][0].get("label", {}).get("value")

    return None


def get_entity_labels(
    endpoint: str,
    entity_uris: List[str],
    timeout: int = 10,
) -> Dict[str, str]:
    """Batch fetch rdfs:labels for entity URIs."""
    if not entity_uris:
        return {}

    unique_uris = list(dict.fromkeys(uri for uri in entity_uris if uri))
    values_clause = " ".join(f"<{uri}>" for uri in unique_uris)
    query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?entity ?label WHERE {{
        VALUES ?entity {{ {values_clause} }}
        OPTIONAL {{
            ?entity rdfs:label ?label .
            FILTER(LANG(?label) = "en" || LANG(?label) = "")
        }}
    }}
    """

    res = execute(query, endpoint=endpoint, timeout=timeout)
    label_map: Dict[str, str] = {}
    if not res.get("success"):
        return label_map

    for row in extract_binding_rows(res):
        uri = row.get("entity")
        label = row.get("label")
        if uri and label:
            label_map.setdefault(uri, label)
    return label_map
