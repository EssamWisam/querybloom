"""Minimal pattern extraction, instance-level minimization, and batch property driver."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import time
from typing import Any, Callable, Sequence

import pandas as pd
from tqdm import tqdm

from querybloom.events import EventSink, emit_event
from querybloom.executor.sparql_executor import execute_sparql_query
from querybloom.graph_serialization import patterns_to_cytoscape
from querybloom.abstat.cache import patterns_cache_path
from querybloom.abstat.domain_range import get_property_domain_range
from querybloom.abstat.properties import find_one_connected_property, get_distinct_properties
from querybloom.abstat.queries import build_type_filter


def compute_minimal_patterns(
    endpoint: str,
    is_wikidata: bool,
    predicate: str,
    max_triples: int,
    min_support: int,
    property_triple_count_cache: dict[str, int],
    minimal_types_fn: Callable[[Iterable[str]], set[str]],
    exclude_class_prefixes: Sequence[str] | None = None,
    include_class_prefixes: Sequence[str] | None = None,
    pbar: Any | None = None,
    rand_offset: bool = False,
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int], set[str]]:
    """
    Paper-style instance-level minimization for a single predicate.
    For each entity, keeps only its most specific asserted types,
    then rebuilds pattern counts from minimal type assignments.

    Returns:
        tuple (object_pattern_counts, attribute_pattern_counts, discovered_types)
    """
    display_name = predicate.split("/")[-1].split("#")[-1]

    s_filter = build_type_filter("?sType", exclude_class_prefixes, include_class_prefixes)
    o_filter = build_type_filter("?oType", exclude_class_prefixes, include_class_prefixes)

    # Compute random offset if requested
    offset_clause = ""
    if rand_offset:
        if predicate not in property_triple_count_cache:
            _search_uri = (
                predicate.replace("/entity/", "/prop/direct/")
                if is_wikidata
                else predicate
            )
            count_q = f"SELECT (COUNT(*) AS ?count) WHERE {{ ?s <{_search_uri}> ?o . }}"
            count_res = execute_sparql_query(
                count_q, endpoint=endpoint, format_type="csv"
            )
            total_count = 0
            if count_res.get("success"):
                try:
                    df_c = count_res.get("results")
                    if isinstance(df_c, pd.DataFrame) and not df_c.empty:
                        total_count = int(df_c.iloc[0]["count"])
                except Exception:
                    total_count = 0
            property_triple_count_cache[predicate] = total_count
        total_count = property_triple_count_cache[predicate]
        offset = (
            random.randint(0, max(0, total_count - max_triples))
            if total_count > max_triples
            else 0
        )
        if offset > 0:
            offset_clause = f" OFFSET {offset}"

    if is_wikidata:
        search_uri = predicate.replace("/entity/", "/prop/direct/")
        base_subquery = f"SELECT ?s ?o WHERE {{ ?s <{search_uri}> ?o . }} ORDER BY ?s ?o LIMIT {max_triples}{offset_clause}"
    else:
        base_subquery = f"SELECT ?s ?o WHERE {{ ?s <{predicate}> ?o . }} ORDER BY ?s ?o LIMIT {max_triples}{offset_clause}"

    # --- Query 1: Base triples (+ datatype for literals) ---
    q_triples = f"""
    SELECT ?s ?o (datatype(?o) AS ?dType) WHERE {{
        {{ {base_subquery} }}
    }}
    """

    res_triples = execute_sparql_query(
        q_triples, endpoint=endpoint, format_type="csv"
    )
    if not res_triples.get("success", False):
        if pbar:
            pbar.write(f"Property {display_name}: base triples query failed.")
        return {}, {}, set()

    df_triples = res_triples.get("results")
    if not isinstance(df_triples, pd.DataFrame) or df_triples.empty:
        if pbar:
            pbar.write(f"Property {display_name}: No triples returned.")
        return {}, {}, set()

    # Collect unique (s, o) pairs and literal datatypes
    triples: set[tuple[str, str]] = set()
    object_dtypes: dict[str, str] = {}
    has_iri_objects = False

    for row in df_triples.itertuples(index=False):
        s = str(row.s) if pd.notna(getattr(row, "s", None)) else None
        o = str(row.o) if pd.notna(getattr(row, "o", None)) else None
        if not s or not o:
            continue
        triples.add((s, o))
        dType = str(row.dType) if pd.notna(getattr(row, "dType", None)) else None
        if dType:
            object_dtypes[o] = dType
        else:
            has_iri_objects = True

    n_iri_objects = len(triples) - len(object_dtypes)
    if pbar:
        pbar.write(
            f"Property {display_name}: {len(triples)} triples, "
            f"~{n_iri_objects} IRI objects, "
            f"{len(object_dtypes)} literal objects"
        )

    # --- Query 2: Subject types via subquery ---
    if is_wikidata:
        q_stypes = f"""
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        SELECT DISTINCT ?s ?sType WHERE {{
            {{ SELECT DISTINCT ?s WHERE {{ {{ {base_subquery} }} }} }}
            ?s wdt:P31 ?sType .
            {s_filter}
        }}
        """
    else:
        q_stypes = f"""
        SELECT DISTINCT ?s ?sType WHERE {{
            {{ SELECT DISTINCT ?s WHERE {{ {{ {base_subquery} }} }} }}
            ?s a ?sType .
            {s_filter}
        }}
        """
    res_stypes = execute_sparql_query(
        q_stypes, endpoint=endpoint, format_type="csv"
    )
    subject_types = defaultdict(set)
    if res_stypes.get("success", False):
        df_st = res_stypes.get("results")
        if isinstance(df_st, pd.DataFrame) and not df_st.empty:
            for row in df_st.itertuples(index=False):
                s = str(row.s) if pd.notna(getattr(row, "s", None)) else None
                sType = str(row.sType) if pd.notna(getattr(row, "sType", None)) else None
                if s and sType:
                    subject_types[s].add(sType)

    # --- Query 3: Object types via subquery – only if IRI objects exist ---
    object_types = defaultdict(set)
    if has_iri_objects:
        if is_wikidata:
            q_otypes = f"""
            PREFIX wdt: <http://www.wikidata.org/prop/direct/>
            SELECT DISTINCT ?o ?oType WHERE {{
                {{ SELECT DISTINCT ?o WHERE {{
                    {{ {base_subquery} }}
                    FILTER(isIRI(?o))
                }} }}
                ?o wdt:P31 ?oType .
                {o_filter}
            }}
            """
        else:
            q_otypes = f"""
            SELECT DISTINCT ?o ?oType WHERE {{
                {{ SELECT DISTINCT ?o WHERE {{
                    {{ {base_subquery} }}
                    FILTER(isIRI(?o))
                }} }}
                ?o a ?oType .
                {o_filter}
            }}
            """
        res_otypes = execute_sparql_query(
            q_otypes, endpoint=endpoint, format_type="csv"
        )
        if res_otypes.get("success", False):
            df_ot = res_otypes.get("results")
            if isinstance(df_ot, pd.DataFrame) and not df_ot.empty:
                for row in df_ot.itertuples(index=False):
                    o = str(row.o) if pd.notna(getattr(row, "o", None)) else None
                    oType = str(row.oType) if pd.notna(getattr(row, "oType", None)) else None
                    if o and oType:
                        object_types[o].add(oType)

    if pbar:
        pbar.write(
            f"Property {display_name}: {len(subject_types)} typed subjects, "
            f"{len(object_types)} typed objects"
        )

    # --- Minimize types per entity (memoized by unique type set) ---
    _memo: dict[frozenset[str], set[str]] = {}
    min_subject_types: dict[str, set[str]] = {}
    for s, types in subject_types.items():
        key = frozenset(types)
        if key not in _memo:
            _memo[key] = minimal_types_fn(types)
        min_subject_types[s] = _memo[key]

    _memo_o: dict[frozenset[str], set[str]] = {}
    min_object_types: dict[str, set[str]] = {}
    for o, types in object_types.items():
        key = frozenset(types)
        if key not in _memo_o:
            _memo_o[key] = minimal_types_fn(types)
        min_object_types[o] = _memo_o[key]

    if pbar:
        pbar.write(
            f"Property {display_name}: {len(_memo)} unique subject type-sets, "
            f"{len(_memo_o)} unique object type-sets"
        )

    # --- Build pattern counts from minimal type assignments ---
    raw_object_pattern_counts = defaultdict(int)
    raw_attribute_pattern_counts = defaultdict(int)
    discovered_types: set[str] = set()

    for s, o in triples:
        s_types = min_subject_types.get(s, set())
        o_types = min_object_types.get(o, None)

        if o_types is not None:
            for st in s_types:
                for ot in o_types:
                    raw_object_pattern_counts[(st, ot)] += 1
                    discovered_types.add(st)
                    discovered_types.add(ot)
        else:
            dType = object_dtypes.get(o, "http://www.w3.org/2000/01/rdf-schema#Resource")
            for st in s_types:
                raw_attribute_pattern_counts[(st, dType)] += 1
                discovered_types.add(st)

    # Filter with min_support
    object_pattern_counts = {
        k: v for k, v in raw_object_pattern_counts.items() if v >= min_support
    }
    attribute_pattern_counts = {
        k: v for k, v in raw_attribute_pattern_counts.items() if v >= min_support
    }

    if pbar:
        pbar.write(
            f"Property {display_name}: {len(object_pattern_counts)} object + "
            f"{len(attribute_pattern_counts)} attribute minimal patterns (min_support={min_support})"
        )

    return object_pattern_counts, attribute_pattern_counts, discovered_types


def emit_cached_pattern_property_events(
    event_sink: EventSink | None,
    patterns: set[tuple[str, str, str]],
    attribute_patterns: set[tuple[str, str, str]],
    property_labels: dict[str, str],
    type_labels: dict[str, str],
    cache_path: Path,
) -> None:
    """Replay property summary events from cached pattern data for SSE consumers."""
    if event_sink is None:
        return

    summaries: dict[str, dict[str, Any]] = {}

    for pattern in patterns:
        if len(pattern) < 3:
            continue
        predicate = pattern[1]
        entry = summaries.setdefault(
            predicate,
            {
                "uri": predicate,
                "label": property_labels.get(predicate),
                "short_name": predicate.split("/")[-1].split("#")[-1],
                "count": 0,
                "added_object_patterns": 0,
                "added_attribute_patterns": 0,
                "type_uris": set(),
            },
        )
        entry["added_object_patterns"] += 1
        entry["type_uris"].add(pattern[0])
        entry["type_uris"].add(pattern[2])

    for pattern in attribute_patterns:
        if len(pattern) < 3:
            continue
        predicate = pattern[1]
        entry = summaries.setdefault(
            predicate,
            {
                "uri": predicate,
                "label": property_labels.get(predicate),
                "short_name": predicate.split("/")[-1].split("#")[-1],
                "count": 0,
                "added_object_patterns": 0,
                "added_attribute_patterns": 0,
                "type_uris": set(),
            },
        )
        entry["added_attribute_patterns"] += 1
        entry["type_uris"].add(pattern[0])
        entry["type_uris"].add(pattern[2])

    ordered = sorted(
        summaries.values(),
        key=lambda item: (
            item["added_object_patterns"] + item["added_attribute_patterns"],
            item.get("label") or item["uri"],
        ),
        reverse=True,
    )

    emit_event(
        event_sink,
        "properties.list",
        "abstat.properties",
        "Loaded property summaries from cache",
        {
            "count": len(ordered),
            "properties": [
                {
                    "uri": item["uri"],
                    "label": item.get("label"),
                    "short_name": item.get("short_name"),
                    "count": item.get("count", 0),
                }
                for item in ordered[:500]
            ],
            "truncated": len(ordered) > 500,
            "source": "cache",
            "path": str(cache_path),
        },
    )
    emit_event(
        event_sink,
        "properties.filtered",
        "abstat.properties",
        "Loaded filtered properties from cache",
        {
            "count": len(ordered),
            "source": "cache",
            "path": str(cache_path),
        },
    )

    total_object_patterns = 0
    total_attribute_patterns = 0
    for item in ordered:
        total_object_patterns += item["added_object_patterns"]
        total_attribute_patterns += item["added_attribute_patterns"]
        emit_event(
            event_sink,
            "property.completed",
            "abstat.property",
            f"Loaded cached patterns for {item.get('label') or item['short_name']}",
            {
                "uri": item["uri"],
                "label": item.get("label"),
                "short_name": item.get("short_name"),
                "num_new_types": len(item["type_uris"]),
                "added_object_patterns": item["added_object_patterns"],
                "added_attribute_patterns": item["added_attribute_patterns"],
                "total_object_patterns": total_object_patterns,
                "total_attribute_patterns": total_attribute_patterns,
                "source": "cache",
            },
        )

    emit_event(
        event_sink,
        "properties.discovered",
        "abstat.properties",
        "Loaded discovered types from cache",
        {
            "discovered_type_count": len(type_labels),
            "source": "cache",
        },
    )


def process_properties(
    abstat_instance: Any,
    property_limit: int = 20,
    max_triples: int = 20000,
    exclude_properties: Sequence[str] | None = None,
    exclude_classes: Sequence[str] | None = None,
    include_classes: Sequence[str] | None = None,
    minimize_patterns: bool = True,
    seed_property: str | None = None,
    min_support: int = 1,
    rand_offset: bool = False,
    use_cache: bool = True,
    persist_cache: bool = True,
    graph_limit: int | None = None,
    event_sink: EventSink | None = None,
    skip_event: Any | None = None,
    **kwargs: Any,
) -> None:
    """
    High-level driver for pattern discovery and extraction.
    Supports sequential processing of frequent properties or dynamic BFS discovery from a seed.
    """
    kwargs.pop("prefetch_subclass", None)

    patterns_cache_p = patterns_cache_path(
        cache_dir=abstat_instance.cache_dir,
        endpoint=abstat_instance.endpoint,
        property_limit=property_limit,
        max_triples=max_triples,
        minimize_patterns=minimize_patterns,
        min_support=min_support,
        exclude_properties=exclude_properties,
        exclude_classes=exclude_classes,
        include_classes=include_classes,
        seed_property=seed_property,
    )

    if use_cache and patterns_cache_p.exists():
        print(f"Loading patterns from cache: {patterns_cache_p}")
        with open(patterns_cache_p, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        abstat_instance.patterns = set(tuple(p) for p in cache_data["patterns"])
        abstat_instance.pattern_counts = defaultdict(int)
        for k_str, v in cache_data["pattern_counts"].items():
            k_list = json.loads(k_str)
            abstat_instance.pattern_counts[tuple(k_list)] = v

        abstat_instance.attribute_patterns = set(
            tuple(p) for p in cache_data["attribute_patterns"]
        )
        abstat_instance.attribute_counts = defaultdict(int)
        for k_str, v in cache_data["attribute_counts"].items():
            k_list = json.loads(k_str)
            abstat_instance.attribute_counts[tuple(k_list)] = v

        abstat_instance.property_labels = cache_data.get("property_labels", {})
        abstat_instance.type_labels = cache_data.get("type_labels", {})
        print(
            f"Loaded {len(abstat_instance.patterns)} object patterns and "
            f"{len(abstat_instance.attribute_patterns)} attribute patterns from cache."
        )
        emit_event(
            event_sink,
            "cache.loaded",
            "abstat.patterns",
            "Loaded patterns from cache",
            {
                "path": str(patterns_cache_p),
                "num_object_patterns": len(abstat_instance.patterns),
                "num_attribute_patterns": len(abstat_instance.attribute_patterns),
                "num_pattern_counts": len(abstat_instance.pattern_counts),
                "property_count": len(abstat_instance.property_labels),
                "type_count": len(abstat_instance.type_labels),
            },
        )
        emit_cached_pattern_property_events(
            event_sink,
            abstat_instance.patterns,
            abstat_instance.attribute_patterns,
            abstat_instance.property_labels,
            abstat_instance.type_labels,
            cache_path=patterns_cache_p,
        )
        return

    if minimize_patterns:
        abstat_instance.prefetch_subclass = True
        abstat_instance.prefetch_subclass_graph(
            use_cache=use_cache,
            persist_cache=persist_cache,
            skip_event=skip_event,
            event_sink=event_sink,
        )
        if skip_event is not None and skip_event.is_set():
            return

    # Normalize exclude list
    exclude_set: set[str] = set()
    if exclude_properties:
        for prop in exclude_properties:
            exclude_set.add(prop)
            if "label" in prop.lower():
                exclude_set.add("http://www.w3.org/2000/01/rdf-schema#label")
                exclude_set.add("label")

    if seed_property is None:
        top_properties = abstat_instance.get_distinct_properties(
            limit=property_limit,
            frequency=False,
            use_cache=use_cache,
            persist_cache=persist_cache,
            event_sink=event_sink,
        )
        print(f"\nProcessing {len(top_properties)} properties...")
        emit_event(
            event_sink,
            "properties.list",
            "abstat.properties",
            "Fetched property list",
            {
                "count": len(top_properties),
                "properties": [
                    {
                        "uri": item[0],
                        "count": int(item[1]) if item[1] is not None else None,
                        "label": item[2] if len(item) > 2 else None,
                    }
                    for item in top_properties[:500]
                ],
                "frequency": False,
                "truncated": len(top_properties) > 500,
            },
        )
    else:
        print(
            f"\nDynamic discovery mode: starting from seed property with limit {property_limit}"
        )
        top_properties = []

    def _process_one_property(p: str, p_label: str | None, pbar: Any) -> set[str]:
        p_short = p.split("/")[-1].split("#")[-1]
        display_name = f"{p_short} ({p_label})" if p_label else p_short
        before_object_patterns = len(abstat_instance.patterns)
        before_attribute_patterns = len(abstat_instance.attribute_patterns)

        emit_event(
            event_sink,
            "property.started",
            "abstat.property",
            f"Processing property {display_name}",
            {"uri": p, "label": p_label, "short_name": p_short},
        )

        if p_label:
            abstat_instance.property_labels[p] = p_label

        if minimize_patterns:
            obj_counts, attr_counts, new_types = abstat_instance.compute_minimal_patterns(
                predicate=p,
                max_triples=max_triples,
                min_support=min_support,
                exclude_class_prefixes=exclude_classes,
                include_class_prefixes=include_classes,
                pbar=pbar,
                rand_offset=rand_offset,
            )
            for (st, ot), count in obj_counts.items():
                abstat_instance.patterns.add((st, p, ot))
                abstat_instance.pattern_counts[(st, p, ot)] = count
            for (st, dt), count in attr_counts.items():
                abstat_instance.attribute_patterns.add((st, p, dt))
                abstat_instance.attribute_counts[(st, p, dt)] = count
        else:
            pbar.write(f"Property {display_name}: Fetching domain-range pairs...")
            domain_range_pairs = get_property_domain_range(
                property_uri=p,
                endpoint=abstat_instance.endpoint,
                max_triples=max_triples,
                min_support=min_support,
                exclude_class_prefixes=exclude_classes,
                include_class_prefixes=include_classes,
            )
            if not domain_range_pairs:
                pbar.write(f"Property {display_name}: No patterns found.")
                emit_event(
                    event_sink,
                    "property.completed",
                    "abstat.property",
                    f"No patterns found for {display_name}",
                    {
                        "uri": p,
                        "label": p_label,
                        "short_name": p_short,
                        "new_types": [],
                        "added_object_patterns": 0,
                        "added_attribute_patterns": 0,
                    },
                )
                return set()

            new_types = set()
            for pair in domain_range_pairs:
                if pair.get("subject_type_label") and pair["subject_type"]:
                    abstat_instance.type_labels[pair["subject_type"]] = pair["subject_type_label"]
                if pair.get("object_type_label") and pair["object_type"]:
                    abstat_instance.type_labels[pair["object_type"]] = pair["object_type_label"]
                if pair["subject_type"]:
                    new_types.add(pair["subject_type"])
                if pair["object_type"] and not pair.get("is_attribute", False):
                    new_types.add(pair["object_type"])

            for pair in domain_range_pairs:
                pat = (pair["subject_type"], p, pair["object_type"])
                if pair.get("is_attribute", False):
                    abstat_instance.attribute_patterns.add(pat)
                    abstat_instance.attribute_counts[pat] = pair["count"]
                else:
                    abstat_instance.patterns.add(pat)
                    abstat_instance.pattern_counts[pat] = pair["count"]

        # Fetch labels for surviving types in patterns
        surviving_types: set[str] = set()
        for s, prop, o in abstat_instance.patterns:
            if prop == p:
                surviving_types.add(s)
                surviving_types.add(o)
        for s, prop, o in abstat_instance.attribute_patterns:
            if prop == p:
                surviving_types.add(s)

        surviving_types = {
            t for t in surviving_types
            if t and not str(t).startswith("http://www.w3.org/2001/XMLSchema#")
        }

        if surviving_types:
            types_list = list(surviving_types)
            chunk_size = 250
            num_chunks = (len(types_list) + chunk_size - 1) // chunk_size
            pbar.write(
                f"Property {display_name}: Fetching labels for {len(surviving_types)} types ({num_chunks} chunk(s))..."
            )
            _t0 = time.time()
            for i in range(0, len(types_list), chunk_size):
                chunk = types_list[i : i + chunk_size]
                values_str = " ".join([f"<{t}>" for t in chunk if "://" in str(t)])
                if not values_str:
                    continue
                lbl_query = f"""
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?s ?label WHERE {{
                    VALUES ?s {{ {values_str} }}
                    ?s rdfs:label ?label .
                    FILTER(LANG(?label) = "en" || LANG(?label) = "")
                }}
                """
                lbl_res = execute_sparql_query(
                    lbl_query, endpoint=abstat_instance.endpoint, format_type="csv"
                )
                if lbl_res.get("success"):
                    res_df = lbl_res.get("results")
                    if isinstance(res_df, pd.DataFrame):
                        for _, r in res_df.iterrows():
                            if pd.notna(r.get("label")):
                                abstat_instance.type_labels[r["s"]] = str(r["label"])
            pbar.write(
                f"Property {display_name}: Labels done in {time.time() - _t0:.2f}s "
                f"({len([t for t in surviving_types if t in abstat_instance.type_labels])} found)"
            )

        emit_event(
            event_sink,
            "property.completed",
            "abstat.property",
            f"Processed property {display_name}",
            {
                "uri": p,
                "label": p_label,
                "short_name": p_short,
                "new_types": sorted(list(new_types))[:500],
                "num_new_types": len(new_types),
                "added_object_patterns": len(abstat_instance.patterns) - before_object_patterns,
                "added_attribute_patterns": len(abstat_instance.attribute_patterns) - before_attribute_patterns,
                "total_object_patterns": len(abstat_instance.patterns),
                "total_attribute_patterns": len(abstat_instance.attribute_patterns),
            },
        )

        if len(abstat_instance.patterns) > before_object_patterns:
            emit_event(
                event_sink,
                "graph.updated",
                "ontology",
                f"Pattern graph updated after {display_name}",
                {
                    "graph": patterns_to_cytoscape(
                        abstat_instance.patterns,
                        pattern_counts=abstat_instance.pattern_counts,
                        type_labels=abstat_instance.type_labels,
                        property_labels=abstat_instance.property_labels,
                        limit=graph_limit,
                    ),
                    "source_property": p,
                    "num_patterns": len(abstat_instance.patterns),
                    "num_attribute_patterns": len(abstat_instance.attribute_patterns),
                },
            )
        return new_types

    valid_properties: list[tuple[str, int | None, str | None]] = []
    for item in top_properties:
        if len(item) == 3:
            p, p_count, p_label = item
        else:
            p, p_count = item
            p_label = None
        p_short = p.split("/")[-1].split("#")[-1]
        if exclude_set and (p in exclude_set or p_short in exclude_set):
            print(f"Property {p_short}: SKIPPED (excluded)")
            continue
        valid_properties.append((p, p_count, p_label))

    if seed_property is None:
        pbar = tqdm(valid_properties, desc="Analyzing properties")
        emit_event(
            event_sink,
            "properties.filtered",
            "abstat.properties",
            "Prepared properties for analysis",
            {"count": len(valid_properties)},
        )
        for p, p_count, p_label in pbar:
            if skip_event is not None and skip_event.is_set():
                pbar.write("Discovery skipped by user — stopping early")
                break
            p_short = p.split("/")[-1].split("#")[-1]
            pbar.set_postfix(prop=p_short)
            _process_one_property(p, p_label, pbar)
    else:
        effective_limit = property_limit
        processed_uris: set[str] = set()
        discovered_types: set[str] = set()
        processed_properties: list[str] = []

        pbar = tqdm(total=effective_limit, desc="Analyzing properties (dynamic)")

        p_short = seed_property.split("/")[-1].split("#")[-1]
        if exclude_set and (seed_property in exclude_set or p_short in exclude_set):
            pbar.write(f"Seed property {p_short}: SKIPPED (excluded)")
            pbar.close()
            return

        pbar.set_postfix(prop=p_short)
        new_types = _process_one_property(seed_property, None, pbar)
        discovered_types.update(new_types)
        processed_uris.add(seed_property)
        processed_properties.append(seed_property)
        pbar.update(1)

        while len(processed_uris) < effective_limit:
            if skip_event is not None and skip_event.is_set():
                pbar.write("Discovery skipped by user — stopping early")
                break
            next_uri = find_one_connected_property(
                endpoint=abstat_instance.endpoint,
                is_wikidata=abstat_instance.is_wikidata,
                known_types=discovered_types,
                remaining_uris=None,
                exclude_uris=processed_uris,
            )

            if next_uri is None:
                pbar.write("No more connected properties found — stopping discovery")
                break

            p_short = next_uri.split("/")[-1].split("#")[-1]
            if exclude_set and (next_uri in exclude_set or p_short in exclude_set):
                pbar.write(f"Property {p_short}: SKIPPED (excluded)")
                processed_uris.add(next_uri)
                continue

            pbar.set_postfix(prop=p_short)
            new_types = _process_one_property(next_uri, None, pbar)
            discovered_types.update(new_types)
            processed_uris.add(next_uri)
            processed_properties.append(next_uri)
            pbar.update(1)

        pbar.close()
        print(
            f"Dynamic discovery: processed {len(processed_uris)} properties, "
            f"discovered {len(discovered_types)} types"
        )
        emit_event(
            event_sink,
            "properties.discovered",
            "abstat.properties",
            "Dynamic property discovery completed",
            {
                "processed_count": len(processed_uris),
                "discovered_type_count": len(discovered_types),
                "processed_properties": processed_properties,
            },
        )

    # Save patterns to cache
    cache_data = {
        "patterns": [list(p) for p in abstat_instance.patterns],
        "pattern_counts": {
            json.dumps(list(k)): v for k, v in abstat_instance.pattern_counts.items()
        },
        "attribute_patterns": [list(p) for p in abstat_instance.attribute_patterns],
        "attribute_counts": {
            json.dumps(list(k)): v for k, v in abstat_instance.attribute_counts.items()
        },
        "property_labels": abstat_instance.property_labels,
        "type_labels": abstat_instance.type_labels,
    }
    if persist_cache:
        with open(patterns_cache_p, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        print(
            f"\nSaved {len(abstat_instance.patterns)} object patterns and "
            f"{len(abstat_instance.attribute_patterns)} attribute patterns to cache: {patterns_cache_p}"
        )
        emit_event(
            event_sink,
            "cache.saved",
            "abstat.patterns",
            "Saved patterns to cache",
            {
                "path": str(patterns_cache_p),
                "num_object_patterns": len(abstat_instance.patterns),
                "num_attribute_patterns": len(abstat_instance.attribute_patterns),
            },
        )
