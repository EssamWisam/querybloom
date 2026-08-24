"""Standalone property domain-range inspection and attribute detection."""

from __future__ import annotations

from typing import Any, Sequence
import pandas as pd

from querybloom.executor.sparql_executor import execute_sparql_query
from querybloom.abstat.queries import build_filter


def get_property_domain_range(
    property_uri: str,
    endpoint: str = "sockg",
    max_triples: int = 20000,
    min_support: int = 1,
    exclude_class_prefixes: Sequence[str] | None = None,
    include_class_prefixes: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Standalone function to find all domain-range (subject type, object type) combinations
    for a given property URI.

    Args:
        property_uri: The full URI of the property to analyze
        endpoint: The SPARQL endpoint to query
        max_triples: Maximum number of triples to sample (to avoid timeouts)
        min_support: Minimum support count for pattern inclusion
        exclude_class_prefixes: Class URI prefixes to ignore
        include_class_prefixes: Class URI prefixes to whitelist

    Returns:
        List of dicts with keys: 'subject_type', 'object_type', 'count',
        'subject_type_label', 'object_type_label', 'is_attribute'.
        Returns empty list on error.
    """
    is_wikidata = "wikidata" in str(endpoint).lower()

    subject_filter = build_filter(
        "?sType", exclude_class_prefixes, include_class_prefixes
    )
    if is_wikidata:
        object_filter = build_filter(
            "?oType", exclude_class_prefixes, include_class_prefixes, optional_obj=True
        )
    else:
        object_filter = build_filter(
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

    type_labels_map: dict[str, str] = {}
    domain_range_pairs: list[dict[str, Any]] = []

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
