#!/usr/bin/env python3
"""
Find discrepancies between ontology-declared rdfs:domain/rdfs:range annotations
and patterns actually observed in instance data for the sud-okn endpoint.

For each undeclared type, also verify whether it is a subclass (direct or transitive)
of the declared type, to confirm the "child class" hypothesis.
"""

import sys
import os
import pandas as pd
from collections import defaultdict

from querybloom.executor.sparql_executor import execute_sparql_query
from querybloom.abstat_2 import get_property_domain_range

ENDPOINT = "sud-okn"


def get_subclass_graph(endpoint):
    """Return dict: child_uri -> set of all ancestor URIs (transitive)."""
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?child ?parent WHERE {
        ?child rdfs:subClassOf+ ?parent .
    }
    """
    result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
    if not result.get("success"):
        print(f"  Warning: could not fetch subclass graph: {result.get('error')}")
        return {}
    df = result["results"]
    ancestors = defaultdict(set)
    for _, row in df.iterrows():
        child  = row.get("child")
        parent = row.get("parent")
        if isinstance(child, str) and isinstance(parent, str):
            ancestors[child].add(parent)
    return ancestors


def get_annotated_domain_range(endpoint):
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
        d, r = row.get("domain"), row.get("range")
        if isinstance(d, str) and pd.notna(d):
            props[p]["domains"].add(d)
        if isinstance(r, str) and pd.notna(r):
            props[p]["ranges"].add(r)
    return props


def shorten(uri):
    return uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def main():
    # Step 1: ontology annotations
    print(f"[1/3] Fetching ontology rdfs:domain/rdfs:range from '{ENDPOINT}'...")
    ont = get_annotated_domain_range(ENDPOINT)
    sudokn_props = {
        uri: dr for uri, dr in ont.items()
        if "SUDOKN" in uri or "industrialontologies" in uri
    }
    print(f"      Found {len(ont)} total annotated properties; "
          f"focusing on {len(sudokn_props)} SUDOKN/IOF properties.\n")

    # Step 2: subclass hierarchy (transitive)
    print(f"[2/3] Fetching transitive rdfs:subClassOf graph...")
    ancestors = get_subclass_graph(ENDPOINT)
    print(f"      Loaded ancestry for {len(ancestors)} classes.\n")

    def is_subclass_of(child, declared_set):
        """True if child is in declared_set OR has any ancestor in declared_set."""
        if child in declared_set:
            return True
        return bool(ancestors.get(child, set()) & declared_set)

    # Step 3: instance-based scan for each focused property
    print(f"[3/3] Querying instance data for each property (this may take a moment)...\n")

    discrepancies = []

    for prop_uri, ont_dr in sudokn_props.items():
        label = shorten(prop_uri)
        ont_domains = ont_dr["domains"]
        ont_ranges  = ont_dr["ranges"]

        pairs = get_property_domain_range(prop_uri, endpoint=ENDPOINT,
                                          max_triples=5000, min_support=1)
        if not pairs:
            continue

        # Collect all empirical domain/range types
        emp_domains = {p["subject_type"] for p in pairs if p.get("subject_type")}
        emp_ranges  = {p["object_type"]  for p in pairs
                       if p.get("object_type") and not p.get("object_type", "").startswith("urn:")}

        # Missing from ontology declarations
        undeclared_domains = emp_domains - ont_domains
        undeclared_ranges  = emp_ranges  - ont_ranges

        if undeclared_domains or undeclared_ranges:
            discrepancies.append({
                "uri":               prop_uri,
                "label":             label,
                "ont_domains":       sorted(ont_domains),
                "ont_ranges":        sorted(ont_ranges),
                "undeclared_domains": sorted(undeclared_domains),
                "undeclared_ranges":  sorted(undeclared_ranges),
                "pairs":             pairs,
            })

    # ── Report ──────────────────────────────────────────────────────────────
    print("=" * 70)
    print(f"DISCREPANCY REPORT  (instance data vs ontology annotations)")
    print(f"Properties with at least one undeclared domain or range type: "
          f"{len(discrepancies)} / {len(sudokn_props)}")
    print("=" * 70)

    TRUE_CHILD  = "YES (subclass)"
    NOT_CHILD   = "NO  (unrelated)"
    BLANK_NODE  = "SKIP (blank node)"

    for d in discrepancies:
        print(f"\n  Property : {d['label']}")
        print(f"  URI      : {d['uri']}")

        if d["ont_domains"]:
            print(f"  Ontology domains : {[shorten(x) for x in d['ont_domains']]}")
        else:
            print(f"  Ontology domains : (none declared)")
        if d["ont_ranges"]:
            print(f"  Ontology ranges  : {[shorten(x) for x in d['ont_ranges']]}")
        else:
            print(f"  Ontology ranges  : (none declared)")

        if d["undeclared_domains"]:
            print(f"  Undeclared domains (seen in data):")
            for ud in d["undeclared_domains"][:8]:
                if ud.startswith("_:"):
                    verdict = BLANK_NODE
                elif is_subclass_of(ud, set(d["ont_domains"])):
                    verdict = TRUE_CHILD
                else:
                    verdict = NOT_CHILD
                print(f"       - {shorten(ud):45s}  is-subclass-of-declared? {verdict}")
            if len(d["undeclared_domains"]) > 8:
                rest = d["undeclared_domains"][8:]
                all_children = all(
                    is_subclass_of(x, set(d["ont_domains"])) for x in rest if not x.startswith("_:")
                )
                print(f"       ... {len(rest)} more  (all subclasses: {all_children})")

        if d["undeclared_ranges"]:
            print(f"  Undeclared ranges (seen in data):")
            for ur in d["undeclared_ranges"][:8]:
                if ur.startswith("_:"):
                    verdict = BLANK_NODE
                elif is_subclass_of(ur, set(d["ont_ranges"])):
                    verdict = TRUE_CHILD
                else:
                    verdict = NOT_CHILD
                print(f"       - {shorten(ur):45s}  is-subclass-of-declared? {verdict}")
            if len(d["undeclared_ranges"]) > 8:
                rest = d["undeclared_ranges"][8:]
                all_children = all(
                    is_subclass_of(x, set(d["ont_ranges"])) for x in rest if not x.startswith("_:")
                )
                print(f"       ... {len(rest)} more  (all subclasses: {all_children})")


if __name__ == "__main__":
    main()
