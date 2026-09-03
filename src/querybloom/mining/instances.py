"""Entity sampling and subgraph instance grounding."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Set

from querybloom.executor.sparql_executor import execute_sparql_query as execute
from querybloom.mining.attributes import get_attribute_values
from querybloom.mining.support import get_entity_labels
from querybloom.mining.utils import extract_binding_rows


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


def sample_subgraph_instances(
    endpoint: str,
    subgraph: Dict[str, Any],
    type_label_cache: Dict[str, str],
    min_support: int = 100,
    m: int = 5,
    timeout: int = 60,
    max_attr_len: int = 200,
) -> List[Dict[str, Any]]:
    """
    Ground a mined subgraph pattern with concrete instance entities and attribute bindings.
    """
    type_uris = sorted(subgraph["types"])
    type_to_var = {type_uri: f"v{index}" for index, type_uri in enumerate(type_uris)}

    clauses = []
    for type_uri, variable in type_to_var.items():
        clauses.append(f"?{variable} a <{type_uri}> .")

    for edge in subgraph["edges"]:
        source_var = type_to_var[edge["s"]]
        target_var = type_to_var[edge["o"]]
        clauses.append(f"?{source_var} <{edge['p']}> ?{target_var} .")

    query = f"""
    SELECT DISTINCT {' '.join(f'?{var}' for var in type_to_var.values())} WHERE {{
        {' '.join(clauses)}
    }}
    LIMIT {m}
    """

    res = execute(query, endpoint=endpoint, timeout=timeout)
    rows = extract_binding_rows(res) if res.get("success") else []
    if not rows:
        return []

    entity_uris = []
    for row in rows:
        for variable in type_to_var.values():
            uri = row.get(variable)
            if uri:
                entity_uris.append(uri)
    label_map = get_entity_labels(endpoint, entity_uris)

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
    for row_index, row in enumerate(rows):
        bindings = {}
        instance_triples = []
        instance_attributes = []

        for type_uri in type_uris:
            variable = type_to_var[type_uri]
            entity_uri = row.get(variable)
            if not entity_uri:
                continue

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

            bindings[type_label_cache[type_uri]] = sample

        for edge in subgraph["edges"]:
            source_uri = row.get(type_to_var[edge["s"]])
            target_uri = row.get(type_to_var[edge["o"]])
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