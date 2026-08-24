"""Dataset export utilities for QA pairs and subgraphs."""

from __future__ import annotations

import json
import os
import random
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
from tqdm import tqdm

from querybloom.executor.sparql_executor import execute_sparql_query


def _pick_optimal_qa_pair(subgraph: dict) -> list[tuple[int, dict]]:
    qa_pairs = subgraph.get("qa_pairs") or []
    if not qa_pairs:
        return []

    for idx, qa in enumerate(qa_pairs):
        if qa.get("is_most_meaningful") is True:
            return [(idx, qa)]

    most_meaningful_index = subgraph.get("most_meaningful_index")
    if isinstance(most_meaningful_index, int):
        idx = most_meaningful_index - 1
        if 0 <= idx < len(qa_pairs):
            return [(idx, qa_pairs[idx])]

    return []


def convert_yaml_to_jsonl(
    input_path: str,
    output_path: Optional[str] = None,
    num_samples: Optional[Union[int, str]] = None,
    execute: bool = False,
    endpoint: str = "sockg-local",
    optimal: bool = False,
    allow_empty_results: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """
    Convert a YAML file of subgraphs/QA pairs to a JSONL file.
    Optionally executes SPARQL queries before filtering.
    Filters for execution_results.success == True and optionally execution_results.count > 0.
    If optimal=True, selects only the single most meaningful QA pair per subgraph
    (as annotated by `is_most_meaningful` or `most_meaningful_index`) before filtering.

    num_samples:
        - int   : sample that many entries from all valid pairs (coverage-aware).
        - 'auto': pick exactly ONE correct pair per subgraph.
                  optimal=True  → the most meaningful one;
                  optimal=False → a random correct one.
        - None  : keep all valid pairs.
    """
    auto_mode = num_samples == "auto"

    if not os.path.exists(input_path):
        print(f"Error: File '{input_path}' not found.")
        return None

    if output_path is None:
        filename = os.path.splitext(input_path)[0]
        optimal_suffix = "_optimal" if optimal else ""
        if auto_mode:
            output_path = f"{filename}{optimal_suffix}_auto.jsonl"
        elif num_samples:
            output_path = f"{filename}{optimal_suffix}_sample{num_samples}.jsonl"
        else:
            output_path = f"{filename}{optimal_suffix}.jsonl"

    print(f"Reading {input_path}...")
    try:
        with open(input_path, "r") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading YAML file: {e}")
        return None

    if not isinstance(data, list):
        print("Error: Expected YAML content to be a list of subgraphs.")
        return None

    count_total = 0
    valid_entries_by_subgraph = {}  # subgraph_id -> list of valid entries

    print("Filtering entries...")
    for subgraph in tqdm(data, desc="Processing subgraphs"):
        subgraph_id = subgraph.get("subgraph_id", "unknown")
        qa_pairs = subgraph.get("qa_pairs", [])

        if not qa_pairs:
            continue

        if optimal:
            selected_pairs = _pick_optimal_qa_pair(subgraph)
            if not selected_pairs:
                if not auto_mode:
                    continue
                selected_pairs = list(enumerate(qa_pairs))
        else:
            selected_pairs = list(enumerate(qa_pairs))

        for i, qa in selected_pairs:
            count_total += 1
            if execute:
                sparql_query = qa.get("sparql_query")
                if sparql_query:
                    try:
                        execution_result = execute_sparql_query(
                            sparql_query, endpoint=endpoint
                        )
                        qa["execution_results"] = execution_result
                    except Exception as e:
                        print(f"Error executing query for ID {subgraph_id}_{i}: {e}")
                        qa["execution_results"] = {
                            "success": False,
                            "error_message": str(e),
                        }
                else:
                    qa["execution_results"] = {
                        "success": False,
                        "error_message": "No SPARQL query found",
                    }

            exec_results = qa.get("execution_results", {})
            success = exec_results.get("success", False)
            count = exec_results.get("count", 0)

            verification_status = qa.get("verification_status")
            if verification_status is not None and verification_status != "correct":
                continue

            has_results = count > 0 if not allow_empty_results else True
            if success and has_results:
                entry = {
                    "id": f"{subgraph_id}_{i}",
                    "question": qa.get("question", ""),
                    "sparql": qa.get("sparql_query", ""),
                }
                if subgraph_id not in valid_entries_by_subgraph:
                    valid_entries_by_subgraph[subgraph_id] = []
                valid_entries_by_subgraph[subgraph_id].append(entry)

    all_valid = [e for entries in valid_entries_by_subgraph.values() for e in entries]
    count_candidates = len(all_valid)

    if auto_mode:
        final_entries = []
        for entries in valid_entries_by_subgraph.values():
            if optimal:
                final_entries.append(entries[0])
            else:
                final_entries.append(random.choice(entries))
        print(
            f"Auto mode: selected 1 correct pair per subgraph "
            f"→ {len(final_entries)} entries from {len(valid_entries_by_subgraph)} subgraphs."
        )
    elif num_samples is not None:
        if isinstance(num_samples, int) and num_samples < count_candidates:
            first_picks = []
            remaining = []
            for entries in valid_entries_by_subgraph.values():
                picked = random.choice(entries)
                first_picks.append(picked)
                remaining.extend(e for e in entries if e is not picked)

            if num_samples <= len(first_picks):
                final_entries = random.sample(first_picks, num_samples)
            else:
                extra_needed = num_samples - len(first_picks)
                extra = random.sample(remaining, extra_needed)
                final_entries = first_picks + extra

            print(
                f"Sampling {num_samples} entries from {count_candidates} candidates "
                f"({len(valid_entries_by_subgraph)} subgraphs)..."
            )
        else:
            print(
                f"Requested {num_samples} samples but only {count_candidates} valid entries found. Including all."
            )
            final_entries = all_valid
    else:
        final_entries = all_valid

    print(f"Writing {len(final_entries)} entries to {output_path}...")
    with open(output_path, "w") as out_f:
        for entry in final_entries:
            out_f.write(json.dumps(entry) + "\n")

    print(f"Conversion complete.")
    print(f"Total QA pairs scanned: {count_total}")
    print(f"Valid candidates found: {count_candidates}")
    print(f"Entries written: {len(final_entries)}")
    print(f"Output saved to: {output_path}")
    return final_entries
