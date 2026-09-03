"""Graph expansion and subgraph search algorithm."""

from __future__ import annotations

from collections import defaultdict
import random
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from tqdm import tqdm

from querybloom.events import EventSink, emit_event
from querybloom.graph_serialization import subgraph_to_cytoscape
from querybloom.mining.attributes import find_and_verify_attributes
from querybloom.mining.candidate import Candidate, compute_k_slots, sample_target_k
from querybloom.mining.serialization import (
    prepare_subgraph_yaml_data,
    save_all_subgraphs_to_yaml,
)
from querybloom.mining.support import get_support


def mine_subgraphs(
    endpoint: str,
    patterns: List[Tuple[str, str, str]],
    pattern_counts: Dict[Tuple[str, str, str], int],
    type_labels: Dict[str, str],
    property_labels: Dict[str, str],
    attribute_counts: Dict[Tuple[str, str, str], int],
    adj: Dict[str, List[Tuple[str, str, str]]],
    min_support: int,
    k: Union[int, Tuple[int, int], Dict[int, float]],
    num_subgraphs: int = 5,
    exact_support: bool = False,
    m: int = 5,
    output_dir: Optional[str] = None,
    max_subgraphs_per_seed: int = 1,
    verif_timeout: int = 5,
    prob_optional: float = 0.0,
    num_attrs: Union[int, Tuple[int, int]] = 0,
    max_attr_len: int = 200,
    strategy: str = "rand",
    uniform_types: bool = False,
    event_sink: EventSink | None = None,
    stop_event: Any | None = None,
    skip_event: Any | None = None,
    max_entity_reuse: int = 3,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Search and mine connected subgraphs with K types matching support thresholds.
    """
    k_slots = compute_k_slots(k, num_subgraphs)

    if isinstance(num_attrs, int):
        num_attrs_range = (num_attrs, num_attrs)
    else:
        num_attrs_range = num_attrs

    if not patterns:
        raise RuntimeError(
            "Pattern pool is empty. Call preprocess() first to build patterns."
        )

    emit_event(
        event_sink,
        "stage.started",
        "mining",
        "Mining subgraphs",
        {
            "k": k,
            "num_subgraphs": num_subgraphs,
            "max_subgraphs_per_seed": max_subgraphs_per_seed,
            "exact_support": exact_support,
            "output_dir": output_dir,
            "num_attrs": num_attrs,
            "uniform_types": uniform_types,
        },
    )

    found_subgraphs: List[Dict[str, Any]] = []
    found_signatures: Set[frozenset] = set()
    exported_subgraphs: List[Dict[str, Any]] = []
    last_export_path: Optional[str] = None

    target_optional = int(num_subgraphs * prob_optional)
    optional_count = 0

    pbar = tqdm(desc="Explored Candidates", total=num_subgraphs)
    seed_usage: Dict[Tuple[str, str, str], int] = defaultdict(int)

    stack: List[Candidate] = []
    visited: Set[frozenset] = set()

    patterns_list = patterns.copy()
    random.shuffle(patterns_list)

    for p in patterns_list:
        s, pred, o = p
        count = pattern_counts.get(p, 0)
        edge_dict = {
            "s": s,
            "p": pred,
            "o": o,
            "support": count,
            "is_optional": False,
        }
        stack.append(
            Candidate(
                types={s, o},
                edges=[edge_dict],
                est_support=count,
                is_verified=True,
                seed_pattern=p,
                has_optional=False,
            )
        )

    try:
        while stack and len(found_subgraphs) < num_subgraphs:
            if stop_event is not None and stop_event.is_set():
                emit_event(
                    event_sink,
                    "run.cancelled",
                    "mining",
                    "Mining cancelled",
                    {"num_subgraphs": len(found_subgraphs)},
                )
                break
            if skip_event is not None and skip_event.is_set():
                emit_event(
                    event_sink,
                    "stage.skipped",
                    "mining",
                    "Mining skipped — proceeding to questions",
                    {"num_subgraphs": len(found_subgraphs)},
                )
                break

            if strategy == "rand":
                pop_idx = random.randint(0, len(stack) - 1)
            else:
                pop_idx = -1
            c = stack.pop(pop_idx)

            if seed_usage[c.seed_pattern] >= max_subgraphs_per_seed:
                continue

            if c.target_k is None:
                c.target_k = sample_target_k(k_slots)
                if c.target_k is None:
                    continue

            # 1. Lazy support verification
            cur_support = c.est_support
            if not c.is_verified:
                last_edge = c.edges[-1]
                s_name = last_edge["s"].split("/")[-1].split("#")[-1]
                p_name = last_edge["p"].split("/")[-1].split("#")[-1]
                o_name = last_edge["o"].split("/")[-1].split("#")[-1]
                pbar.set_postfix_str(f"Verifying: ...--[{p_name}]-->{o_name}")

                limit_val = None if exact_support else min_support
                edges_tuples = [(e["s"], e["p"], e["o"]) for e in c.edges]
                real_support = get_support(
                    endpoint=endpoint,
                    types=c.types,
                    edges=edges_tuples,
                    timeout=verif_timeout,
                    pbar=pbar,
                    limit=limit_val,
                )

                if real_support < min_support:
                    if real_support >= 1 and optional_count < target_optional:
                        last_edge["support"] = real_support
                        last_edge["is_optional"] = True
                        c.has_optional = True
                        cur_support = real_support
                    else:
                        continue
                else:
                    last_edge["support"] = real_support
                    cur_support = real_support

            # Dedup check
            sig = frozenset((e["s"], e["p"], e["o"]) for e in c.edges)
            if sig in visited or sig in found_signatures:
                continue
            visited.add(sig)

            # 2. Check Goal
            cur_num_types = len(c.types)
            if cur_num_types == c.target_k:
                if k_slots.get(c.target_k, 0) <= 0:
                    continue

                sampled_num_attrs = random.randint(
                    num_attrs_range[0], num_attrs_range[1]
                )
                subgraph: Dict[str, Any] = {
                    "types": list(c.types),
                    "edges": c.edges,
                    "num_types": cur_num_types,
                    "support": cur_support,
                    "has_optional_edges": c.has_optional,
                }

                if sampled_num_attrs > 0:
                    type_attributes = find_and_verify_attributes(
                        endpoint=endpoint,
                        attribute_counts=attribute_counts,
                        type_uris=c.types,
                        num_attrs=sampled_num_attrs,
                        verif_timeout=verif_timeout,
                        min_support=min_support,
                        abstat_labels=type_labels,
                    )
                    if type_attributes:
                        subgraph["type_attributes"] = type_attributes

                graph = subgraph_to_cytoscape(
                    subgraph,
                    type_labels=type_labels,
                    property_labels=property_labels,
                )

                yaml_data = prepare_subgraph_yaml_data(
                    subgraph=subgraph,
                    index=len(found_subgraphs),
                    endpoint=endpoint,
                    min_support=min_support,
                    m=m,
                    max_entity_reuse=max_entity_reuse,
                    max_attr_len=max_attr_len,
                    abstat_labels=type_labels,
                )
                if not yaml_data.get("instances"):
                    emit_event(
                        event_sink,
                        "subgraph.rejected",
                        "mining.samples",
                        "Rejected subgraph because no grounded instances were found",
                        {
                            "subgraph": subgraph,
                            "graph": graph,
                            "k": c.target_k,
                            "reason": "no_grounded_instances",
                        },
                    )
                    continue

                found_subgraphs.append(subgraph)
                found_signatures.add(sig)
                k_slots[c.target_k] -= 1

                emit_event(
                    event_sink,
                    "subgraph.discovered",
                    "mining",
                    f"Discovered subgraph {len(found_subgraphs)}",
                    {
                        "index": len(found_subgraphs) - 1,
                        "subgraph": subgraph,
                        "graph": graph,
                        "k": c.target_k,
                        "support": cur_support,
                        "remaining_slots": dict(k_slots),
                    },
                )

                if c.has_optional:
                    optional_count += 1
                pbar.update(1)
                seed_usage[c.seed_pattern] += 1
                emit_event(
                    event_sink,
                    "subgraph.samples",
                    "mining.samples",
                    f"Samples ready for subgraph {len(found_subgraphs)}",
                    {
                        "index": len(found_subgraphs) - 1,
                        "subgraph_id": yaml_data.get("subgraph_id"),
                        "types": yaml_data.get("types", {}),
                        "relationships": yaml_data.get("relationships", []),
                        "samples": yaml_data,
                    },
                )

                if output_dir:
                    exported_subgraphs.append(yaml_data)
                    filepath = save_all_subgraphs_to_yaml(
                        subgraphs_data=exported_subgraphs,
                        endpoint=endpoint,
                        output_dir=output_dir,
                    )
                    last_export_path = filepath
                    pbar.write(
                        f"Updated {filepath} with subgraph {len(found_subgraphs)} "
                        f"(k={c.target_k}, Seed usage: {seed_usage[c.seed_pattern]})"
                    )

                if seed_usage[c.seed_pattern] >= max_subgraphs_per_seed:
                    continue
                continue

            if cur_num_types > c.target_k:
                continue

            # 3. Extensions
            cur_edge_tuples = {(e["s"], e["p"], e["o"]) for e in c.edges}
            ext_candidates: Set[Tuple[str, str, str]] = set()
            if uniform_types:
                for t in c.types:
                    local = [
                        pat for pat in adj.get(t, []) if pat not in cur_edge_tuples
                    ]
                    if local:
                        ext_candidates.add(random.choice(local))
            else:
                for t in c.types:
                    for pat in adj.get(t, []):
                        if pat not in cur_edge_tuples:
                            ext_candidates.add(pat)

            cand_list = list(ext_candidates)
            random.shuffle(cand_list)

            for pat in cand_list:
                s, p, o = pat
                new_types = c.types | {s, o}

                new_edge = {
                    "s": s,
                    "p": p,
                    "o": o,
                    "support": None,
                    "is_optional": False,
                }
                new_edges = c.edges + [new_edge]

                new_sig = frozenset((e["s"], e["p"], e["o"]) for e in new_edges)
                if new_sig in visited:
                    continue

                pat_count = pattern_counts.get(pat, 0)
                est_support = min(cur_support, pat_count)

                if est_support >= min_support or (
                    est_support >= 1 and optional_count < target_optional
                ):
                    stack.append(
                        Candidate(
                            types=new_types,
                            edges=new_edges,
                            est_support=est_support,
                            is_verified=False,
                            seed_pattern=c.seed_pattern,
                            has_optional=c.has_optional,
                            target_k=c.target_k,
                        )
                    )

    finally:
        pbar.close()

    emit_event(
        event_sink,
        "stage.completed",
        "mining",
        "Mining completed",
        {"num_subgraphs": len(found_subgraphs), "output_path": last_export_path},
    )

    return found_subgraphs, last_export_path
