"""Feature-redundancy measurement: does removing a SPARQL feature change query results?"""

import os
import re
import sys
import json
import hashlib
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from querybloom.executor.sparql_executor import (
        execute_sparql_query as _execute_sparql_query,
    )
except Exception:
    _execute_sparql_query = None

from .parsing import analyze_sparql_features


# ---------------------------------------------------------------------------
# Feature removal helpers
# ---------------------------------------------------------------------------

REDUNDANCY_FEATURES = ["DISTINCT", "FILTER", "OPTIONAL", "ORDER BY", "LIMIT"]


def _remove_distinct(sparql: str) -> str:
    """SELECT DISTINCT ... → SELECT ..."""
    return re.sub(r"\bSELECT\s+DISTINCT\b", "SELECT", sparql, flags=re.IGNORECASE)


def _multiply_limit(sparql: str, factor: int = 2) -> str:
    """LIMIT N → LIMIT N*factor."""

    def _repl(m):
        return f"LIMIT {int(m.group(1)) * factor}"

    return re.sub(r"\bLIMIT\s+(\d+)", _repl, sparql, flags=re.IGNORECASE)


def _remove_order_by(sparql: str) -> str:
    """Remove ORDER BY ... clause (up to next keyword or closing brace)."""
    return re.sub(
        r"\bORDER\s+BY\s+.+?(?=\bLIMIT\b|\bOFFSET\b|\bHAVING\b|}|\Z)",
        "",
        sparql,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _find_balanced_block(sparql: str, start: int, open_ch: str, close_ch: str) -> int:
    """Return index past the matching close_ch starting from sparql[start] == open_ch."""
    depth = 0
    i = start
    while i < len(sparql):
        if sparql[i] == open_ch:
            depth += 1
        elif sparql[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(sparql)


def _remove_all_filter(sparql: str) -> str:
    """Remove every FILTER(...) clause (balanced-parenthesis aware)."""
    result = sparql
    while True:
        match = re.search(r"\bFILTER\s*\(", result, re.IGNORECASE)
        if not match:
            break
        paren_start = match.end() - 1  # index of '('
        paren_end = _find_balanced_block(result, paren_start, "(", ")")
        result = result[: match.start()] + result[paren_end:]
    return result


def _remove_all_optional(sparql: str) -> str:
    """Remove every OPTIONAL { ... } block (balanced-brace aware)."""
    result = sparql
    while True:
        match = re.search(r"\bOPTIONAL\s*\{", result, re.IGNORECASE)
        if not match:
            break
        brace_start = match.end() - 1  # index of '{'
        brace_end = _find_balanced_block(result, brace_start, "{", "}")
        result = result[: match.start()] + result[brace_end:]
    return result


REMOVERS = {
    "DISTINCT": _remove_distinct,
    "FILTER": _remove_all_filter,
    "OPTIONAL": _remove_all_optional,
    "ORDER BY": _remove_order_by,
    "LIMIT": _multiply_limit,
}


# ---------------------------------------------------------------------------
# Result comparison
# ---------------------------------------------------------------------------


# Maximum rows fetched / compared per query – prevents OOM on unbounded modified queries.
_MAX_ROWS = 100000


def _add_safety_limit(sparql: str, max_rows: int = _MAX_ROWS) -> str:
    """Ensure the query has LIMIT <= max_rows. Adds one if absent, lowers it if too high."""
    existing = re.search(r"\bLIMIT\s+(\d+)", sparql, re.IGNORECASE)
    if existing:
        if int(existing.group(1)) > max_rows:
            return re.sub(
                r"\bLIMIT\s+\d+", f"LIMIT {max_rows}", sparql, flags=re.IGNORECASE
            )
        return sparql  # already within budget
    # No LIMIT – append one before any trailing whitespace
    return sparql.rstrip() + f"\nLIMIT {max_rows}"


def _result_rows(response: dict, max_rows: int = _MAX_ROWS) -> list | None:
    """Convert executor response to a list of row tuples for comparison."""
    if not response.get("success") or response.get("results") is None:
        return None
    rows = response["results"]
    if not isinstance(rows, list):
        return None
    result = []
    for i, row in enumerate(rows[:max_rows]):
        if row is None:
            print(f"[redundancy] skipping None row at index {i} in results")
            continue
        result.append(
            tuple(sorted((k, v.get("value", "")) for k, v in row.items()))
        )
    return result


def _results_match(
    original_resp: dict, modified_resp: dict, *, order_sensitive: bool = False
) -> bool:
    """True if both queries returned the same results.

    When *order_sensitive* is True the row ordering must also match
    (used for ORDER BY redundancy checks).
    """
    r1 = _result_rows(original_resp)
    r2 = _result_rows(modified_resp)
    if r1 is None or r2 is None:
        return False  # couldn't compare → treat as non-redundant
    if order_sensitive:
        return r1 == r2
    return set(r1) == set(r2)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache", "redundancy")


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:16]


def _execute_cached(query: str, endpoint: str) -> dict:
    """Execute with a disk cache to avoid re-running identical queries."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    key = _cache_key(query)
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    if _execute_sparql_query is None:
        return {"success": False}
    resp = _execute_sparql_query(query, endpoint=endpoint)
    try:
        with open(path, "w") as f:
            json.dump(resp, f)
    except Exception:
        pass
    return resp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def measure_redundancy(
    queries: list[str],
    endpoint: str = "dblp",
    max_workers: int = 2,
    features: list[str] | None = None,
) -> dict:
    """Measure per-feature redundancy rate across a benchmark.

    For each feature in *features* (default: ``REDUNDANCY_FEATURES``), this
    function finds every query that uses the feature, removes/weakens it,
    re-executes both versions, and checks whether the results changed.

    Parameters
    ----------
    queries : list[str]
        SPARQL query strings.
    endpoint : str
        SPARQL endpoint alias.
    max_workers : int
        Concurrent query threads.
    features : list[str] | None
        Subset of REDUNDANCY_FEATURES to test.  ``None`` → all.

    Returns
    -------
    dict with keys:
        ``redundancy_rates``  – {feature: float} redundancy % (0–100)
        ``_counts``           – {feature: {"has": int, "redundant": int}}
    """
    if features is None:
        features = REDUNDANCY_FEATURES

    # Pre-detect which queries use which features
    feature_flags = [analyze_sparql_features(q) for q in queries]

    counts = {f: {"has": 0, "redundant": 0} for f in features}

    # Build work items: (query_idx, feature_name, original_query, modified_query)
    work = []
    for i, q in enumerate(queries):
        for feat in features:
            if feature_flags[i].get(feat, 0):
                remover = REMOVERS[feat]
                modified = remover(q)
                if modified.strip() == q.strip():
                    continue  # removal had no effect
                # Cap modified query to _MAX_ROWS to prevent unbounded result sets
                # (e.g. removing FILTER/OPTIONAL from a query that has no LIMIT)
                modified = _add_safety_limit(modified)
                counts[feat]["has"] += 1
                work.append((i, feat, q, modified))

    # Execute originals + modified in parallel, deduplicating identical queries
    all_queries = {}
    for _, _, orig, mod in work:
        all_queries[orig] = None
        all_queries[mod] = None

    def _run(query):
        return query, _execute_cached(query, endpoint)

    print(f"  Redundancy: executing {len(all_queries)} unique queries …")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for query, resp in pool.map(_run, all_queries.keys()):
            all_queries[query] = resp

    # Compare
    for _, feat, orig, mod in work:
        order_sensitive = feat == "ORDER BY"
        if _results_match(
            all_queries[orig], all_queries[mod], order_sensitive=order_sensitive
        ):
            counts[feat]["redundant"] += 1

    rates = {}
    for feat in features:
        has = counts[feat]["has"]
        rates[feat] = (counts[feat]["redundant"] / has * 100) if has > 0 else 0.0

    return {"redundancy_rates": rates, "_counts": counts}
