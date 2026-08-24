import sys, os
import pandas as pd
from collections import defaultdict

# Add necessary paths
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))
from querybloom.executor.sparql_executor import execute_sparql_query


def main():
    # Notice we do NOT have an ORDER BY here, which makes LIMIT non-deterministic
    base_subquery = "SELECT ?s ?o WHERE { ?s <https://dblp.org/rdf/schema#authoredBy> ?o . } LIMIT 10"

    q_triples = (
        f"SELECT ?s ?o (datatype(?o) AS ?dType) WHERE {{ {{ {base_subquery} }} }}"
    )
    res_triples = execute_sparql_query(q_triples, endpoint="dblp", format_type="csv")
    df = res_triples.get("results")

    o_list = set(df["o"].tolist())
    print("Triples objects count:", len(o_list))

    q_otypes = f"""
    SELECT DISTINCT ?o ?oType WHERE {{
        {{ SELECT DISTINCT ?o WHERE {{
            {{ {base_subquery} }}
            FILTER(isIRI(?o))
        }} }}
        ?o a ?oType .
    }}
    """
    res_otypes = execute_sparql_query(q_otypes, endpoint="dblp", format_type="csv")
    df2 = res_otypes.get("results")

    if df2 is not None and not df2.empty:
        o2_list = set(df2["o"].tolist())
        print("Otypes objects count:", len(o2_list))

        # Check intersection
        intersect = o_list.intersection(o2_list)
        print("Intersection count:", len(intersect))
        print("Are they identical?", intersect == o_list)
    else:
        print("empty!")


if __name__ == "__main__":
    main()
