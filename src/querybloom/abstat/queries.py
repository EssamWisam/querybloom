"""SPARQL query templates and filter builders for ABSTAT."""

from __future__ import annotations

from typing import Sequence


def build_filter(
    var: str,
    exclude_prefixes: Sequence[str] | None,
    include_prefixes: Sequence[str] | None,
    optional_obj: bool = False,
) -> str:
    """Build a SPARQL FILTER clause for URI prefix whitelisting and blacklisting."""
    clauses: list[str] = []
    if include_prefixes:
        inc = " || ".join([f'STRSTARTS(STR({var}), "{p}")' for p in include_prefixes])
        clauses.append(f"({inc})")
    if exclude_prefixes:
        exc = " && ".join([f'!STRSTARTS(STR({var}), "{p}")' for p in exclude_prefixes])
        clauses.append(exc)
    if not clauses:
        return ""
    combined = " && ".join(clauses)
    if optional_obj:
        return f"FILTER(!BOUND({var}) || ({combined}))"
    return f"FILTER({combined})"


def build_type_filter(
    var: str,
    exclude_class_prefixes: Sequence[str] | None,
    include_class_prefixes: Sequence[str] | None,
) -> str:
    """Build a SPARQL FILTER clause specifically for type variables (?sType, ?oType)."""
    clauses: list[str] = []
    if include_class_prefixes:
        inc = " || ".join([f'STRSTARTS(STR({var}), "{p}")' for p in include_class_prefixes])
        clauses.append(f"({inc})")
    if exclude_class_prefixes:
        exc = " && ".join([f'!STRSTARTS(STR({var}), "{p}")' for p in exclude_class_prefixes])
        clauses.append(exc)
    return f"FILTER({' && '.join(clauses)})" if clauses else ""
