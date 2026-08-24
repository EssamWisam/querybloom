"""YAML dataset formatting and serialization for mined subgraphs."""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Dict, List, Optional, Set

import yaml

from querybloom.mining.instances import sample_subgraph_instances
from querybloom.mining.support import get_type_label


def prepare_subgraph_yaml_data(
    subgraph: Dict[str, Any],
    index: int,
    endpoint: str,
    min_support: int = 100,
    m: int = 5,
    max_attr_len: int = 200,
    abstat_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Prepare subgraph data for YAML export with graph info and sample entities per type.
    """
    type_label_cache: Dict[str, str] = {}
    for type_uri in subgraph["types"]:
        label = get_type_label(endpoint, type_uri, abstat_labels=abstat_labels)
        if label:
            type_label_cache[type_uri] = label
        else:
            type_label_cache[type_uri] = type_uri.split("/")[-1].split("#")[-1]

    sample_payload = sample_subgraph_instances(
        endpoint=endpoint,
        subgraph=subgraph,
        type_label_cache=type_label_cache,
        min_support=min_support,
        m=m,
        max_attr_len=max_attr_len,
    )
    type_samples = sample_payload["types"]
    attribute_uris = set(sample_payload.get("attribute_uris", []))

    formatted_edges: List[str] = []
    predicate_uris: List[str] = []
    for edge in subgraph["edges"]:
        s, p, o = edge["s"], edge["p"], edge["o"]
        is_optional = edge.get("is_optional", False)

        if p not in predicate_uris:
            predicate_uris.append(p)

        s_label = type_label_cache.get(s, s.split("/")[-1].split("#")[-1])
        o_label = type_label_cache.get(o, o.split("/")[-1].split("#")[-1])

        p_label = get_type_label(endpoint, p, abstat_labels=abstat_labels)
        if not p_label:
            p_label = p.split("/")[-1].split("#")[-1]

        arrow = "-->*" if is_optional else "-->"
        edge_str = f"{s_label} --{p_label} {arrow} {o_label}"
        formatted_edges.append(edge_str)

    return {
        "subgraph_id": index + 1,
        "num_types": subgraph["num_types"],
        "min_support": subgraph["support"],
        "edges": formatted_edges,
        "predicate_uris": predicate_uris,
        "attribute_uris": sorted(list(attribute_uris)),
        "sample_mode": sample_payload.get("sample_mode", "grounded"),
        "sample_query": sample_payload.get("sample_query"),
        "sample_query_success": sample_payload.get("sample_query_success"),
        "instances": sample_payload.get("instances", []),
        "types": type_samples,
    }


def save_all_subgraphs_to_yaml(
    subgraphs_data: List[Dict[str, Any]],
    endpoint: str,
    output_dir: str,
) -> str:
    """
    Save all subgraphs to a YAML file with format: mm-dd-HH-endpoint.yaml.
    Returns the path to the saved file.
    """
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%m-%d-%H")
    endpoint_name = endpoint.replace("http://", "").replace("https://", "")
    endpoint_name = endpoint_name.replace("/", "-").replace(":", "-")
    endpoint_name = endpoint_name.strip("-")[:50]

    filename = f"{timestamp}-{endpoint_name}.yaml"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(
            subgraphs_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    return filepath
