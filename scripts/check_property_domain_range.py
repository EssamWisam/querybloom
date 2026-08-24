#!/usr/bin/env python3
"""
Check how many properties in the sud-okn KG have unique (single) vs. multiple
domain-range pairs — using declared rdfs:domain / rdfs:range annotations only.

Usage: python check_property_domain_range.py
"""

import sys
import os
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from querybloom.executor.sparql_executor import execute_sparql_query

ENDPOINT = "sud-okn"


def get_annotated_domain_range(endpoint):
    """
    Fetch all (property, rdfs:domain, rdfs:range) triples declared in the ontology.
    Returns a dict: property_uri -> {"domains": set, "ranges": set}
    """
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?p ?domain ?range WHERE {
        { ?p rdfs:domain ?domain . }
        UNION
        { ?p rdfs:range  ?range  . }
    }
    """
    result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
    if not result.get("success"):
        raise RuntimeError(f"Query failed: {result.get('error')}")

    df = result["results"]
    props = {}
    for _, row in df.iterrows():
        p = row.get("p")
        if not p or not isinstance(p, str):
            continue
        if p not in props:
            props[p] = {"domains": set(), "ranges": set()}
        d = row.get("domain")
        r = row.get("range")
        if isinstance(d, str) and pd.notna(d):
            props[p]["domains"].add(d)
        if isinstance(r, str) and pd.notna(r):
            props[p]["ranges"].add(r)

    return props


def main():
    print(f"Fetching declared rdfs:domain/rdfs:range from '{ENDPOINT}'...")
    props = get_annotated_domain_range(ENDPOINT)
    print(
        f"Found {len(props)} properties with at least one domain or range annotation.\n"
    )

    multi_domain = []
    multi_range = []
    multi_both = []
    single = []
    no_annotation = []

    for prop_uri, dr in props.items():
        unique_domains = dr["domains"]
        unique_ranges = dr["ranges"]

        if not unique_domains and not unique_ranges:
            no_annotation.append(prop_uri)
            continue

        has_multi_domain = len(unique_domains) > 1
        has_multi_range = len(unique_ranges) > 1

        label = prop_uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        entry = {
            "uri": prop_uri,
            "label": label,
            "domains": sorted(unique_domains),
            "ranges": sorted(unique_ranges),
        }

        if has_multi_domain and has_multi_range:
            multi_both.append(entry)
        elif has_multi_domain:
            multi_domain.append(entry)
        elif has_multi_range:
            multi_range.append(entry)
        else:
            single.append(entry)

    total = len(single) + len(multi_domain) + len(multi_range) + len(multi_both)

    if total == 0:
        print("No data returned from endpoint. Check connectivity.")
        return

    def pct(n):
        return f"{n}/{total} ({100*n/total:.1f}%)"

    print("=" * 60)
    print(f"RESULTS for endpoint: {ENDPOINT}")
    print("=" * 60)
    print(f"  Single domain + single range : {pct(len(single))}")
    print(f"  Multi-domain only            : {pct(len(multi_domain))}")
    print(f"  Multi-range only             : {pct(len(multi_range))}")
    print(f"  Multi-domain AND multi-range : {pct(len(multi_both))}")
    print()

    multi_any = multi_domain + multi_range + multi_both
    print(f"  Properties with ANY multi domain/range: {pct(len(multi_any))}")
    print("=" * 60)

    if multi_domain:
        print("\n--- Properties with multiple DOMAINS (single range) ---")
        for e in multi_domain:
            print(f"  {e['label']}")
            print(f"    URI:     {e['uri']}")
            print(f"    domains: {e['domains']}")
            print(f"    range:   {e['ranges']}")

    if multi_range:
        print("\n--- Properties with multiple RANGES (single domain) ---")
        for e in multi_range:
            print(f"  {e['label']}")
            print(f"    URI:    {e['uri']}")
            print(f"    domain: {e['domains']}")
            print(f"    ranges: {e['ranges']}")

    if multi_both:
        print("\n--- Properties with multiple DOMAINS and multiple RANGES ---")
        for e in multi_both:
            print(f"  {e['label']}")
            print(f"    URI:     {e['uri']}")
            print(f"    domains: {e['domains']}")
            print(f"    ranges:  {e['ranges']}")


if __name__ == "__main__":
    main()
