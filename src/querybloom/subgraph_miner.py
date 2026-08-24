"""Backward-compatible entry point for SubgraphMiner in querybloom namespace.

This module re-exports SubgraphMiner and Candidate from the `querybloom.mining` package.
"""

from __future__ import annotations

from querybloom.mining import (
    Candidate,
    SubgraphMiner,
    compute_k_slots,
    find_and_verify_attributes,
    get_attribute_values,
    get_entity_labels,
    get_support,
    get_type_label,
    mine_subgraphs,
    plot_ontology_graph,
    plot_subgraphs_from_yaml,
    prepare_subgraph_yaml_data,
    sample_entities_for_type,
    sample_subgraph_instances,
    sample_target_k,
    save_all_subgraphs_to_yaml,
)

__all__ = [
    "Candidate",
    "SubgraphMiner",
    "compute_k_slots",
    "sample_target_k",
    "mine_subgraphs",
    "get_support",
    "get_type_label",
    "get_entity_labels",
    "sample_entities_for_type",
    "sample_subgraph_instances",
    "find_and_verify_attributes",
    "get_attribute_values",
    "prepare_subgraph_yaml_data",
    "save_all_subgraphs_to_yaml",
    "plot_ontology_graph",
    "plot_subgraphs_from_yaml",
]
