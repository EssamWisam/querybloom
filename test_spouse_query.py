"""
Test file: Minimization-first, then label fetching only for surviving pattern types.
Hypothesis: far fewer types need labels after minimization → much faster label fetching.
"""

import sys
import os
import time
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..', 'src')))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from querybloom.executor.sparql_executor import execute_sparql_query
from querybloom.abstat_2 import ABSTAT_v2

property_uri = "http://dbpedia.org/ontology/spouse"
endpoint = "dbpedia-qlever"
max_triples = 3000
min_support = 10

print("=" * 80)
print("APPROACH: Minimize first, then fetch labels only for surviving types")
print("=" * 80)
print()

# ── Step 1: Main domain-range query (no label fetching) ───────────────────────
print("Step 1: Fetching domain-range pairs (no labels)...")
query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?sType ?finalOType ?dType (COUNT(*) as ?count) WHERE {{
    {{
        SELECT ?s ?o WHERE {{
            ?s <{property_uri}> ?o .
        }} LIMIT {max_triples}
    }}
    ?s a ?sType .
    OPTIONAL {{ FILTER(isIRI(?o)) . ?o a ?rawOType }}
    BIND(datatype(?o) AS ?dType)
    BIND(IF(BOUND(?rawOType), ?rawOType, <urn:untyped>) AS ?finalOType)
}}
GROUP BY ?sType ?finalOType ?dType
HAVING (COUNT(*) >= {min_support})
"""

t0 = time.time()
result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
main_query_time = time.time() - t0

print(f"  Done in {main_query_time:.2f}s")

if not result.get("success", False):
    print(f"ERROR: {result.get('error')}")
    sys.exit(1)

df = result.get("results")
o_col = "finalOType" if "finalOType" in df.columns else "oType"

all_raw_types = set(df['sType'].dropna().unique())
for val in df[o_col].dropna().unique():
    if str(val) != "urn:untyped" and not str(val).startswith("http://www.w3.org/2001/XMLSchema#"):
        all_raw_types.add(val)

print(f"  Raw type combinations: {len(df)}")
print(f"  Unique types before minimization: {len(all_raw_types)}")
print()

# ── Step 2: Minimization (optimized) ─────────────────────────────────────────
print("Step 2: Running minimization (optimized)...")

object_patterns = []
attribute_patterns = []
for _, row in df.iterrows():
    sType = row.get("sType") if pd.notna(row.get("sType")) else None
    if not sType:
        continue
    oType = row.get(o_col) if pd.notna(row.get(o_col)) else None
    dType = row.get("dType") if pd.notna(row.get("dType")) else None
    count = int(row.get("count")) if pd.notna(row.get("count")) else 0

    is_untyped = oType and ("urn:untyped" in str(oType))
    if oType and not is_untyped:
        final_oType = oType
        is_attribute = False
    elif dType:
        final_oType = dType
        is_attribute = True
    else:
        final_oType = "http://www.w3.org/2000/01/rdf-schema#Resource"
        is_attribute = False

    pat = {"sType": sType, "oType": final_oType, "count": count}
    if is_attribute:
        attribute_patterns.append(pat)
    else:
        object_patterns.append(pat)

print(f"  Object patterns: {len(object_patterns)},  Attribute patterns: {len(attribute_patterns)}")

def compute_minimal_patterns_fast(patterns, endpoint):
    """
    Original O(n²) logic with lazy SPARQL-based is_subtype() and per-type caching.
    Once all ~468 unique types are cached, the loop is pure dict lookups.
    """
    if not patterns:
        return []

    candidates = [(p["sType"], p["oType"], p["count"]) for p in patterns]
    n = len(candidates)
    supertype_cache = {}

    def is_subtype(t1, t2):
        if t1 == t2:
            return True
        if t1 not in supertype_cache:
            query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?sup WHERE {{
    <{t1}> rdfs:subClassOf* ?sup .
}}
"""
            res = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
            supertypes = {t1}
            if res.get("success"):
                res_df = res.get("results")
                if isinstance(res_df, pd.DataFrame) and "sup" in res_df.columns:
                    supertypes.update(res_df["sup"].dropna().tolist())
            supertype_cache[t1] = supertypes
        return t2 in supertype_cache[t1]

    to_remove = set()
    for i in range(n):
        for j in range(n):
            if i == j or j in to_remove:
                continue
            s1, o1, count_i = candidates[i]
            s2, o2, count_j = candidates[j]
            if is_subtype(s1, s2) and is_subtype(o1, o2):
                is_equivalent = is_subtype(s2, s1) and is_subtype(o2, o1)
                if not is_equivalent and count_j <= count_i:
                    to_remove.add(j)

    return [{"sType": candidates[i][0], "oType": candidates[i][1], "count": candidates[i][2]}
            for i in range(n) if i not in to_remove]

t0 = time.time()
minimal_object = compute_minimal_patterns_fast(object_patterns, endpoint)
minimal_attribute = compute_minimal_patterns_fast(attribute_patterns, endpoint)
minimization_time = time.time() - t0

# Collect only types that survived minimization
surviving_types = set()
for p in minimal_object + minimal_attribute:
    surviving_types.add(p["sType"])
    surviving_types.add(p["oType"])
# Drop xsd datatypes — no human label needed
surviving_types = {t for t in surviving_types
                   if not str(t).startswith("http://www.w3.org/2001/XMLSchema#")}

print(f"  Done in {minimization_time:.2f}s")
print(f"  Patterns: {len(minimal_object)} object  +  {len(minimal_attribute)} attribute")
print(f"  Unique types after minimization: {len(surviving_types)}  (was {len(all_raw_types)})")
reduction_pct = 100 * (1 - len(surviving_types) / max(len(all_raw_types), 1))
print(f"  Reduction: {len(all_raw_types) - len(surviving_types)} types dropped  ({reduction_pct:.1f}%)")
print()

# ── Step 3: Label fetching only for surviving types ───────────────────────────
print("Step 3: Fetching labels only for surviving types...")

type_labels_map = {}
types_list = list(surviving_types)
chunk_size = 250
total_label_time = 0
num_chunks = (len(types_list) + chunk_size - 1) // chunk_size

print(f"  {len(surviving_types)} types → {num_chunks} chunk(s) of {chunk_size}")
print()

for i in range(0, len(types_list), chunk_size):
    chunk = types_list[i:i + chunk_size]
    chunk_num = i // chunk_size + 1
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

    t0 = time.time()
    lbl_res = execute_sparql_query(lbl_query, endpoint=endpoint, format_type="csv")
    chunk_time = time.time() - t0
    total_label_time += chunk_time

    if lbl_res.get("success"):
        res_df = lbl_res.get("results")
        if isinstance(res_df, pd.DataFrame):
            for _, r in res_df.iterrows():
                if pd.notna(r.get("label")):
                    type_labels_map[r["s"]] = str(r["label"])
            print(f"  Chunk {chunk_num}/{num_chunks}: {chunk_time:.2f}s — {len(res_df)} labels")
        else:
            print(f"  Chunk {chunk_num}/{num_chunks}: {chunk_time:.2f}s — no DataFrame")
    else:
        print(f"  Chunk {chunk_num}/{num_chunks}: {chunk_time:.2f}s — query failed")

print()
print(f"  Labels fetched: {len(type_labels_map)} / {len(surviving_types)}")
print()

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 80)
print("TIME BREAKDOWN")
print("=" * 80)
print(f"  Main query:       {main_query_time:.2f}s")
print(f"  Minimization:     {minimization_time:.2f}s")
print(f"  Label fetching:   {total_label_time:.2f}s  (was 111.99s with old approach)")
print(f"  TOTAL:            {main_query_time + minimization_time + total_label_time:.2f}s")
print()
print("=" * 80)
print("LABEL COVERAGE (surviving patterns)")
print("=" * 80)
for uri in list(surviving_types)[:20]:
    label = type_labels_map.get(uri, "(no label found)")
    short = uri.split('/')[-1].split('#')[-1]
    print(f"  {short:40s}  →  {label}")
