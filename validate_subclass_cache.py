"""
Quick validation: check that the cached subclass graph wasn't truncated
by the endpoint's result-row limit.

Usage:
    PYTHONPATH="$PWD" python querybloom/validate_subclass_cache.py --endpoint dbpedia-qlever
"""
import argparse
import json
from pathlib import Path
from collections import defaultdict

from querybloom.executor.sparql_executor import execute_sparql_query

CACHE_DIR = Path(__file__).parent / "cache"


def load_cache(endpoint: str):
    safe = endpoint.replace("/", "_").replace(":", "_").replace(".", "_")
    cache_path = CACHE_DIR / f"subclass_edges_{safe}.json"
    if not cache_path.exists():
        return None, cache_path
    with open(cache_path) as f:
        data = json.load(f)
    pairs = data.get("pairs", [])
    return pairs, cache_path


def count_endpoint_edges(endpoint: str) -> int:
    """Ask the endpoint for the exact count of distinct (subClass, superClass) pairs."""
    is_wikidata = "wikidata" in endpoint.lower()
    if is_wikidata:
        query = """
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        SELECT (COUNT(*) AS ?n) WHERE {
            SELECT DISTINCT ?sub ?sup WHERE {
                ?sub wdt:P279 ?sup .
                FILTER(isURI(?sub) && isURI(?sup))
            }
        }
        """
    else:
        query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl:  <http://www.w3.org/2002/07/owl#>
        SELECT (COUNT(*) AS ?n) WHERE {
            SELECT DISTINCT ?sub ?sup WHERE {
                ?sub (rdfs:subClassOf | owl:subClassOf) ?sup .
                FILTER(isURI(?sub) && isURI(?sup))
            }
        }
        """
    result = execute_sparql_query(query, endpoint=endpoint, format_type="csv")
    if not result.get("success", False):
        raise RuntimeError(f"Count query failed: {result.get('error')}")
    import pandas as pd
    df = result.get("results")
    if not isinstance(df, pd.DataFrame) or "n" not in df.columns:
        raise RuntimeError("Unexpected response format from count query")
    return int(df["n"].iloc[0])


def main():
    parser = argparse.ArgumentParser(description="Validate subclass graph cache completeness")
    parser.add_argument("--endpoint", default="dbpedia-qlever", help="Endpoint name")
    args = parser.parse_args()

    print(f"Endpoint : {args.endpoint}")

    # --- Load cache ---
    pairs, cache_path = load_cache(args.endpoint)
    if pairs is None:
        print(f"ERROR: No cache file found at {cache_path}")
        return
    cached_edges = len(pairs)
    unique_subs = len({p[0] for p in pairs})
    print(f"Cache    : {cache_path}")
    print(f"  Cached edges         : {cached_edges:,}")
    print(f"  Distinct subclasses  : {unique_subs:,}")

    # --- Count at endpoint ---
    print("\nQuerying endpoint for exact edge count (may take a few seconds)...")
    try:
        endpoint_count = count_endpoint_edges(args.endpoint)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return

    print(f"  Endpoint edge count  : {endpoint_count:,}")

    # --- Compare ---
    print()
    if cached_edges == endpoint_count:
        print("✓  Cache is COMPLETE — counts match exactly.")
    elif cached_edges < endpoint_count:
        missing = endpoint_count - cached_edges
        pct = missing / endpoint_count * 100
        print(f"✗  Cache is INCOMPLETE — missing {missing:,} edges ({pct:.1f}%).")
        print("   The endpoint likely hit its result-row limit during the original fetch.")
        print("   Delete the cache file and refetch, or increase the endpoint's row limit.")
        print(f"   Cache file: {cache_path}")
    else:
        extra = cached_edges - endpoint_count
        print(f"?  Cache has MORE edges than the endpoint reports ({extra:,} extra).")
        print("   This is unexpected — the cache may contain duplicates or stale data.")


if __name__ == "__main__":
    main()
