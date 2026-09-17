"""Entity sampling and subgraph instance grounding."""

from __future__ import annotations

import random
from collections import defaultdict
from math import ceil
from typing import Any, Dict, List, Optional, Set

from querybloom.executor.sparql_executor import execute_sparql_query as execute
from querybloom.mining.attributes import get_attribute_values
from querybloom.mining.constraints import parallel_edge_pairs
from querybloom.mining.support import get_entity_labels
from querybloom.mining.utils import extract_binding_rows


_TERM_TYPES_KEY = "__term_types__"


def _row_binding_is_uri(row: Dict[str, Any], variable: str) -> bool:
    return row.get(_TERM_TYPES_KEY, {}).get(variable, "uri") == "uri"


def sample_entities_for_type(
    endpoint: str,
    type_uri: str,
    type_count_cache: Dict[str, int],
    m: int = 5,
    timeout: int = 60,
) -> List[Dict[str, str]]:
    """
    Sample m entities of a given type from the knowledge graph.
    Returns a list of dicts with 'uri' and optionally 'label'.
    """
    def _extract_entity_uris(result: Dict[str, Any]) -> List[str]:
        uris = []
        bindings = result.get("results", [])
        if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
            records = bindings.to_dict("records")
            for rec in records:
                uri = rec.get("entity")
                if uri:
                    uris.append(str(uri))
        elif isinstance(bindings, list):
            for b in bindings:
                if isinstance(b, dict):
                    val = b.get("entity")
                    if isinstance(val, dict):
                        uris.append(str(val.get("value", "")))
                    elif val:
                        uris.append(str(val))
        elif isinstance(bindings, dict) and "results" in bindings:
            for b in bindings["results"].get("bindings", []):
                uri = b.get("entity", {}).get("value", "")
                if uri:
                    uris.append(str(uri))
        return [u for u in uris if u]

    # COUNT + random OFFSET sampling
    if type_uri not in type_count_cache:
        count_query = f"""
        SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
            ?entity a <{type_uri}> .
        }}
        """
        count_res = execute(count_query, endpoint=endpoint, timeout=timeout)
        total = 0
        if count_res.get("success"):
            try:
                bindings = count_res.get("results", [])
                if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
                    total = int(bindings.to_dict("records")[0].get("count", 0))
                elif isinstance(bindings, list) and bindings:
                    val = bindings[0].get("count")
                    total = int(val.get("value", 0)) if isinstance(val, dict) else int(val or 0)
                elif isinstance(bindings, dict) and "results" in bindings:
                    total = int(bindings["results"]["bindings"][0]["count"]["value"])
            except Exception:
                total = 0
        type_count_cache[type_uri] = total

    total = type_count_cache[type_uri]
    offset = random.randint(0, max(0, total - m)) if total > m else 0

    primary_query = f"""
    SELECT DISTINCT ?entity WHERE {{
        ?entity a <{type_uri}> .
    }}
    LIMIT {m}
    OFFSET {offset}
    """
    res = execute(primary_query, endpoint=endpoint, timeout=timeout)

    if not res.get("success"):
        print(
            f"[sample_entities] Primary query failed for {type_uri}: "
            f"status={res.get('status')}, error={res.get('error')}"
        )

    entity_uris = _extract_entity_uris(res) if res.get("success") else []
    if not entity_uris:
        return []

    values_clause = " ".join(f"<{uri}>" for uri in entity_uris)
    labels_query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?entity ?lbl WHERE {{
        VALUES ?entity {{ {values_clause} }}
        ?entity rdfs:label ?lbl .
        FILTER(LANG(?lbl) = "en" || LANG(?lbl) = "")
    }}
    """

    labels_res = execute(labels_query, endpoint=endpoint, timeout=timeout)
    label_map: Dict[str, str] = {}
    if labels_res.get("success"):
        bindings = labels_res.get("results", [])
        if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
            records = bindings.to_dict("records")
            for rec in records:
                uri = rec.get("entity")
                label = rec.get("lbl")
                if uri and label:
                    label_map.setdefault(str(uri), str(label))
        elif isinstance(bindings, list):
            for b in bindings:
                if isinstance(b, dict):
                    uri = b.get("entity", {}).get("value", "") if isinstance(b.get("entity"), dict) else b.get("entity")
                    label = b.get("lbl", {}).get("value", "") if isinstance(b.get("lbl"), dict) else b.get("lbl")
                    if uri and label:
                        label_map.setdefault(str(uri), str(label))
        elif isinstance(bindings, dict) and "results" in bindings:
            for b in bindings["results"].get("bindings", []):
                uri = b.get("entity", {}).get("value", "")
                label = b.get("lbl", {}).get("value", "")
                if uri and label:
                    label_map.setdefault(str(uri), str(label))

    entities = []
    for uri in entity_uris:
        entity: Dict[str, str] = {"uri": uri}
        if uri in label_map:
            entity["label"] = label_map[uri]
        entities.append(entity)

    return entities


def _type_var_map(type_uris: List[str]) -> Dict[str, str]:
    return {type_uri: f"v{index}" for index, type_uri in enumerate(sorted(type_uris))}


def _edge_var_map(
    edges: List[Dict[str, Any]],
    type_to_var: Dict[str, str],
    optionalize: bool,
) -> List[tuple[Dict[str, Any], str, str]]:
    mapped = []
    for edge in edges:
        source_var = type_to_var[edge["s"]]
        target_var = type_to_var[edge["o"]]
        mapped.append((edge, source_var, target_var))
    return mapped


def build_instance_sparql(
    type_uris: List[str],
    edges: List[Dict[str, Any]],
    *,
    optionalize: bool,
    limit: int,
    excluded_values: Optional[Dict[str, Set[str]]] = None,
) -> str:
    """Build the SPARQL used to ground pattern instances."""
    type_to_var = _type_var_map(type_uris)
    source_types = {edge["s"] for edge in edges}
    clauses = [
        f"?{variable} a <{type_uri}> ."
        for type_uri, variable in type_to_var.items()
        if type_uri in source_types or not edges
    ]
    select_vars: List[str] = [
        type_to_var[type_uri]
        for type_uri in sorted(type_uris)
        if type_uri in source_types or not edges
    ]
    edge_vars = _edge_var_map(edges, type_to_var, optionalize)
    parallel_pairs = parallel_edge_pairs(edges)
    parallel_siblings: Dict[int, Set[int]] = {index: set() for index in range(len(edges))}
    for left_index, right_index in parallel_pairs:
        parallel_siblings[left_index].add(right_index)
        parallel_siblings[right_index].add(left_index)
    required_indices = [
        index
        for index, edge in enumerate(edges)
        if not (optionalize and edge.get("is_optional"))
    ]
    optional_indices = [
        index
        for index, edge in enumerate(edges)
        if optionalize and edge.get("is_optional")
    ]

    for index in required_indices:
        edge, source_var, target_var = edge_vars[index]
        triple = f"?{source_var} <{edge['p']}> ?{target_var} . ?{target_var} a <{edge['o']}> ."
        if target_var not in select_vars:
            select_vars.append(target_var)
        clauses.append(triple)

    for left_index, right_index in parallel_pairs:
        if left_index in required_indices and right_index in required_indices:
            left_target = edge_vars[left_index][2]
            right_target = edge_vars[right_index][2]
            clauses.append(f"FILTER(?{left_target} != ?{right_target})")

    processed_optional: List[int] = []
    for index in optional_indices:
        edge, source_var, target_var = edge_vars[index]
        triple = f"?{source_var} <{edge['p']}> ?{target_var} . ?{target_var} a <{edge['o']}> ."
        marker = f"opt{index}"
        select_vars.extend(var for var in (target_var, marker) if var not in select_vars)
        filters = []
        for sibling_index in sorted(parallel_siblings[index]):
            if sibling_index not in required_indices + processed_optional:
                continue
            other_target = edge_vars[sibling_index][2]
            if sibling_index in processed_optional:
                filters.append(
                    f"(!BOUND(?opt{sibling_index}) || ?{target_var} != ?{other_target})"
                )
            else:
                filters.append(f"(?{target_var} != ?{other_target})")
        filter_clause = f" FILTER({' && '.join(filters)})" if filters else ""
        clauses.append(
            f"OPTIONAL {{ {triple}{filter_clause} BIND(true AS ?{marker}) }}"
        )
        processed_optional.append(index)

    for variable, values in sorted((excluded_values or {}).items()):
        if values:
            iris = ", ".join(f"<{value}>" for value in sorted(values))
            clauses.append(f"FILTER(?{variable} NOT IN ({iris}))")

    return (
        f"SELECT DISTINCT {' '.join(f'?{var}' for var in select_vars)} WHERE {{ "
        f"{' '.join(clauses)} "
        f"}} LIMIT {limit}"
    )


def _instance_query(
    endpoint: str,
    type_uris: List[str],
    edges: List[Dict[str, Any]],
    *,
    optionalize: bool,
    timeout: int,
    limit: int,
    excluded_values: Optional[Dict[str, Set[str]]] = None,
) -> List[Dict[str, Any]]:
    query = build_instance_sparql(
        type_uris,
        edges,
        optionalize=optionalize,
        limit=limit,
        excluded_values=excluded_values,
    )
    res = execute(query, endpoint=endpoint, timeout=timeout)
    if not res.get("success"):
        print(
            "[instance_query] Failed to ground subgraph instances: "
            f"status={res.get('status')}, error={res.get('error')}"
        )
        return []
    rows = extract_binding_rows(res)
    bindings = res.get("results", [])
    if isinstance(bindings, list):
        for row, binding in zip(rows, bindings):
            term_types = {
                variable: value["type"]
                for variable, value in binding.items()
                if isinstance(value, dict) and value.get("type")
            }
            if term_types:
                row[_TERM_TYPES_KEY] = term_types
    elif isinstance(bindings, dict) and isinstance(bindings.get("bindings"), list):
        for row, binding in zip(rows, bindings["bindings"]):
            term_types = {
                variable: value["type"]
                for variable, value in binding.items()
                if isinstance(value, dict) and value.get("type")
            }
            if term_types:
                row[_TERM_TYPES_KEY] = term_types
    return rows


def _sample_instance_rows(
    endpoint: str,
    type_uris: List[str],
    edges: List[Dict[str, Any]],
    *,
    optionalize: bool,
    timeout: int,
    m: int,
    max_entity_reuse: int,
) -> List[Dict[str, Any]]:
    type_to_var = _type_var_map(type_uris)
    core_types = _core_type_uris(edges)
    core_variables = [type_to_var[type_uri] for type_uri in core_types]
    value_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    selected: List[Dict[str, Any]] = []
    seen: Set[tuple] = set()

    for _ in range(ceil(m / max_entity_reuse)):
        excluded_values = {
            variable: {
                value
                for value, count in value_counts[variable].items()
                if count >= max_entity_reuse
                and any(
                    row.get(variable) == value
                    and _row_binding_is_uri(row, variable)
                    for row in selected
                )
            }
            for variable in core_variables
        }
        rows = _instance_query(
            endpoint,
            type_uris,
            edges,
            optionalize=optionalize,
            timeout=timeout,
            limit=m,
            excluded_values=excluded_values,
        )
        added = 0
        for row in rows:
            key = _required_row_key(row, type_to_var, core_types)
            if not any(key) or key in seen:
                continue
            if any(
                row.get(variable)
                and value_counts[variable][row[variable]] >= max_entity_reuse
                for variable in core_variables
            ):
                continue
            seen.add(key)
            selected.append(row)
            added += 1
            for variable in core_variables:
                value = row.get(variable)
                if value:
                    value_counts[variable][value] += 1
            if len(selected) >= m:
                return selected
        if not added:
            break

    return selected


def _core_type_uris(edges: List[Dict[str, Any]]) -> Set[str]:
    core: Set[str] = set()
    for edge in edges:
        core.add(edge["s"])
        if not edge.get("is_optional"):
            core.add(edge["o"])
    return core


def _required_row_key(
    row: Dict[str, Any],
    type_to_var: Dict[str, str],
    core_types: Optional[Set[str]] = None,
) -> tuple:
    variables = [
        type_to_var[type_uri]
        for type_uri in type_to_var
        if core_types is None or type_uri in core_types
    ]
    return tuple(row.get(variable) for variable in variables)


def mixed_row_is_complete(row: Dict[str, Any], edges: List[Dict[str, Any]]) -> bool:
    """True when every optional edge is bound in a mixed OPTIONAL query row."""
    return all(
        row.get(f"opt{index}")
        for index, edge in enumerate(edges)
        if edge.get("is_optional")
    )


def select_sampled_rows(
    mixed_rows: List[Dict[str, Any]],
    full_rows: List[Dict[str, Any]],
    type_to_var: Dict[str, str],
    m: int,
    core_types: Optional[Set[str]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
    max_entity_reuse: Optional[int] = None,
) -> List[tuple[str, Dict[str, Any]]]:
    """Prefer one complete instance, then fill remaining slots from mixed rows."""
    selected: List[tuple[str, Dict[str, Any]]] = []
    seen: Set[tuple] = set()
    edges = edges or []
    variables = [
        type_to_var[type_uri]
        for type_uri in type_to_var
        if core_types is None or type_uri in core_types
    ]
    value_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def take(kind: str, rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            if len(selected) >= m:
                return
            key = _required_row_key(row, type_to_var, core_types)
            if not any(key) or key in seen:
                continue
            if max_entity_reuse is not None and any(
                row.get(variable)
                and value_counts[variable][row[variable]] >= max_entity_reuse
                for variable in variables
            ):
                continue
            seen.add(key)
            selected.append((kind, row))
            for variable in variables:
                value = row.get(variable)
                if value:
                    value_counts[variable][value] += 1

    complete_mixed = [row for row in mixed_rows if mixed_row_is_complete(row, edges)]
    if complete_mixed:
        take("mixed", complete_mixed[:1])
    elif full_rows:
        take("full", full_rows[:1])
    take("mixed", mixed_rows)
    take("full", full_rows)
    return selected


def sample_subgraph_instances(
    endpoint: str,
    subgraph: Dict[str, Any],
    type_label_cache: Dict[str, str],
    m: int = 5,
    timeout: int = 60,
    max_entity_reuse: int = 3,
) -> List[Dict[str, Any]]:
    """
    Ground a mined subgraph pattern with concrete instance entities and attribute bindings.

    Required edges stay required. Optional edges are queried with OPTIONAL so
    instances may omit them. A LIMIT 1 full-match query runs only if the mixed
    sample contains no complete instance.
    """
    type_uris = sorted(subgraph["types"])
    if max_entity_reuse < 1:
        raise ValueError("max_entity_reuse must be at least 1")
    type_to_var = _type_var_map(type_uris)
    edges = list(subgraph.get("edges") or [])
    has_optional = any(edge.get("is_optional") for edge in edges)

    full_edge_vars = _edge_var_map(edges, type_to_var, optionalize=False)
    mixed_edge_vars = _edge_var_map(edges, type_to_var, optionalize=True)
    if has_optional:
        mixed_rows = _sample_instance_rows(
            endpoint,
            type_uris,
            edges,
            optionalize=True,
            timeout=timeout,
            m=m,
            max_entity_reuse=max_entity_reuse,
        )
        full_rows = (
            []
            if any(mixed_row_is_complete(row, edges) for row in mixed_rows)
            else _instance_query(
                endpoint,
                type_uris,
                edges,
                optionalize=False,
                timeout=timeout,
                limit=1,
            )
        )
    else:
        mixed_rows = []
        full_rows = _sample_instance_rows(
            endpoint,
            type_uris,
            edges,
            optionalize=False,
            timeout=timeout,
            m=m,
            max_entity_reuse=max_entity_reuse,
        )

    selected_rows = select_sampled_rows(
        mixed_rows,
        full_rows,
        type_to_var,
        m,
        core_types=_core_type_uris(edges),
        edges=edges,
        max_entity_reuse=max_entity_reuse,
    )
    selected = [
        (full_edge_vars if kind == "full" else mixed_edge_vars, row, kind == "mixed")
        for kind, row in selected_rows
    ]
    if not selected:
        return []

    entity_uris = []
    for edge_vars, row, _ in selected:
        for variable in type_to_var.values():
            uri = row.get(variable)
            if uri:
                entity_uris.append(uri)
        for _, _, target_var in edge_vars:
            uri = row.get(target_var)
            if uri:
                entity_uris.append(uri)
    label_map = get_entity_labels(endpoint, entity_uris, timeout=min(timeout, 30))

    attribute_info_by_type = {}
    for type_uri, attrs_info in (subgraph.get("type_attributes") or {}).items():
        attribute_info_by_type[type_uri] = {
            "property_uris": [attr["property"] for attr in attrs_info],
            "property_labels": {
                attr["property"]: attr["property_label"] for attr in attrs_info
            },
            "property_supports": {
                attr["property"]: attr["support"] for attr in attrs_info
            },
            "property_datatype_labels": {
                attr["property"]: attr["datatype_label"] for attr in attrs_info
            },
            "property_label_from_rdfs": {
                attr["property"]: bool(attr.get("label_from_rdfs"))
                for attr in attrs_info
            },
        }

    instances: List[Dict[str, Any]] = []
    for row_index, (edge_vars, row, is_mixed) in enumerate(selected):
        bindings = {}
        instance_triples = []
        instance_attributes = []

        entities_by_type: Dict[str, List[str]] = {type_uri: [] for type_uri in type_uris}

        def add_entity(type_uri: str, entity_uri: Optional[str]) -> None:
            if not entity_uri:
                return
            bucket = entities_by_type.setdefault(type_uri, [])
            if entity_uri not in bucket:
                bucket.append(entity_uri)

        for type_uri in type_uris:
            add_entity(type_uri, row.get(type_to_var[type_uri]))
        for edge, source_var, target_var in edge_vars:
            add_entity(edge["s"], row.get(source_var))
            add_entity(edge["o"], row.get(target_var))

        for type_uri, entity_uris_for_type in entities_by_type.items():
            for entity_uri in entity_uris_for_type:
                sample = {"uri": entity_uri}
                if entity_uri in label_map:
                    sample["label"] = label_map[entity_uri]

                attrs_info = attribute_info_by_type.get(type_uri)
                if attrs_info:
                    attr_values = get_attribute_values(
                        endpoint=endpoint,
                        entity_uri=entity_uri,
                        properties=attrs_info["property_uris"],
                    )
                    for prop, val in (attr_values or {}).items():
                        instance_attributes.append(
                            {
                                "source_type": type_uri,
                                "source": entity_uri,
                                "property": prop,
                                "property_label": attrs_info["property_labels"][prop],
                                "value": val,
                                "datatype_label": attrs_info["property_datatype_labels"][prop],
                                "label_from_rdfs": attrs_info["property_label_from_rdfs"].get(
                                    prop, False
                                ),
                            }
                        )

                if type_uri in type_label_cache and type_label_cache[type_uri] not in bindings:
                    bindings[type_label_cache[type_uri]] = sample

        for edge_index, (edge, source_var, target_var) in enumerate(edge_vars):
            source_uri = row.get(source_var)
            target_uri = row.get(target_var)
            if (
                edge.get("is_optional")
                and is_mixed
                and not row.get(f"opt{edge_index}")
            ):
                continue
            if source_uri and target_uri:
                instance_triples.append(
                    {
                        "source_type": edge["s"],
                        "source": source_uri,
                        "predicate": edge["p"],
                        "target_type": edge["o"],
                        "target": target_uri,
                        "optional": bool(edge.get("is_optional")),
                    }
                )

        instances.append(
            {
                "index": row_index,
                "bindings": bindings,
                "triples": instance_triples,
                "attributes": instance_attributes,
            }
        )

    return instances