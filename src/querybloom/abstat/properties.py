"""SPARQL property discovery, frequency listing, and greedy BFS traversal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from querybloom.events import EventSink, emit_event
from querybloom.executor.sparql_executor import execute_sparql_query
from querybloom.abstat.cache import properties_cache_path


def get_distinct_properties(
    endpoint: str,
    cache_dir: Path,
    is_wikidata: bool = False,
    limit: int | None = None,
    frequency: bool = True,
    use_cache: bool = True,
    persist_cache: bool = True,
    event_sink: EventSink | None = None,
) -> list[tuple[str, int | None, str | None]]:
    """
    Fetches properties from the endpoint.
    If frequency=True, orders by occurrence count (slower).
    If frequency=False, just fetches distinct properties (faster).
    Returns list of (property_uri, count, label).
    """
    cache_path = properties_cache_path(cache_dir, endpoint, limit, frequency)

    if use_cache and cache_path.exists():
        print(f"Loading properties from cache: {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
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

    action = "top properties by frequency" if frequency else "distinct properties"
    limit_clause = f"LIMIT {limit}" if limit is not None else ""
    print(f"Fetching {action} (limit={limit})...")

    is_frequency_result = frequency and not is_wikidata

    if is_wikidata:
        print("Wikidata mode: Using wikibase:Property query (counts disabled) with labels.")
        query = f"""
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>

        SELECT ?p ?pLabel WHERE {{
            ?p a wikibase:Property .
            ?p wikibase:propertyType wikibase:WikibaseItem .
            ?p rdfs:label ?pLabel .
            FILTER(LANG(?pLabel) = "en" || LANG(?pLabel) = "")
        }}
        ORDER BY RAND()
        {limit_clause}
        """
        result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
        df = result.get("results") if result.get("success", False) else None
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
        result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
        df = result.get("results") if result.get("success", False) else None

        # If frequency query failed or returned no results, fall back to simple distinct query
        if not result.get("success", False) or not isinstance(df, pd.DataFrame) or df.empty:
            print(f"Frequency property query failed or returned 0 rows for {endpoint}. Falling back to simple distinct query...")
            query = f"""
            SELECT DISTINCT ?p WHERE {{
                ?s ?p ?o .
            }} 
            {limit_clause}
            """
            result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
            df = result.get("results") if result.get("success", False) else None
            is_frequency_result = False

        # If still failed or returned no results, fall back to ontology property definitions
        if not result.get("success", False) or not isinstance(df, pd.DataFrame) or df.empty:
            print(f"Triple-scan property query failed or returned 0 rows for {endpoint}. Falling back to ontology property definitions (rdf:Property / owl:Property)...")
            query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>

            SELECT DISTINCT ?p WHERE {{
                {{ ?p a rdf:Property . }}
                UNION
                {{ ?p a owl:ObjectProperty . }}
                UNION
                {{ ?p a owl:DatatypeProperty . }}
                UNION
                {{ ?p a owl:AnnotationProperty . }}
            }}
            {limit_clause}
            """
            result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
            df = result.get("results") if result.get("success", False) else None
            is_frequency_result = False
    else:
        query = f"""
        SELECT DISTINCT ?p WHERE {{
            ?s ?p ?o .
        }} 
        {limit_clause}
        """
        result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
        df = result.get("results") if result.get("success", False) else None

        # If distinct query failed or returned no results, fall back to ontology property definitions
        if not result.get("success", False) or not isinstance(df, pd.DataFrame) or df.empty:
            print(f"Distinct property query failed or returned 0 rows for {endpoint}. Falling back to ontology property definitions (rdf:Property / owl:Property)...")
            query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>

            SELECT DISTINCT ?p WHERE {{
                {{ ?p a rdf:Property . }}
                UNION
                {{ ?p a owl:ObjectProperty . }}
                UNION
                {{ ?p a owl:DatatypeProperty . }}
                UNION
                {{ ?p a owl:AnnotationProperty . }}
            }}
            {limit_clause}
            """
            result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
            df = result.get("results") if result.get("success", False) else None

    if not result.get("success", False):
        error_message = result.get("error") or "Unknown error"
        message = f"Failed to fetch properties from {endpoint}."
        print(f"{message} {error_message}")
        emit_event(
            event_sink,
            "error",
            "abstat.properties",
            message,
            {
                "endpoint": endpoint,
                "status": result.get("status"),
                "error": error_message,
                "query": result.get("executed_query") or query,
                "executed_endpoint_url": result.get("executed_endpoint_url"),
            },
        )
        raise RuntimeError(message)

    df = result.get("results")
    if not isinstance(df, pd.DataFrame):
        message = f"Failed to fetch properties from {endpoint}."
        print(f"{message} Unexpected results format {type(df).__name__}")
        emit_event(
            event_sink,
            "error",
            "abstat.properties",
            message,
            {
                "endpoint": endpoint,
                "error": f"Unexpected results format {type(df).__name__}",
                "result_type": type(df).__name__,
                "query": result.get("executed_query") or query,
                "executed_endpoint_url": result.get("executed_endpoint_url"),
            },
        )
        raise RuntimeError(message)

    properties: list[tuple[str, int | None, str | None]] = []

    def get_label(row: Any) -> str | None:
        label = row.get("pLabel")
        return str(label) if pd.notna(label) else None

    if is_wikidata:
        if "p" in df.columns:
            for _, row in df.iterrows():
                properties.append((row["p"], None, get_label(row)))
    elif is_frequency_result:
        if "p" in df.columns and "count" in df.columns:
            for _, row in df.iterrows():
                p = row["p"]
                count = row["count"]
                if p not in ["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"]:
                    properties.append((p, count, get_label(row)))
    else:
        if "p" in df.columns:
            found_uris: list[str] = []
            for _, row in df.iterrows():
                p = row["p"]
                if p not in ["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"]:
                    found_uris.append(p)

            labels_map: dict[str, str] = {}
            if found_uris:
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
                        label_query, endpoint=endpoint, format_type="csv"
                    )
                    if res_lbl.get("success", False):
                        df_lbl = res_lbl.get("results")
                        if isinstance(df_lbl, pd.DataFrame):
                            for _, lrow in df_lbl.iterrows():
                                if pd.notna(lrow.get("pLabel")):
                                    labels_map[lrow["p"]] = str(lrow["pLabel"])

            for p in found_uris:
                properties.append((p, None, labels_map.get(p)))

    print(f"Found {len(properties)} properties.")

    if not properties:
        row_count = len(df.index) if isinstance(df, pd.DataFrame) else 0
        columns = list(df.columns) if isinstance(df, pd.DataFrame) else []
        message = f"No properties were found for {endpoint}."
        emit_event(
            event_sink,
            "error",
            "abstat.properties",
            message,
            {
                "endpoint": endpoint,
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

    if persist_cache and properties:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(properties, f)
        print(f"Saved properties to cache: {cache_path}")

    return properties


def find_one_connected_property(
    endpoint: str,
    is_wikidata: bool,
    known_types: set[str],
    remaining_uris: set[str] | None = None,
    exclude_uris: set[str] | None = None,
) -> str | None:
    """
    Find a single unprocessed property connected to any of the known types.

    For each known type, asks the endpoint for properties used by instances
    of that type (domain or range side). Returns the first one that is in
    ``remaining_uris`` (if provided), otherwise returns the first discovered property.
    """
    if not known_types:
        return None

    type_pred = "wdt:P31" if is_wikidata else "a"
    prefix = (
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
        if is_wikidata
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
            query, endpoint=endpoint, format_type="csv"
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
            query, endpoint=endpoint, format_type="csv"
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
