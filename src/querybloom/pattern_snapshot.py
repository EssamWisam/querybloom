"""Serialization helpers for reusable ABSTAT pattern state."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from querybloom.mining import SubgraphMiner


def pattern_data_from_miner(miner: SubgraphMiner) -> dict:
    """Serialize all state required to restart subgraph mining."""
    return {
        "objects": [list(pattern) for pattern in miner.abstat.patterns],
        "object_count": len(miner.abstat.patterns),
        "object_counts": [
            {"pattern": list(pattern), "count": count}
            for pattern, count in miner.abstat.pattern_counts.items()
        ],
        "attributes": [
            list(pattern) for pattern in miner.abstat.attribute_patterns
        ],
        "attribute_count": len(miner.abstat.attribute_patterns),
        "attribute_counts": [
            {"pattern": list(pattern), "count": count}
            for pattern, count in miner.abstat.attribute_counts.items()
        ],
        "mining_pool": [list(pattern) for pattern in miner.patterns],
        "mining_pool_count": len(miner.patterns),
        "property_labels": miner.abstat.property_labels,
        "type_labels": miner.abstat.type_labels,
    }


def load_pattern_data(miner: SubgraphMiner, pattern_data: dict) -> None:
    """Restore complete miner state from a run result or local snapshot."""
    patterns = pattern_data.get("objects", pattern_data.get("patterns", []))
    object_counts = pattern_data.get("object_counts")
    if object_counts is None:
        object_counts = [
            {"pattern": pattern, "count": count}
            for pattern, count in pattern_data.get("pattern_counts", [])
        ]
    attributes = pattern_data.get(
        "attributes", pattern_data.get("attribute_patterns", [])
    )
    attribute_counts = pattern_data.get("attribute_counts", [])
    if attribute_counts and not isinstance(attribute_counts[0], dict):
        attribute_counts = [
            {"pattern": pattern, "count": count}
            for pattern, count in attribute_counts
        ]

    if not patterns or not object_counts:
        raise ValueError("Run has no persisted patterns to restart mining from")

    miner.abstat.patterns = {tuple(pattern) for pattern in patterns}
    miner.abstat.pattern_counts = defaultdict(
        int,
        {
            tuple(item["pattern"]): int(item["count"])
            for item in object_counts
        },
    )
    miner.abstat.attribute_patterns = {tuple(pattern) for pattern in attributes}
    miner.abstat.attribute_counts = defaultdict(
        int,
        {
            tuple(item["pattern"]): int(item["count"])
            for item in attribute_counts
        },
    )
    miner.abstat.property_labels = pattern_data.get("property_labels", {})
    miner.abstat.type_labels = pattern_data.get("type_labels", {})
    miner._build_pattern_pool()