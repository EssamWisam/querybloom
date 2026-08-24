"""ABSTAT package: structural profiling and type-pattern summarization for Knowledge Graphs."""

from __future__ import annotations

from querybloom.abstat.core import ABSTAT_v2
from querybloom.abstat.domain_range import get_property_domain_range
from querybloom.abstat.hierarchy import is_subtype, minimal_types, prefetch_subclass_graph
from querybloom.abstat.patterns import compute_minimal_patterns, process_properties
from querybloom.abstat.properties import find_one_connected_property, get_distinct_properties
from querybloom.abstat.visualization import format_pattern_dataframe, plot_schema_graph

ABSTAT = ABSTAT_v2

__all__ = [
    "ABSTAT_v2",
    "ABSTAT",
    "get_property_domain_range",
    "prefetch_subclass_graph",
    "is_subtype",
    "minimal_types",
    "get_distinct_properties",
    "find_one_connected_property",
    "compute_minimal_patterns",
    "process_properties",
    "plot_schema_graph",
    "format_pattern_dataframe",
]
