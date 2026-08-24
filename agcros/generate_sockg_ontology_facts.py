"""
Generate two YAML files from the sockg-local SPARQL endpoint:
  1. sockg_subclasses.yaml   — all (subclass, superclass) pairs via rdfs:subClassOf / owl:subClassOf
  2. sockg_property_domain_ranges.yaml — for every property, all Cartesian products of its
     ontology-declared (not inferred) rdfs:domain × rdfs:range values
"""

import os
import sys
from pathlib import Path
from itertools import product
from collections import defaultdict

import yaml
import pandas as pd

from querybloom.executor.sparql_executor import execute_sparql_query  # noqa: E402

ENDPOINT = "sockg-local"
OUT_DIR = _HERE


# ── 1. subclass pairs ─────────────────────────────────────────────────────────

def fetch_subclasses() -> list[dict]:
    """Return all direct rdfs:subClassOf / owl:subClassOf edges."""
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl:  <http://www.w3.org/2002/07/owl#>
    SELECT DISTINCT ?subClass ?superClass WHERE {
        ?subClass (rdfs:subClassOf | owl:subClassOf) ?superClass .
        FILTER(isURI(?subClass) && isURI(?superClass))
    }
    """
    print("Fetching subclass pairs …")
    result = execute_sparql_query(query, endpoint=ENDPOINT, format_type="csv")

    if not result.get("success", False):
        print(f"  ERROR: {result.get('error')}")
        return []

    df: pd.DataFrame = result.get("results")
    if not isinstance(df, pd.DataFrame) or df.empty:
        print("  No subclass pairs found.")
        return []

    pairs = []
    for _, row in df.iterrows():
        sub = row.get("subClass")
        sup = row.get("superClass")
        if pd.notna(sub) and pd.notna(sup):
            pairs.append({"subclass": str(sub), "superclass": str(sup)})

    print(f"  Found {len(pairs)} subclass pairs.")
    return pairs


# ── 2. property domain × range combinations ───────────────────────────────────

def fetch_property_domain_ranges() -> list[dict]:
    """
    For each property return all Cartesian products of its
    ontology-declared rdfs:domain and rdfs:range values.

    Properties that have only a domain (or only a range) are also included,
    with the missing side set to null.
    """
    domain_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?property ?domain WHERE {
        ?property rdfs:domain ?domain .
        FILTER(isURI(?property) && isURI(?domain))
    }
    """
    range_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?property ?range WHERE {
        ?property rdfs:range ?range .
        FILTER(isURI(?property) && isURI(?range))
    }
    """

    print("Fetching ontology-declared domains …")
    d_result = execute_sparql_query(domain_query, endpoint=ENDPOINT, format_type="csv")
    print("Fetching ontology-declared ranges …")
    r_result = execute_sparql_query(range_query, endpoint=ENDPOINT, format_type="csv")

    # build property → set of domains / ranges
    prop_domains: dict[str, list[str]] = defaultdict(list)
    prop_ranges:  dict[str, list[str]] = defaultdict(list)

    if d_result.get("success", False):
        df = d_result.get("results")
        if isinstance(df, pd.DataFrame) and not df.empty:
            for _, row in df.iterrows():
                prop = row.get("property")
                dom  = row.get("domain")
                if pd.notna(prop) and pd.notna(dom):
                    prop_domains[str(prop)].append(str(dom))
    else:
        print(f"  Domain query ERROR: {d_result.get('error')}")

    if r_result.get("success", False):
        df = r_result.get("results")
        if isinstance(df, pd.DataFrame) and not df.empty:
            for _, row in df.iterrows():
                prop = row.get("property")
                rng  = row.get("range")
                if pd.notna(prop) and pd.notna(rng):
                    prop_ranges[str(prop)].append(str(rng))
    else:
        print(f"  Range query ERROR: {r_result.get('error')}")

    all_props = set(prop_domains.keys()) | set(prop_ranges.keys())
    print(f"  Found {len(all_props)} properties with at least one domain/range declaration.")

    rows = []
    for prop in sorted(all_props):
        domains = prop_domains.get(prop) or [None]
        ranges  = prop_ranges.get(prop)  or [None]
        for dom, rng in product(domains, ranges):
            entry: dict = {"property": prop}
            if dom is not None:
                entry["domain"] = dom
            if rng is not None:
                entry["range"] = rng
            rows.append(entry)

    print(f"  Total (property, domain, range) combinations: {len(rows)}.")
    return rows


# ── prefix helpers ────────────────────────────────────────────────────────────

# Well-known namespace → preferred short prefix
_KNOWN_NS: list[tuple[str, str]] = [
    ("https://idir.uta.edu/sockg-ontology#",              "sockg"),
    ("http://www.w3.org/2001/XMLSchema#",                 "xsd"),
    ("http://www.w3.org/2000/01/rdf-schema#",             "rdfs"),
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#",       "rdf"),
    ("http://www.w3.org/2002/07/owl#",                    "owl"),
    ("http://www.opengis.net/ont/geosparql#",             "geosparql"),
    ("http://purl.org/spatialai/spatial/spatial-full#",   "spatial"),
    ("http://purl.org/dc/terms/",                         "dcterms"),
    ("http://qudt.org/schema/qudt/",                      "qudt"),
    ("http://stko-kwg.geog.ucsb.edu/lod/ontology/",      "kwg"),
    ("http://schema.org/",                                "schema"),
    ("http://xmlns.com/foaf/0.1/",                        "foaf"),
]


def _split_uri(uri: str) -> tuple[str, str]:
    """Return (namespace, local) splitting at the last # or /."""
    for sep in ("#", "/"):
        idx = uri.rfind(sep)
        if idx != -1:
            return uri[: idx + 1], uri[idx + 1 :]
    return ("", uri)


def build_prefix_map(uris: set[str]) -> dict[str, str]:
    """
    Return {prefix: namespace} for every namespace that appears in *uris*.
    Known namespaces get their canonical prefix; unknown ones get an auto-generated one.
    """
    namespaces: set[str] = set()
    for uri in uris:
        ns, _ = _split_uri(uri)
        if ns:
            namespaces.add(ns)

    prefix_map: dict[str, str] = {}   # prefix -> namespace
    used_prefixes: set[str] = set()

    # 1. assign well-known prefixes first
    for ns, pfx in _KNOWN_NS:
        if ns in namespaces:
            prefix_map[pfx] = ns
            used_prefixes.add(pfx)

    # 2. auto-generate for the rest
    counter: dict[str, int] = {}
    for ns in sorted(namespaces):
        if any(v == ns for v in prefix_map.values()):
            continue                   # already covered
        # derive candidate from the last meaningful path segment
        clean = ns.rstrip("#/")
        candidate = clean.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        candidate = candidate[:12] or "ns"
        base = candidate
        i = counter.get(base, 0)
        while candidate in used_prefixes:
            i += 1
            candidate = f"{base}{i}"
        counter[base] = i
        prefix_map[candidate] = ns
        used_prefixes.add(candidate)

    return prefix_map  # {prefix: namespace}


def curie(uri: str, ns2pfx: dict[str, str]) -> str:
    """Shorten *uri* to a CURIE using ns2pfx ({namespace: prefix})."""
    ns, local = _split_uri(uri)
    if ns and ns in ns2pfx:
        return f"{ns2pfx[ns]}:{local}"
    return uri


# ── domain-indexed writer ─────────────────────────────────────────────────────

def local_name(uri: str) -> str:
    """Return the local fragment of a URI (after last # or /)."""
    _, local = _split_uri(uri)
    return local or uri


def build_domain_indexed(rows: list[dict]) -> dict:
    """
    Build a nested dict:
      classes:
        <DomainLocalName>:
          <propertyLocalName>: <rangeLocalName>   # single value
          <propertyLocalName>:                    # or list when >1 range
            - <rangeLocalName>
    """
    from collections import defaultdict
    by_domain: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for row in rows:
        dom  = row.get("domain")
        prop = row["property"]
        rng  = row.get("range")
        dom_key  = local_name(dom)  if dom  else "(no domain)"
        prop_key = local_name(prop)
        rng_val  = local_name(rng)  if rng  else None
        if rng_val:
            by_domain[dom_key][prop_key].add(rng_val)
        else:
            by_domain[dom_key].setdefault(prop_key, set())

    classes: dict = {}
    for dom_key in sorted(by_domain):
        props_out: dict = {}
        for prop_key in sorted(by_domain[dom_key]):
            ranges = sorted(by_domain[dom_key][prop_key])
            if len(ranges) == 1:
                props_out[prop_key] = ranges[0]
            elif len(ranges) > 1:
                props_out[prop_key] = ranges
            else:
                props_out[prop_key] = None
        classes[dom_key] = props_out

    return classes


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    # 1 — subclasses
    subclasses = fetch_subclasses()
    out1 = OUT_DIR / "sockg_subclasses.yaml"
    with open(out1, "w") as f:
        yaml.dump(subclasses, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"Written: {out1}  ({len(subclasses)} entries)\n")

    # 2 — property domain-range combinations (friendly format)
    prop_dr = fetch_property_domain_ranges()
    classes = build_domain_indexed(prop_dr)

    out2 = OUT_DIR / "sockg_property_domain_ranges.yaml"
    with open(out2, "w") as f:
        yaml.dump({"classes": classes}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    total_props = sum(len(v) for v in classes.values())
    print(f"Written: {out2}  ({len(classes)} domain classes, {total_props} property entries)\n")


if __name__ == "__main__":
    main()
