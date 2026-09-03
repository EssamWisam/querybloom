"""Attribute discovery, support verification, and entity attribute value retrieval."""

from __future__ import annotations

from collections import defaultdict
import random
from typing import Any, Dict, List, Optional, Set

from querybloom.executor.sparql_executor import execute_sparql_query as execute
from querybloom.mining.support import get_support, get_type_label

EXCLUDED_ATTRIBUTE_URIS: Set[str] = {
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://www.w3.org/2004/02/skos/core#altLabel",
    "http://www.w3.org/2004/02/skos/core#definition",
    "http://purl.org/dc/terms/description",
    "http://purl.org/dc/elements/1.1/description",
}


def find_and_verify_attributes(
    endpoint: str,
    attribute_counts: Dict[Tuple[str, str, str], int],
    type_uris: Set[str],
    num_attrs: int,
    verif_timeout: int = 5,
    min_support: int = 100,
    abstat_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Find and verify attribute patterns for a set of types.
    Collects attributes from all types, randomly samples num_attrs total,
    and verifies support against the endpoint.
    """
    if not attribute_counts:
        return {}

    all_attributes = []
    for (s, p, o), count in attribute_counts.items():
        if s in type_uris:
            p_lower = p.lower()
            if (
                p not in EXCLUDED_ATTRIBUTE_URIS
                and "label" not in p_lower
                and "description" not in p_lower
                and "comment" not in p_lower
            ):
                all_attributes.append((s, p, o, count))

    if not all_attributes:
        return {}

    if len(all_attributes) > num_attrs:
        all_attributes = random.sample(all_attributes, num_attrs)

    type_attributes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s, p, o, count in all_attributes:
        support = get_support(
            endpoint=endpoint,
            types={s},
            edges=[(s, p, o)],
            timeout=verif_timeout,
            limit=min_support,
        )

        if support >= 1:
            fetched_label = get_type_label(endpoint, p, abstat_labels=abstat_labels)
            p_label = fetched_label or p.split("/")[-1].split("#")[-1]
            o_label = o.split("/")[-1].split("#")[-1]

            type_attributes[s].append(
                {
                    "property": p,
                    "property_label": p_label,
                    "datatype": o,
                    "datatype_label": o_label,
                    "support": support,
                    "label_from_rdfs": bool(fetched_label),
                }
            )

    return dict(type_attributes)


def get_attribute_values(
    endpoint: str,
    entity_uri: str,
    properties: List[str],
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Fetch attribute values for a specific entity.
    """
    if not properties:
        return {}

    property_vars = []
    optional_clauses = []
    for i, prop in enumerate(properties):
        var_name = f"val{i}"
        property_vars.append(var_name)
        optional_clauses.append(
            f"OPTIONAL {{ <{entity_uri}> <{prop}> ?{var_name} }}"
        )

    query = f"""
    SELECT {' '.join(f'?{v}' for v in property_vars)} WHERE {{
        {' '.join(optional_clauses)}
    }}
    """

    res = execute(query, endpoint=endpoint, timeout=timeout)

    values: Dict[str, Any] = {}
    if res.get("success"):
        bindings = res.get("results", [])
        if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
            records = bindings.to_dict("records")
            if records:
                record = records[0]
                for i, prop in enumerate(properties):
                    var_name = f"val{i}"
                    if var_name in record and record[var_name] is not None:
                        values[prop] = record[var_name]
        elif isinstance(bindings, list) and bindings:
            record = bindings[0]
            if record is not None:
                for i, prop in enumerate(properties):
                    var_name = f"val{i}"
                    if var_name in record:
                        val_obj = record[var_name]
                        if isinstance(val_obj, dict) and "value" in val_obj:
                            values[prop] = val_obj["value"]
                        elif val_obj is not None:
                            values[prop] = val_obj

    return values
