"""Subclass taxonomy fetching, caching, and instance-level minimal types reasoning."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Set

import pandas as pd

from querybloom.events import EventSink, emit_event
from querybloom.executor.sparql_executor import execute_sparql_query
from querybloom.abstat.cache import subclass_cache_path


def prefetch_subclass_graph(
    endpoint: str,
    cache_dir: Path,
    is_wikidata: bool = False,
    use_cache: bool = True,
    persist_cache: bool = True,
    skip_event: Any | None = None,
    event_sink: EventSink | None = None,
) -> tuple[dict[str, set[str]], bool]:
    """
    Prefetches global subclass edges once and caches them on disk.
    Used to make is_subtype checks local during minimization.

    Returns:
        tuple (subclass_graph, prefetched_success_flag)
    """
    cache_path = subclass_cache_path(cache_dir, endpoint)

    if skip_event is not None and skip_event.is_set():
        print("Subclass graph prefetch skipped because cancellation was requested.")
        return defaultdict(set), False

    if use_cache and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            graph = defaultdict(set)
            for pair in data.get("pairs", []):
                if isinstance(pair, list) and len(pair) == 2:
                    sub, sup = pair
                    graph[sub].add(sup)
            if not graph:
                print(
                    f"Warning: cached subclass graph at {cache_path} is empty. "
                    f"Deleting stale cache and re-fetching..."
                )
                cache_path.unlink(missing_ok=True)
                # fall through to re-fetch
            else:
                print(
                    f"Loaded subclass graph from cache: {cache_path} "
                    f"({len(graph)} subclasses)"
                )
                return graph, True
        except Exception as e:
            print(f"Warning: failed to load subclass cache, refetching. Error: {e}")

    if is_wikidata:
        query = """
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        SELECT DISTINCT ?subClass ?superClass WHERE {
            ?subClass wdt:P279 ?superClass .
            FILTER(isURI(?subClass) && isURI(?superClass))
        }
        """
    else:
        query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT DISTINCT ?subClass ?superClass
        WHERE {
          ?subClass (rdfs:subClassOf | owl:subClassOf) ?superClass .
          FILTER(isURI(?subClass) && isURI(?superClass))
        }
        """

    print("Prefetching subclass graph for local type minimization (bounded timeout: 120s)...")
    emit_event(
        event_sink,
        "stage.started",
        "abstat.subclass_prefetch",
        "Prefetching subclass graph for type minimization",
        {"endpoint": endpoint, "timeout": 120},
    )
    result = execute_sparql_query(
        query,
        endpoint=endpoint,
        format_type="csv",
        timeout=120,
    )

    if skip_event is not None and skip_event.is_set():
        print("Subclass graph prefetch stopped because cancellation was requested.")
        emit_event(
            event_sink,
            "stage.skipped",
            "abstat.subclass_prefetch",
            "Subclass graph prefetch stopped after cancellation",
            {"endpoint": endpoint},
        )
        return defaultdict(set), False

    graph = defaultdict(set)
    if result.get("success", False):
        df = result.get("results")
        if isinstance(df, pd.DataFrame) and {"subClass", "superClass"}.issubset(df.columns):
            for _, row in df.iterrows():
                sub = row.get("subClass")
                sup = row.get("superClass")
                if pd.notna(sub) and pd.notna(sup):
                    graph[str(sub)].add(str(sup))

    if not graph:
        subclass_rows = result.get("results")
        row_count = len(subclass_rows.index) if isinstance(subclass_rows, pd.DataFrame) else 0
        columns = list(subclass_rows.columns) if isinstance(subclass_rows, pd.DataFrame) else []
        print(
            f"WARNING: Subclass graph fetch returned 0 edges from endpoint '{endpoint}'. "
            f"The endpoint may be unavailable, slow, or this KG may not define rdfs:subClassOf/owl:subClassOf relations. "
            f"Type minimization will be skipped (all asserted types kept as-is). "
            f"Cache will NOT be saved so the fetch is retried next run."
        )
        emit_event(
            event_sink,
            "warning",
            "abstat.subclass_prefetch",
            "No subclass hierarchy was found for type minimization; continuing without hierarchy pruning.",
            {
                "endpoint": endpoint,
                "query": result.get("executed_query") or query,
                "executed_endpoint_url": result.get("executed_endpoint_url"),
                "result": {
                    "row_count": row_count,
                    "columns": columns,
                },
                "status": result.get("status"),
                "error": result.get("error"),
                "timeout": 120,
            },
        )
        return graph, True

    try:
        pairs = [[sub, sup] for sub, sups in graph.items() for sup in sups]
        if persist_cache:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"pairs": pairs}, f)
            print(
                f"Prefetched subclass graph: {len(graph)} subclasses, {len(pairs)} edges. "
                f"Saved to {cache_path}"
            )
        emit_event(
            event_sink,
            "stage.completed",
            "abstat.subclass_prefetch",
            "Subclass graph prefetched",
            {
                "endpoint": endpoint,
                "subclass_count": len(graph),
                "edge_count": len(pairs),
            },
        )
    except Exception as e:
        print(f"Warning: could not persist subclass graph cache: {e}")

    return graph, True


def is_subtype(
    t1: str,
    t2: str,
    subclass_graph: dict[str, set[str]],
    supertype_cache: dict[str, set[str]],
    endpoint: str,
    is_wikidata: bool = False,
    prefetch_subclass: bool = False,
    subclass_prefetched: bool = False,
) -> bool:
    """
    Returns True if t1 is a subtype of t2.
    Optimized: Resolves supertypes locally if prefetched, otherwise queries endpoint once and caches.
    """
    if t1 == t2:
        return True

    # Check cache (t1 -> set of supertypes)
    if t1 in supertype_cache:
        return t2 in supertype_cache[t1]

    # If subclass graph was prefetched, resolve supertypes locally (transitive closure BFS)
    if prefetch_subclass and subclass_prefetched:
        supertypes = {t1}
        stack = [t1]
        while stack:
            current = stack.pop()
            for sup in subclass_graph.get(current, set()):
                if sup not in supertypes:
                    supertypes.add(sup)
                    stack.append(sup)
        supertype_cache[t1] = supertypes
        return t2 in supertypes

    # Fetch all supertypes of t1 in a single query
    if is_wikidata:
        query = f"""
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        SELECT DISTINCT ?sup WHERE {{
            <{t1}> wdt:P279* ?sup .
        }}
        """
    else:
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?sup WHERE {{
            <{t1}> rdfs:subClassOf* ?sup .
        }}
        """

    result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")

    # Default to containing itself (reflexive property)
    supertypes = {t1}

    if result.get("success", False):
        df = result.get("results")
        if isinstance(df, pd.DataFrame) and "sup" in df.columns:
            supertypes.update(df["sup"].dropna().tolist())

    supertype_cache[t1] = supertypes
    return t2 in supertypes


def minimal_types(
    asserted_types: Iterable[str],
    is_subtype_fn: Callable[[str, str], bool],
) -> set[str]:
    """
    Given a set of asserted types, return the subset that are minimal
    (no strict subtype exists in the set). Paper-faithful instance-level minimization.
    """
    asserted = list(asserted_types)
    keep = set(asserted)
    for t in asserted:
        if t not in keep:
            continue
        for other in asserted:
            if t == other:
                continue
            if is_subtype_fn(other, t):
                if not is_subtype_fn(t, other):  # not equivalent
                    keep.discard(t)
                    break
    return keep
