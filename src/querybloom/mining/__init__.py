"""Mining package: frequent subgraph sampling, DFS exploration, and KG instance grounding."""

from __future__ import annotations

from querybloom.mining.attributes import (
    find_and_verify_attributes,
    get_attribute_values,
)
from querybloom.mining.candidate import Candidate, compute_k_slots, sample_target_k
from querybloom.mining.core import SubgraphMiner
from querybloom.mining.instances import (
    sample_entities_for_type,
    sample_subgraph_instances,
)
from querybloom.mining.search import mine_subgraphs
from querybloom.mining.serialization import (
    prepare_subgraph_yaml_data,
    save_all_subgraphs_to_yaml,
)
from querybloom.mining.yaml_v5 import (
    build_subgraph_yaml,
    dump_subgraph_yaml,
    is_v5_subgraph,
    parse_relationship_line,
)
from querybloom.mining.support import (
    get_entity_labels,
    get_support,
    get_type_label,
)
from querybloom.mining.visualization import (
    plot_ontology_graph,
    plot_subgraphs_from_yaml,
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
    "build_subgraph_yaml",
    "dump_subgraph_yaml",
    "is_v5_subgraph",
    "parse_relationship_line",
    "plot_ontology_graph",
    "plot_subgraphs_from_yaml",
]
