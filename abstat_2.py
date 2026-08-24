from collections import defaultdict
import random
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from tqdm import tqdm
import os
import json
import hashlib
from pathlib import Path
from querybloom.events import EventSink, emit_event
from querybloom.graph_serialization import patterns_to_cytoscape
from querybloom.executor.sparql_executor import execute_sparql_query



def get_property_domain_range(
    property_uri,
    endpoint="sockg",
    max_triples=20000,
    min_support=1,
    exclude_class_prefixes=None,
    include_class_prefixes=None,
):
    """
    Standalone function to find all domain-range (subject type, object type) combinations
    for a given property URI.

    Args:
        property_uri: The full URI of the property to analyze
        endpoint: The SPARQL endpoint to query
        max_triples: Maximum number of triples to sample (to avoid timeouts)

    Returns:
        List of dicts with keys: 'subject_type', 'object_type', 'count', 'subject_type_label', 'object_type_label'
        Returns empty list on error.
    """
    is_wikidata = "wikidata" in endpoint.lower()

    def _build_filter(var, exclude_prefixes, include_prefixes, optional_obj=False):
        clauses = []
        if include_prefixes:
            inc = " || ".join(
                [f'STRSTARTS(STR({var}), "{p}")' for p in include_prefixes]
            )
            clauses.append(f"({inc})")
        if exclude_prefixes:
            exc = " && ".join(
                [f'!STRSTARTS(STR({var}), "{p}")' for p in exclude_prefixes]
            )
            clauses.append(exc)
        if not clauses:
            return ""
        combined = " && ".join(clauses)
        if optional_obj:
            return f"FILTER(!BOUND({var}) || ({combined}))"
        return f"FILTER({combined})"

    subject_filter = _build_filter(
        "?sType", exclude_class_prefixes, include_class_prefixes
    )
    if is_wikidata:
        object_filter = _build_filter(
            "?oType", exclude_class_prefixes, include_class_prefixes, optional_obj=True
        )
    else:
        object_filter = _build_filter(
            "?finalOType", exclude_class_prefixes, include_class_prefixes
        )

    if is_wikidata:
        search_uri = property_uri.replace("/entity/", "/prop/direct/")

        query = f"""
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?sType ?oType ?dType (SUM(?pairCount) as ?count) (SAMPLE(?sLabel) as ?sTypeLabel) (SAMPLE(?oLabel) as ?oTypeLabel) WHERE {{
            {{
                # Step 1: Get the sample and count unique S-O pairs first
                SELECT ?s ?o (COUNT(*) as ?pairCount) WHERE {{
                    {{ SELECT ?s ?o WHERE {{ ?s <{search_uri}> ?o . }} LIMIT {max_triples} }}
                }} GROUP BY ?s ?o
            }}
            
            # Step 2: Join types to the unique entities only
            OPTIONAL {{ ?s wdt:P31 ?rawSType }}
            OPTIONAL {{ ?o wdt:P31 ?oType }}
            BIND(datatype(?o) AS ?dType)
            
            BIND(IF(BOUND(?rawSType), ?rawSType, wd:Q35120) AS ?sType)
            {subject_filter}
            {object_filter}

            OPTIONAL {{ ?sType rdfs:label ?sLabel . FILTER(LANG(?sLabel) = "en" || LANG(?sLabel) = "") }}
            OPTIONAL {{ ?oType rdfs:label ?oLabel . FILTER(LANG(?oLabel) = "en" || LANG(?oLabel) = "") }}
        }}
        GROUP BY ?sType ?oType ?dType
        """
    else:
        # Optimized: Split into two queries.
        # 1. Aggregation (Heavy): Calculate counts of types
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?sType ?finalOType ?dType (COUNT(*) as ?count) WHERE {{
            {{
                SELECT ?s ?o WHERE {{
                    ?s <{property_uri}> ?o .
                }} LIMIT {max_triples}
            }}
            ?s a ?sType .
            
            # Optimization: Only check rdf:type if object is a URI (skips literals)
            OPTIONAL {{ FILTER(isIRI(?o)) . ?o a ?rawOType }}
            
            BIND(datatype(?o) AS ?dType)
            # Use explicit type if available, otherwise use a marker for processing later
            BIND(IF(BOUND(?rawOType), ?rawOType, <urn:untyped>) AS ?finalOType)
            {subject_filter}
            {object_filter}
        }}
        GROUP BY ?sType ?finalOType ?dType
        HAVING (COUNT(*) >= {min_support})
        """

    result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")

    if not result.get("success", False):
        error_msg = result.get("error", "Unknown error")
        print(f"Error fetching domain-range for property: {error_msg}")
        return []

    df = result.get("results")

    if not isinstance(df, pd.DataFrame) or df.empty:
        return []

    # Labels are fetched after minimization (only for surviving types)
    type_labels_map = {}

    domain_range_pairs = []

    for _, row in df.iterrows():
        sType = row.get("sType") if pd.notna(row.get("sType")) else None
        if not sType:
            continue

        # Handle both old column name (oType) and new column name (finalOType)
        oType = (
            row.get("finalOType") if "finalOType" in df.columns else row.get("oType")
        )
        oType = oType if pd.notna(oType) else None

        dType = row.get("dType") if pd.notna(row.get("dType")) else None
        count = int(row.get("count")) if pd.notna(row.get("count")) else 0

        # Retrieve labels from map (fast) or row (legacy/Wikidata)
        if not is_wikidata:
            sTypeLabel = type_labels_map.get(sType)
            oTypeLabel = type_labels_map.get(oType)
        else:
            sTypeLabel = (
                row.get("sTypeLabel") if pd.notna(row.get("sTypeLabel")) else None
            )
            oTypeLabel = (
                row.get("oTypeLabel") if pd.notna(row.get("oTypeLabel")) else None
            )

        # Check for the untyped marker
        is_untyped_marker = oType and (
            oType == "urn:untyped" or "urn:untyped" in str(oType)
        )

        # Determine Object Type: explicit type > datatype > fallback
        is_attribute = False
        if oType and not is_untyped_marker:
            final_oType = oType
        elif dType:
            final_oType = dType  # Use datatype URI as type
            is_attribute = True
        else:
            final_oType = "http://www.w3.org/2000/01/rdf-schema#Resource"  # Fallback

        domain_range_pairs.append(
            {
                "subject_type": sType,
                "object_type": final_oType,
                "count": count,
                "subject_type_label": sTypeLabel,
                "object_type_label": oTypeLabel,
                "is_attribute": is_attribute,
            }
        )

    return domain_range_pairs


class ABSTAT_v2:
    def __init__(self, endpoint="sockg"):
        self.endpoint = endpoint
        self.is_wikidata = "wikidata" in endpoint.lower()
        self.supertype_cache = {}  # Cache: Type -> Set[Supertypes]
        self.subclass_graph = defaultdict(set)  # subClass -> set(superClass)
        self.prefetch_subclass = False
        self.subclass_prefetched = False
        self.patterns = set()  # Minimal Type Patterns (C, P, D)
        self.pattern_counts = defaultdict(int)
        self.attribute_patterns = (
            set()
        )  # Minimal Attribute Patterns (C, P, LiteralType)
        self.attribute_counts = defaultdict(int)
        self.property_labels = {}  # Cache: PropertyURI -> Label
        self.type_labels = {}  # Cache: TypeURI -> Label
        self.cache_dir = Path(__file__).parent / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        self._property_triple_count_cache: dict = (
            {}
        )  # Cache: predicate -> total triple count

    def prefetch_subclass_graph(
        self,
        use_cache=True,
        persist_cache=True,
        skip_event=None,
        event_sink: EventSink | None = None,
    ):
        """
        Prefetches global subclass edges once and caches them on disk.
        Used to make is_subtype checks local during minimization.
        """
        safe_endpoint = (
            str(self.endpoint).replace("/", "_").replace(":", "_").replace(".", "_")
        )
        cache_path = self.cache_dir / f"subclass_edges_{safe_endpoint}.json"

        if skip_event is not None and skip_event.is_set():
            print("Subclass graph prefetch skipped because cancellation was requested.")
            return

        if use_cache and cache_path.exists():
            try:
                with open(cache_path, "r") as f:
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
                    self.subclass_graph = graph
                    self.subclass_prefetched = True
                    print(
                        f"Loaded subclass graph from cache: {cache_path} "
                        f"({len(self.subclass_graph)} subclasses)"
                    )
                    return
            except Exception as e:
                print(f"Warning: failed to load subclass cache, refetching. Error: {e}")

        if self.is_wikidata:
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

        print(
            "Prefetching subclass graph for local type minimization (bounded timeout: 120s)..."
        )
        emit_event(
            event_sink,
            "stage.started",
            "abstat.subclass_prefetch",
            "Prefetching subclass graph for type minimization",
            {"endpoint": self.endpoint, "timeout": 120},
        )
        result = execute_sparql_query(
            query,
            endpoint=self.endpoint,
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
                {"endpoint": self.endpoint},
            )
            return

        graph = defaultdict(set)
        if result.get("success", False):
            df = result.get("results")
            if isinstance(df, pd.DataFrame) and {"subClass", "superClass"}.issubset(
                df.columns
            ):
                for _, row in df.iterrows():
                    sub = row.get("subClass")
                    sup = row.get("superClass")
                    if pd.notna(sub) and pd.notna(sup):
                        graph[str(sub)].add(str(sup))

        self.subclass_graph = graph
        self.subclass_prefetched = True

        if not graph:
            subclass_rows = result.get("results")
            row_count = (
                len(subclass_rows.index)
                if isinstance(subclass_rows, pd.DataFrame)
                else 0
            )
            columns = (
                list(subclass_rows.columns)
                if isinstance(subclass_rows, pd.DataFrame)
                else []
            )
            print(
                f"WARNING: Subclass graph fetch returned 0 edges from endpoint '{self.endpoint}'. "
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
                    "endpoint": self.endpoint,
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
            return

        try:
            pairs = [[sub, sup] for sub, sups in graph.items() for sup in sups]
            if persist_cache:
                with open(cache_path, "w") as f:
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
                    "endpoint": self.endpoint,
                    "subclass_count": len(graph),
                    "edge_count": len(pairs),
                },
            )
        except Exception as e:
            print(f"Warning: could not persist subclass graph cache: {e}")

    def _minimal_types(self, asserted_types):
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
                if self.is_subtype(other, t):
                    if not self.is_subtype(t, other):  # not equivalent
                        keep.discard(t)
                        break
        return keep

    def is_subtype(self, t1, t2):
        """
        Returns True if t1 is a subtype of t2.
        Optimized: Fetches ALL supertypes of t1 once and caches them.
        """
        if t1 == t2:
            return True

        # Check cache (t1 -> set of supertypes)
        if t1 in self.supertype_cache:
            return t2 in self.supertype_cache[t1]

        # If subclass graph was prefetched, resolve supertypes locally (transitive closure)
        if self.prefetch_subclass and self.subclass_prefetched:
            supertypes = {t1}
            stack = [t1]
            while stack:
                current = stack.pop()
                for sup in self.subclass_graph.get(current, set()):
                    if sup not in supertypes:
                        supertypes.add(sup)
                        stack.append(sup)
            self.supertype_cache[t1] = supertypes
            return t2 in supertypes

        # Fetch all supertypes of t1 in a single query
        if self.is_wikidata:
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

        result = execute_sparql_query(query, endpoint=self.endpoint, format_type="csv")

        # Default to containing itself (reflexive property)
        supertypes = {t1}

        if result.get("success", False):
            # When format_type="csv", results is a pandas DataFrame
            df = result.get("results")
            if isinstance(df, pd.DataFrame) and "sup" in df.columns:
                supertypes.update(df["sup"].dropna().tolist())

        self.supertype_cache[t1] = supertypes
        return t2 in supertypes

    def get_distinct_properties(
        self,
        limit=None,
        frequency=True,
        use_cache=True,
        persist_cache=True,
        event_sink: EventSink | None = None,
    ):
        """
        Fetches properties from the endpoint.
        If frequency=True, orders by occurrence count (slower).
        If frequency=False, just fetches distinct properties (faster).
        Returns list of (property_uri, count, label). Count is None if frequency=False. Label is None if not available.
        """
        # --- Caching logic ---
        # Sanitize endpoint name for filename
        safe_endpoint = (
            str(self.endpoint).replace("/", "_").replace(":", "_").replace(".", "_")
        )
        cache_filename = f"props_{safe_endpoint}_lim{limit}_freq{frequency}.json"
        cache_path = self.cache_dir / cache_filename

        if use_cache and cache_path.exists():
            print(f"Loading properties from cache: {cache_path}")
            with open(cache_path, "r") as f:
                properties = json.load(f)
            emit_event(
                event_sink,
                "cache.loaded",
                "abstat.properties",
                "Loaded properties from cache",
                {
                    "path": str(cache_path),
                    "count": len(properties),
                    "frequency": bool(frequency),
                },
            )
            return properties
        # ---------------------

        action = "top properties by frequency" if frequency else "distinct properties"
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        print(f"Fetching {action} (limit={limit})...")

        if self.is_wikidata:
            print(
                "Wikidata mode: Using wikibase:Property query (counts disabled) with labels."
            )
            query = f"""
            PREFIX wikibase: <http://wikiba.se/ontology#>

            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            PREFIX wd: <http://www.wikidata.org/entity/>

            PREFIX wdt: <http://www.wikidata.org/prop/direct/>

            SELECT ?p ?pLabel WHERE {{

            # 1. Start with the Property entity itself

            ?p a wikibase:Property .

            # 2. Filter for "Object" properties (Item to Item) 

            # This excludes IDs, strings, and numbers.

            ?p wikibase:propertyType wikibase:WikibaseItem .

            

            # 3. Fast label lookup in QLever

            ?p rdfs:label ?pLabel .

            FILTER(LANG(?pLabel) = "en" || LANG(?pLabel) = "")

            }}
            ORDER BY RAND()
            {limit_clause}
            """
        elif frequency:
            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?p (SAMPLE(?label) as ?pLabel) (COUNT(*) AS ?count) WHERE {{
                ?s ?p ?o .
                OPTIONAL {{ 
                    ?p rdfs:label ?label . 
                    FILTER(LANG(?label) = "en" || LANG(?label) = "") 
                }}
            }} 
            GROUP BY ?p 
            ORDER BY DESC(?count) 
            {limit_clause}
            """
        else:
            # Optimized: Split into two queries to avoid massive memory usage on optional join
            query = f"""
            SELECT DISTINCT ?p WHERE {{
                ?s ?p ?o .
            }} 
            {limit_clause}
            """

        # Optimized: Use CSV to avoid JSON parsing overhead
        result = execute_sparql_query(query, endpoint=self.endpoint, format_type="csv")

        if not result.get("success", False):
            error_message = result.get("error") or "Unknown error"
            message = f"Failed to fetch properties from {self.endpoint}."
            print(f"{message} {error_message}")
            emit_event(
                event_sink,
                "error",
                "abstat.properties",
                message,
                {
                    "endpoint": self.endpoint,
                    "status": result.get("status"),
                    "error": error_message,
                    "query": result.get("executed_query") or query,
                    "executed_endpoint_url": result.get("executed_endpoint_url"),
                },
            )
            raise RuntimeError(message)

        df = result.get("results")
        if not isinstance(df, pd.DataFrame):
            message = f"Failed to fetch properties from {self.endpoint}."
            print(
                f"{message} Unexpected results format {type(df).__name__}"
            )
            emit_event(
                event_sink,
                "error",
                "abstat.properties",
                message,
                {
                    "endpoint": self.endpoint,
                    "error": f"Unexpected results format {type(df).__name__}",
                    "result_type": type(df).__name__,
                    "query": result.get("executed_query") or query,
                    "executed_endpoint_url": result.get("executed_endpoint_url"),
                },
            )
            raise RuntimeError(message)

        properties = []

        def get_label(row):
            label = row.get("pLabel")
            return str(label) if pd.notna(label) else None

        if self.is_wikidata:
            if "p" in df.columns:
                for _, row in df.iterrows():
                    properties.append((row["p"], None, get_label(row)))
        elif frequency:
            # Check required columns exist
            if "p" in df.columns and "count" in df.columns:
                for _, row in df.iterrows():
                    p = row["p"]
                    count = row["count"]

                    # Skip built-in properties that clutter the view
                    if p not in ["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"]:
                        properties.append((p, count, get_label(row)))
        else:
            # Non-frequency, distinct properties case
            if "p" in df.columns:
                found_uris = []
                for _, row in df.iterrows():
                    p = row["p"]
                    if p not in ["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"]:
                        found_uris.append(p)

                # Batch fetch labels for found URIs
                labels_map = {}
                if found_uris:
                    # Construct VALUES block
                    # Step 2: Fetch labels for these properties
                    chunk_size = 100
                    for i in range(0, len(found_uris), chunk_size):
                        chunk = found_uris[i : i + chunk_size]
                        values_str = " ".join([f"<{uri}>" for uri in chunk])

                        label_query = f"""
                        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                        SELECT ?p ?pLabel WHERE {{
                            VALUES ?p {{ {values_str} }}
                            ?p rdfs:label ?pLabel .
                            FILTER(LANG(?pLabel) = "en" || LANG(?pLabel) = "")
                        }}
                        """
                        res_lbl = execute_sparql_query(
                            label_query, endpoint=self.endpoint, format_type="csv"
                        )
                        if res_lbl.get("success", False):
                            df_lbl = res_lbl.get("results")
                            if isinstance(df_lbl, pd.DataFrame):
                                for _, lrow in df_lbl.iterrows():
                                    if pd.notna(lrow.get("pLabel")):
                                        labels_map[lrow["p"]] = str(lrow["pLabel"])

                # Build final list
                for p in found_uris:
                    # Use label if found, else None
                    properties.append((p, None, labels_map.get(p)))

        print(f"Found {len(properties)} properties.")

        if not properties:
            row_count = len(df.index) if isinstance(df, pd.DataFrame) else 0
            columns = list(df.columns) if isinstance(df, pd.DataFrame) else []
            message = f"No properties were found for {self.endpoint}."
            emit_event(
                event_sink,
                "error",
                "abstat.properties",
                message,
                {
                    "endpoint": self.endpoint,
                    "query": result.get("executed_query") or query,
                    "requested_query": query,
                    "executed_endpoint_url": result.get("executed_endpoint_url"),
                    "result": {
                        "success": result.get("success"),
                        "status": result.get("status"),
                        "row_count": row_count,
                        "columns": columns,
                        "usable_property_count": len(properties),
                    },
                    "details": "The property-discovery SPARQL query returned 0 usable rows.",
                    "hint": "For FRINK endpoints, try the direct KG endpoint as a custom endpoint if the federated FROM graph is empty or misconfigured.",
                },
            )
            raise RuntimeError(message)

        # Save to cache
        if persist_cache and properties:
            with open(cache_path, "w") as f:
                json.dump(properties, f)
            print(f"Saved properties to cache: {cache_path}")

        return properties

    def _emit_cached_pattern_property_events(self, event_sink: EventSink | None, *, cache_path: Path):
        if event_sink is None:
            return

        summaries = {}

        for pattern in self.patterns:
            if len(pattern) < 3:
                continue
            predicate = pattern[1]
            entry = summaries.setdefault(
                predicate,
                {
                    "uri": predicate,
                    "label": self.property_labels.get(predicate),
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

        for pattern in self.attribute_patterns:
            if len(pattern) < 3:
                continue
            predicate = pattern[1]
            entry = summaries.setdefault(
                predicate,
                {
                    "uri": predicate,
                    "label": self.property_labels.get(predicate),
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
                "discovered_type_count": len(self.type_labels),
                "source": "cache",
            },
        )

    def find_one_connected_property(
        self,
        known_types,
        remaining_uris=None,
        exclude_uris=None,
    ):
        """
        Find a single unprocessed property connected to any of the known types.

        For each known type, asks the endpoint for properties used by instances
        of that type (domain or range side). Returns the first one that is in
        ``remaining_uris`` (if provided), otherwise returns the first discovered property.

        Args:
            known_types: Set of type URIs already discovered
            remaining_uris: Optional set of property URIs to filter by. If None, any discovered property is valid.

        Returns:
            A single property URI (str) that is connected, or None
        """
        if not known_types:
            return None

        type_pred = "wdt:P31" if self.is_wikidata else "a"
        prefix = (
            "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
            if self.is_wikidata
            else ""
        )

        for t in known_types:
            # Domain side: instances of type t as subject
            query = f"""{prefix}SELECT DISTINCT ?p WHERE {{
                    ?s {type_pred} <{t}> .
                    ?s ?p ?o .
                }} LIMIT 50
                """
            result = execute_sparql_query(
                query, endpoint=self.endpoint, format_type="csv"
            )
            if result.get("success", False):
                df = result.get("results")
                if isinstance(df, pd.DataFrame) and "p" in df.columns:
                    for p in df["p"].dropna().tolist():
                        if exclude_uris and p in exclude_uris:
                            continue
                        if remaining_uris is None or p in remaining_uris:
                            return p

            # Range side: instances of type t as object
            query = f"""{prefix}SELECT DISTINCT ?p WHERE {{
                    ?o {type_pred} <{t}> .
                    ?s ?p ?o .
                }} LIMIT 50
                """
            result = execute_sparql_query(
                query, endpoint=self.endpoint, format_type="csv"
            )
            if result.get("success", False):
                df = result.get("results")
                if isinstance(df, pd.DataFrame) and "p" in df.columns:
                    for p in df["p"].dropna().tolist():
                        if exclude_uris and p in exclude_uris:
                            continue
                        if remaining_uris is None or p in remaining_uris:
                            return p

        return None

    def process_properties(
        self,
        property_limit=20,
        max_triples=20000,
        exclude_properties=None,
        exclude_classes=None,
        include_classes=None,
        minimize_patterns=True,
        seed_property=None,
        min_support=1,
        rand_offset=False,
        use_cache=True,
        persist_cache=True,
        graph_limit=None,
        event_sink: EventSink | None = None,
        skip_event=None,
        **kwargs,
    ):
        """
        Core ABSTAT 2.0 Logic:
        Iterates over frequent properties and fetches type pairs directly.
        When minimize_patterns=True, uses paper-faithful instance-level minimization:
        for each entity, keeps only its most specific asserted types, then rebuilds
        pattern counts from minimal type assignments.

        Args:
            property_limit: Number of properties to process (or limit for dynamic discovery when seed_property is used)
            max_triples: Maximum triples per property
            exclude_properties: List of property URIs or short names to exclude
            exclude_classes: List of URI prefixes — types starting with any of these will be excluded
                (e.g. ['http://www.wikidata.org', 'http://schema.org'])
            include_classes: List of URI prefixes — ONLY types starting with one of these are kept
                (whitelist; takes precedence when combined with exclude_classes)
                (e.g. ['http://dbpedia.org/ontology/'])
            minimize_patterns: If False, skip minimization (faster but redundant patterns)
            seed_property: If provided (URI), start from this seed property and use dynamic discovery
                to explore connected properties. property_limit becomes the extraction limit.
        """
        # Accept legacy prefetch_subclass kwarg (ignored — always prefetch when minimizing)
        kwargs.pop("prefetch_subclass", None)
        # --- Pattern Caching Logic ---
        # Create a cache key based on processing parameters
        safe_endpoint = (
            str(self.endpoint).replace("/", "_").replace(":", "_").replace(".", "_")
        )
        exclude_key = (
            "_".join(sorted(exclude_properties)) if exclude_properties else "none"
        )
        exclude_hash = hashlib.md5(exclude_key.encode()).hexdigest()[:8]
        classes_key = "_".join(sorted(exclude_classes)) if exclude_classes else "none"
        classes_hash = hashlib.md5(classes_key.encode()).hexdigest()[:8]
        include_key = "_".join(sorted(include_classes)) if include_classes else "none"
        include_hash = hashlib.md5(include_key.encode()).hexdigest()[:8]
        seed_tag = (
            f"_seed{hashlib.md5(seed_property.encode()).hexdigest()[:8]}"
            if seed_property is not None
            else ""
        )
        patterns_cache_filename = f"patterns_{safe_endpoint}_lim{property_limit}_max{max_triples}_min{minimize_patterns}_ms{min_support}_ex{exclude_hash}_cl{classes_hash}_inc{include_hash}_paper{seed_tag}.json"
        patterns_cache_path = self.cache_dir / patterns_cache_filename

        if use_cache and patterns_cache_path.exists():
            print(f"Loading patterns from cache: {patterns_cache_path}")
            with open(patterns_cache_path, "r") as f:
                cache_data = json.load(f)
                # Restore patterns as sets of tuples
                self.patterns = set(tuple(p) for p in cache_data["patterns"])
                # Parse pattern_counts keys from JSON strings back to tuples
                self.pattern_counts = defaultdict(int)
                for k_str, v in cache_data["pattern_counts"].items():
                    # Convert string representation back to list, then to tuple
                    k_list = json.loads(k_str)
                    self.pattern_counts[tuple(k_list)] = v

                self.attribute_patterns = set(
                    tuple(p) for p in cache_data["attribute_patterns"]
                )
                # Parse attribute_counts keys from JSON strings back to tuples
                self.attribute_counts = defaultdict(int)
                for k_str, v in cache_data["attribute_counts"].items():
                    k_list = json.loads(k_str)
                    self.attribute_counts[tuple(k_list)] = v

                self.property_labels = cache_data.get("property_labels", {})
                self.type_labels = cache_data.get("type_labels", {})
                print(
                    f"Loaded {len(self.patterns)} object patterns and {len(self.attribute_patterns)} attribute patterns from cache."
                )
                emit_event(
                    event_sink,
                    "cache.loaded",
                    "abstat.patterns",
                    "Loaded patterns from cache",
                    {
                        "path": str(patterns_cache_path),
                        "num_object_patterns": len(self.patterns),
                        "num_attribute_patterns": len(self.attribute_patterns),
                        "num_pattern_counts": len(self.pattern_counts),
                        "property_count": len(self.property_labels),
                        "type_count": len(self.type_labels),
                    },
                )
                self._emit_cached_pattern_property_events(event_sink, cache_path=patterns_cache_path)
                return
        # ---------------------

        if minimize_patterns:
            self.prefetch_subclass = True
            self.prefetch_subclass_graph(
                use_cache=use_cache,
                persist_cache=persist_cache,
                skip_event=skip_event,
                event_sink=event_sink,
            )
            if skip_event is not None and skip_event.is_set():
                return

        # Normalize exclude list
        exclude_set = set()
        if exclude_properties:
            for prop in exclude_properties:
                exclude_set.add(prop)  # Add as-is
                # Also add common variations
                if "label" in prop.lower():
                    exclude_set.add("http://www.w3.org/2000/01/rdf-schema#label")
                    exclude_set.add("label")

        if seed_property is None:
            # Fetch top properties for constraint/filtering
            top_properties = self.get_distinct_properties(
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
            # No need to fetch all properties, will discover dynamically
            top_properties = []

        # --- Helper: process a single property (domain-range + minimization) ---
        def _process_one_property(p, p_label, pbar):
            """Process one property: fetch instance-level types, minimize, store patterns.
            Returns the set of types discovered from this property."""
            p_short = p.split("/")[-1].split("#")[-1]
            display_name = f"{p_short} ({p_label})" if p_label else p_short
            before_object_patterns = len(self.patterns)
            before_attribute_patterns = len(self.attribute_patterns)

            emit_event(
                event_sink,
                "property.started",
                "abstat.property",
                f"Processing property {display_name}",
                {"uri": p, "label": p_label, "short_name": p_short},
            )

            if p_label:
                self.property_labels[p] = p_label

            if minimize_patterns:
                # Paper-style instance-level minimization (single SPARQL call)
                new_types = self.compute_minimal_patterns(
                    predicate=p,
                    max_triples=max_triples,
                    min_support=min_support,
                    exclude_class_prefixes=exclude_classes,
                    include_class_prefixes=include_classes,
                    pbar=pbar,
                    rand_offset=rand_offset,
                )
            else:
                # No minimization — use aggregated approach
                pbar.write(f"Property {display_name}: Fetching domain-range pairs...")
                domain_range_pairs = get_property_domain_range(
                    property_uri=p,
                    endpoint=self.endpoint,
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
                        self.type_labels[pair["subject_type"]] = pair[
                            "subject_type_label"
                        ]
                    if pair.get("object_type_label") and pair["object_type"]:
                        self.type_labels[pair["object_type"]] = pair[
                            "object_type_label"
                        ]
                    if pair["subject_type"]:
                        new_types.add(pair["subject_type"])
                    if pair["object_type"] and not pair.get("is_attribute", False):
                        new_types.add(pair["object_type"])

                for pair in domain_range_pairs:
                    pat = (pair["subject_type"], p, pair["object_type"])
                    if pair.get("is_attribute", False):
                        self.attribute_patterns.add(pat)
                        self.attribute_counts[pat] = pair["count"]
                    else:
                        self.patterns.add(pat)
                        self.pattern_counts[pat] = pair["count"]

            # --- Fetch labels only for types that survived into patterns ---
            surviving_types = set()
            for s, prop, o in self.patterns:
                if prop == p:
                    surviving_types.add(s)
                    surviving_types.add(o)
            for s, prop, o in self.attribute_patterns:
                if prop == p:
                    surviving_types.add(s)
            surviving_types = {
                t
                for t in surviving_types
                if t and not str(t).startswith("http://www.w3.org/2001/XMLSchema#")
            }
            if surviving_types:
                import time as _time

                types_list = list(surviving_types)
                chunk_size = 250
                num_chunks = (len(types_list) + chunk_size - 1) // chunk_size
                pbar.write(
                    f"Property {display_name}: Fetching labels for {len(surviving_types)} types ({num_chunks} chunk(s))..."
                )
                _t0 = _time.time()
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
                        lbl_query, endpoint=self.endpoint, format_type="csv"
                    )
                    if lbl_res.get("success"):
                        res_df = lbl_res.get("results")
                        if isinstance(res_df, pd.DataFrame):
                            for _, r in res_df.iterrows():
                                if pd.notna(r.get("label")):
                                    self.type_labels[r["s"]] = str(r["label"])
                pbar.write(
                    f"Property {display_name}: Labels done in {_time.time() - _t0:.2f}s ({len([t for t in surviving_types if t in self.type_labels])} found)"
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
                    "added_object_patterns": len(self.patterns) - before_object_patterns,
                    "added_attribute_patterns": len(self.attribute_patterns) - before_attribute_patterns,
                    "total_object_patterns": len(self.patterns),
                    "total_attribute_patterns": len(self.attribute_patterns),
                },
            )

            # The live ontology graph only renders object-property patterns.
            # Skip graph refreshes for attribute-only changes to avoid no-op updates.
            if len(self.patterns) > before_object_patterns:
                emit_event(
                    event_sink,
                    "graph.updated",
                    "ontology",
                    f"Pattern graph updated after {display_name}",
                    {
                        "graph": patterns_to_cytoscape(
                            self.patterns,
                            pattern_counts=self.pattern_counts,
                            type_labels=self.type_labels,
                            property_labels=self.property_labels,
                            limit=graph_limit,
                        ),
                        "source_property": p,
                        "num_patterns": len(self.patterns),
                        "num_attribute_patterns": len(self.attribute_patterns),
                    },
                )
            return new_types

        # --- Build valid property list (filtering excludes) ---
        valid_properties = []  # list of (uri, count, label)
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
            # --- Original mode: process all properties sequentially ---
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
            # --- Dynamic discovery mode: start from seed property ---
            effective_limit = property_limit
            processed_uris = set()
            discovered_types = set()
            processed_properties = []  # Track what we've processed

            pbar = tqdm(total=effective_limit, desc="Analyzing properties (dynamic)")

            # Step 1: Process the seed property
            p_short = seed_property.split("/")[-1].split("#")[-1]

            # Check if seed is excluded
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

            # Step 2: Greedy BFS — dynamically discover connected properties
            while len(processed_uris) < effective_limit:
                if skip_event is not None and skip_event.is_set():
                    pbar.write("Discovery skipped by user — stopping early")
                    break
                next_uri = self.find_one_connected_property(
                    known_types=discovered_types,
                    remaining_uris=None,  # No constraint - discover any property
                    exclude_uris=processed_uris,
                )

                if next_uri is None:
                    # No more connected properties found
                    pbar.write(
                        "No more connected properties found — stopping discovery"
                    )
                    break

                # Check if excluded — add to processed so it isn't returned again
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

        # --- Save patterns to cache ---
        cache_data = {
            "patterns": [list(p) for p in self.patterns],
            "pattern_counts": {
                json.dumps(list(k)): v for k, v in self.pattern_counts.items()
            },
            "attribute_patterns": [list(p) for p in self.attribute_patterns],
            "attribute_counts": {
                json.dumps(list(k)): v for k, v in self.attribute_counts.items()
            },
            "property_labels": self.property_labels,
            "type_labels": self.type_labels,
        }
        if persist_cache:
            with open(patterns_cache_path, "w") as f:
                json.dump(cache_data, f, indent=2)
            print(
                f"\nSaved {len(self.patterns)} object patterns and {len(self.attribute_patterns)} attribute patterns to cache: {patterns_cache_path}"
            )
            emit_event(
                event_sink,
                "cache.saved",
                "abstat.patterns",
                "Saved patterns to cache",
                {
                    "path": str(patterns_cache_path),
                    "num_object_patterns": len(self.patterns),
                    "num_attribute_patterns": len(self.attribute_patterns),
                },
            )
        # ---------------------

    def compute_minimal_patterns(
        self,
        predicate,
        max_triples,
        min_support,
        exclude_class_prefixes=None,
        include_class_prefixes=None,
        pbar=None,
        rand_offset=False,
    ):
        """
        Paper-style instance-level minimization.
        For each entity, keeps only its most specific asserted types,
        then rebuilds pattern counts from minimal type assignments.

        Returns: set of discovered type URIs
        """
        display_name = predicate.split("/")[-1].split("#")[-1]

        # --- Build include/exclude FILTER clauses ---
        def _type_filter(var, excl, incl):
            clauses = []
            if incl:
                inc = " || ".join([f'STRSTARTS(STR({var}), "{p}")' for p in incl])
                clauses.append(f"({inc})")
            if excl:
                exc = " && ".join([f'!STRSTARTS(STR({var}), "{p}")' for p in excl])
                clauses.append(exc)
            return f"FILTER({' && '.join(clauses)})" if clauses else ""

        s_filter = _type_filter(
            "?sType", exclude_class_prefixes, include_class_prefixes
        )
        o_filter = _type_filter(
            "?oType", exclude_class_prefixes, include_class_prefixes
        )

        # --- Build the base subquery (reused in all 3 queries) ---
        # Compute random offset if requested
        offset_clause = ""
        if rand_offset:
            if predicate not in self._property_triple_count_cache:
                _search_uri = (
                    predicate.replace("/entity/", "/prop/direct/")
                    if self.is_wikidata
                    else predicate
                )
                count_q = (
                    f"SELECT (COUNT(*) AS ?count) WHERE {{ ?s <{_search_uri}> ?o . }}"
                )
                count_res = execute_sparql_query(
                    count_q, endpoint=self.endpoint, format_type="csv"
                )
                total_count = 0
                if count_res.get("success"):
                    try:
                        df_c = count_res.get("results")
                        if isinstance(df_c, pd.DataFrame) and not df_c.empty:
                            total_count = int(df_c.iloc[0]["count"])
                    except Exception:
                        total_count = 0
                self._property_triple_count_cache[predicate] = total_count
            total_count = self._property_triple_count_cache[predicate]
            offset = (
                random.randint(0, max(0, total_count - max_triples))
                if total_count > max_triples
                else 0
            )
            if offset > 0:
                offset_clause = f" OFFSET {offset}"

        if self.is_wikidata:
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
            q_triples, endpoint=self.endpoint, format_type="csv"
        )
        if not res_triples.get("success", False):
            if pbar:
                pbar.write(f"Property {display_name}: base triples query failed.")
            return set()
        df_triples = res_triples.get("results")
        if not isinstance(df_triples, pd.DataFrame) or df_triples.empty:
            if pbar:
                pbar.write(f"Property {display_name}: No triples returned.")
            return set()

        # Collect unique (s, o) pairs and literal datatypes
        triples = set()  # unique (s, o) pairs
        object_dtypes = {}  # o -> dType  (literal objects)
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

        # --- Query 2: Subject types via subquery (no VALUES) ---
        if self.is_wikidata:
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
            q_stypes, endpoint=self.endpoint, format_type="csv"
        )
        subject_types = defaultdict(set)
        if res_stypes.get("success", False):
            df_st = res_stypes.get("results")
            if isinstance(df_st, pd.DataFrame) and not df_st.empty:
                for row in df_st.itertuples(index=False):
                    s = str(row.s) if pd.notna(getattr(row, "s", None)) else None
                    sType = (
                        str(row.sType)
                        if pd.notna(getattr(row, "sType", None))
                        else None
                    )
                    if s and sType:
                        subject_types[s].add(sType)

        # --- Query 3: Object types via subquery – only if IRI objects exist ---
        object_types = defaultdict(set)
        if has_iri_objects:
            if self.is_wikidata:
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
                q_otypes, endpoint=self.endpoint, format_type="csv"
            )
            if res_otypes.get("success", False):
                df_ot = res_otypes.get("results")
                if isinstance(df_ot, pd.DataFrame) and not df_ot.empty:
                    for row in df_ot.itertuples(index=False):
                        o = str(row.o) if pd.notna(getattr(row, "o", None)) else None
                        oType = (
                            str(row.oType)
                            if pd.notna(getattr(row, "oType", None))
                            else None
                        )
                        if o and oType:
                            object_types[o].add(oType)

        if pbar:
            pbar.write(
                f"Property {display_name}: {len(subject_types)} typed subjects, "
                f"{len(object_types)} typed objects"
            )

        # --- Minimize types per entity (memoized by unique type set) ---
        _memo = {}
        min_subject_types = {}
        for s, types in subject_types.items():
            key = frozenset(types)
            if key not in _memo:
                _memo[key] = self._minimal_types(types)
            min_subject_types[s] = _memo[key]

        _memo_o = {}
        min_object_types = {}
        for o, types in object_types.items():
            key = frozenset(types)
            if key not in _memo_o:
                _memo_o[key] = self._minimal_types(types)
            min_object_types[o] = _memo_o[key]

        if pbar:
            pbar.write(
                f"Property {display_name}: {len(_memo)} unique subject type-sets, "
                f"{len(_memo_o)} unique object type-sets"
            )

        # --- Build pattern counts from minimal type assignments ---
        object_pattern_counts = defaultdict(int)
        attribute_pattern_counts = defaultdict(int)
        discovered_types = set()

        for s, o in triples:
            s_types = min_subject_types.get(s, set())
            o_types = min_object_types.get(o, None)

            if o_types is not None:
                # Object property — cross-join minimal types
                for st in s_types:
                    for ot in o_types:
                        object_pattern_counts[(st, ot)] += 1
                        discovered_types.add(st)
                        discovered_types.add(ot)
            else:
                # Attribute — use dType as object type
                dType = object_dtypes.get(
                    o, "http://www.w3.org/2000/01/rdf-schema#Resource"
                )
                for st in s_types:
                    attribute_pattern_counts[(st, dType)] += 1
                    discovered_types.add(st)

        # --- Store patterns (min_support filter) ---
        added_obj = 0
        for (st, ot), count in object_pattern_counts.items():
            if count >= min_support:
                self.patterns.add((st, predicate, ot))
                self.pattern_counts[(st, predicate, ot)] = count
                added_obj += 1

        added_attr = 0
        for (st, dt), count in attribute_pattern_counts.items():
            if count >= min_support:
                self.attribute_patterns.add((st, predicate, dt))
                self.attribute_counts[(st, predicate, dt)] = count
                added_attr += 1

        if pbar:
            pbar.write(
                f"Property {display_name}: {added_obj} object + {added_attr} attribute "
                f"minimal patterns (min_support={min_support})"
            )

        return discovered_types

    def plot_schema_graph(self, exclude_properties=None, max_edges=None):
        """
        Plots the schema graph derived from minimal type patterns.
        C — P —> D
        """
        import random

        if exclude_properties is None:
            exclude_properties = []

        # Filter patterns first
        patterns_to_plot = []
        for sub_type, pred, obj_type in self.patterns:
            p_name = pred.split("/")[-1].split("#")[-1]
            if p_name not in exclude_properties:
                patterns_to_plot.append((sub_type, pred, obj_type))

        # Randomly sample if max_edges is specified and exceeded
        if max_edges and len(patterns_to_plot) > max_edges:
            print(
                f"Sampling {max_edges} patterns from {len(patterns_to_plot)} available..."
            )
            patterns_to_plot = random.sample(patterns_to_plot, max_edges)

        PG = nx.MultiDiGraph()

        print(f"Plotting schema graph with {len(patterns_to_plot)} patterns...")

        edge_labels = {}
        node_labels = {}

        for sub_type, pred, obj_type in patterns_to_plot:
            # Helper to get short name
            def get_name(uri):
                return uri.split("/")[-1].split("#")[-1]

            p_name = get_name(pred)
            # exclude_properties check already done above

            u = get_name(sub_type)
            v = get_name(obj_type)

            PG.add_edge(u, v)

            # Node Labels
            if sub_type in self.type_labels:
                node_labels[u] = self.type_labels[sub_type]
            else:
                node_labels[u] = u

            if obj_type in self.type_labels:
                node_labels[v] = self.type_labels[obj_type]
            else:
                node_labels[v] = v

            # Use label if available
            if pred in self.property_labels:
                edge_labels[(u, v)] = self.property_labels[pred]
            else:
                edge_labels[(u, v)] = p_name

        if PG.number_of_nodes() == 0:
            print("Graph is empty. No patterns to plot.")
            return

        plt.figure(figsize=(15, 10))
        pos = nx.spring_layout(PG, k=2, iterations=100)

        # Draw nodes
        nx.draw_networkx_nodes(
            PG, pos, node_size=2000, node_color="lightblue", alpha=0.9
        )
        nx.draw_networkx_labels(
            PG, pos, labels=node_labels, font_size=8, font_weight="bold"
        )

        # Draw edges with straight lines
        ax = plt.gca()
        for (u, v), label in edge_labels.items():
            if u not in pos or v not in pos:
                continue

            start = pos[u]
            end = pos[v]

            # Draw straight arrow
            arrow = patches.FancyArrowPatch(
                start,
                end,
                arrowstyle="-|>",
                mutation_scale=15,
                color="gray",
                alpha=0.6,
                shrinkA=20,
                shrinkB=20,
            )
            ax.add_patch(arrow)

            # Label in the middle
            mid_point = (start + end) / 2

            # Add a white box background for better readability
            plt.text(
                mid_point[0],
                mid_point[1],
                label,
                horizontalalignment="center",
                verticalalignment="center",
                fontsize=7,
                color="darkblue",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8),
            )

        plt.title("ABSTAT 2.0 Schema Summary")
        plt.axis("off")
        plt.show()

    def print_data(self):
        """
        Returns a DataFrame of patterns, sorted by properties with the fewest combinations first.
        """
        data = []
        for (s, p, o), count in self.pattern_counts.items():
            # Use short names for display
            p_name = p.split("/")[-1].split("#")[-1]
            s_name = s.split("/")[-1].split("#")[-1]
            o_name = o.split("/")[-1].split("#")[-1]

            # Add label if available
            if s in self.type_labels:
                s_display = f"{s_name} ({self.type_labels[s]})"
            else:
                s_display = s_name

            if o in self.type_labels:
                o_display = f"{o_name} ({self.type_labels[o]})"
            else:
                o_display = o_name

            if p in self.property_labels:
                label = self.property_labels[p]
                p_display = f"{p_name} ({label})"
            else:
                p_display = p_name

            data.append(
                {
                    "Subject Type": s_display,
                    "Property": p_display,
                    "Object Type": o_display,
                    "Count": count,
                }
            )

        if not data:
            print("No patterns found.")
            return pd.DataFrame()

        df = pd.DataFrame(data)

        # Calculate number of combinations (rows) per property to sort by complexity
        # transform('count') gives us the count of the group for each row
        df["complexity"] = df.groupby("Property")["Property"].transform("count")

        # Sort by complexity (asc), then Pattern Count (desc)
        df_sorted = df.sort_values(
            by=["complexity", "Property", "Count"], ascending=[True, True, False]
        )

        # Drop helper column
        df_final = df_sorted.drop(columns=["complexity"])

        return df_final
