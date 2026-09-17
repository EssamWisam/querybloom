"""SPARQL transformations and outcome rules for redundancy metrics."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from ..execution import ExecutionObservation

REDUNDANCY_FEATURES = ("DISTINCT", "FILTER", "OPTIONAL", "ORDER BY", "LIMIT")
MAX_ROWS = 100_000


def remove_distinct(sparql: str) -> str:
    return re.sub(r"\bSELECT\s+DISTINCT\b", "SELECT", sparql, flags=re.IGNORECASE)


def multiply_limit(sparql: str, factor: int = 2) -> str:
    return re.sub(
        r"\bLIMIT\s+(\d+)",
        lambda match: f"LIMIT {int(match.group(1)) * factor}",
        sparql,
        flags=re.IGNORECASE,
    )


def remove_order_by(sparql: str) -> str:
    return re.sub(
        r"\bORDER\s+BY\s+.+?(?=\bLIMIT\b|\bOFFSET\b|\bHAVING\b|}|\Z)",
        "",
        sparql,
        flags=re.IGNORECASE | re.DOTALL,
    )


def remove_all_filters(sparql: str) -> str:
    return _remove_balanced(sparql, r"\bFILTER\s*\(", "(", ")")


def remove_all_optional(sparql: str) -> str:
    return _remove_balanced(sparql, r"\bOPTIONAL\s*\{", "{", "}")


_REMOVERS: dict[str, Callable[[str], str]] = {
    "DISTINCT": remove_distinct,
    "FILTER": remove_all_filters,
    "OPTIONAL": remove_all_optional,
    "ORDER BY": remove_order_by,
    "LIMIT": multiply_limit,
}


def modify_query(sparql: str, feature: str) -> str:
    try:
        remover = _REMOVERS[feature]
    except KeyError as exc:
        raise ValueError(f"unsupported redundancy feature: {feature!r}") from exc
    return remover(sparql)


def add_safety_limit(sparql: str, max_rows: int = MAX_ROWS) -> str:
    # ASK queries have no solution sequence, so LIMIT is not valid SPARQL syntax for them.
    if re.search(r"\bASK\b", sparql, re.IGNORECASE):
        return sparql
    existing = re.search(r"\bLIMIT\s+(\d+)", sparql, re.IGNORECASE)
    if existing:
        if int(existing.group(1)) > max_rows:
            return re.sub(
                r"\bLIMIT\s+\d+",
                f"LIMIT {max_rows}",
                sparql,
                flags=re.IGNORECASE,
            )
        return sparql
    return sparql.rstrip() + f"\nLIMIT {max_rows}"


def canonical_rows(
    observation: ExecutionObservation, max_rows: int = MAX_ROWS
) -> tuple[tuple[tuple[str, str], ...], ...] | None:
    if observation.kind != "select":
        return None
    return tuple(
        tuple(
            sorted(
                (variable, binding.get("value", ""))
                for variable, binding in row.items()
            )
        )
        for row in observation.rows[:max_rows]
    )


def results_match(
    original: ExecutionObservation,
    modified: ExecutionObservation,
    *,
    order_sensitive: bool = False,
) -> bool:
    original_rows = canonical_rows(original)
    modified_rows = canonical_rows(modified)
    if original_rows is None or modified_rows is None:
        return False
    if order_sensitive:
        return original_rows == modified_rows
    return set(original_rows) == set(modified_rows)


def pair_outcome(
    original: ExecutionObservation,
    modified: ExecutionObservation,
    *,
    feature: str,
) -> Literal["redundant", "changed", "failed"]:
    if original.kind == "failure" or modified.kind == "failure":
        return "failed"
    return (
        "redundant"
        if results_match(original, modified, order_sensitive=feature == "ORDER BY")
        else "changed"
    )


def _remove_balanced(sparql: str, pattern: str, opening: str, closing: str) -> str:
    result = sparql
    while True:
        match = re.search(pattern, result, re.IGNORECASE)
        if match is None:
            # Removing the block can strand a leftover "." from its original
            # trailing separator, producing an invalid empty triple pattern
            # (e.g. "?y . . ?x ..."). Collapse any such adjacent dots.
            result = re.sub(r"\.(\s*\.)+", ".", result)
            result = re.sub(r"\{\s*\.\s*", "{ ", result)
            return result
        block_start = match.end() - 1
        block_end = _find_balanced_block(result, block_start, opening, closing)
        result = result[: match.start()] + result[block_end:]


def _find_balanced_block(sparql: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    position = start
    while position < len(sparql):
        if sparql[position] == opening:
            depth += 1
        elif sparql[position] == closing:
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return len(sparql)
