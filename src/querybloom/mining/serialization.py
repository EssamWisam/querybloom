"""YAML dataset formatting and serialization for mined subgraphs."""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Dict, List, Optional

import yaml

from querybloom.mining.instances import sample_subgraph_instances
from querybloom.mining.support import get_type_label
from querybloom.mining.yaml_v5 import build_subgraph_yaml, local_name


def prepare_subgraph_yaml_data(
    subgraph: Dict[str, Any],
    index: int,
    endpoint: str,
    min_support: int = 100,
    m: int = 5,
    max_attr_len: int = 200,
    abstat_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Prepare a mined subgraph as compact v5 YAML data."""
    type_uris = list(subgraph["types"])
    type_labels: Dict[str, str] = {}
    for type_uri in type_uris:
        type_labels[type_uri] = (
            get_type_label(endpoint, type_uri, abstat_labels=abstat_labels)
            or local_name(type_uri)
        )

    instance_rows = sample_subgraph_instances(
        endpoint=endpoint,
        subgraph=subgraph,
        type_label_cache=type_labels,
        min_support=min_support,
        m=m,
        max_attr_len=max_attr_len,
    )

    return build_subgraph_yaml(
        subgraph_id=index + 1,
        support=subgraph["support"],
        type_uris=type_uris,
        type_labels=type_labels,
        edges=subgraph["edges"],
        type_attributes=subgraph.get("type_attributes") or {},
        instance_rows=instance_rows,
        min_support=min_support,
        max_attr_len=max_attr_len,
    )


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
