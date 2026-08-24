"""Candidate subgraph representation and k-distribution slot sampling."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Dict, List, Optional, Set, Tuple, Union


@dataclass
class Candidate:
    """A candidate subgraph on the DFS exploration stack."""

    types: Set[str]
    edges: List[Dict[str, Any]]
    est_support: int
    is_verified: bool
    seed_pattern: Tuple[str, str, str]
    has_optional: bool
    target_k: Optional[int] = None


def compute_k_slots(
    k: Union[int, Tuple[int, int], Dict[int, float]],
    num_subgraphs: int,
) -> Dict[int, int]:
    """
    Convert k specification (int, tuple range, or weighted dict) into {k_value: num_slots}.
    """
    if isinstance(k, int):
        return {k: num_subgraphs}
    elif isinstance(k, tuple):
        k_values = list(range(k[0], k[1] + 1))
        base, remainder = divmod(num_subgraphs, len(k_values))
        return {
            kv: base + (1 if i < remainder else 0)
            for i, kv in enumerate(k_values)
        }
    elif isinstance(k, dict):
        total_weight = sum(k.values())
        slots: Dict[int, int] = {}
        assigned = 0
        k_items = sorted(k.items())
        for i, (kv, w) in enumerate(k_items):
            if i == len(k_items) - 1:
                slots[kv] = num_subgraphs - assigned
            else:
                slots[kv] = round(num_subgraphs * w / total_weight)
                assigned += slots[kv]
        return slots
    raise ValueError(f"k must be int, tuple, or dict, got {type(k)}")


def sample_target_k(k_slots: Dict[int, int]) -> Optional[int]:
    """
    Sample a target k from remaining unfilled slots, weighted by availability.
    """
    available = [(kv, slots) for kv, slots in k_slots.items() if slots > 0]
    if not available:
        return None
    k_values, weights = zip(*available)
    return random.choices(k_values, weights=weights, k=1)[0]
