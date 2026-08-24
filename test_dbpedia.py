import sys, os

from querybloom.executor.sparql_executor import execute_sparql_query

base_subquery = (
    "SELECT ?s ?o WHERE { ?s <http://dbpedia.org/ontology/spouse> ?o . } LIMIT 10"
)

q_triples = f"SELECT ?s ?o (datatype(?o) AS ?dType) WHERE {{ {{ {base_subquery} }} }}"
res_triples = execute_sparql_query(
    q_triples, endpoint="dbpedia-qlever", format_type="csv"
)
df = res_triples.get("results")
if df is not None and not df.empty:
    o_list = set(df["o"].tolist())
    print("DBpedia Triples objects count:", len(o_list))

    q_otypes = f"""SELECT DISTINCT ?o ?oType WHERE {{ {{ SELECT DISTINCT ?o WHERE {{ {{ {base_subquery} }} FILTER(isIRI(?o)) }} }} ?o a ?oType . }}"""
    res_otypes = execute_sparql_query(
        q_otypes, endpoint="dbpedia-qlever", format_type="csv"
    )
    df2 = res_otypes.get("results")

    if df2 is not None and not df2.empty:
        o2_list = set(df2["o"].tolist())
        print("DBpedia Otypes objects count:", len(o2_list))

        intersect = o_list.intersection(o2_list)
        print("DBpedia Intersection count:", len(intersect))
        print("Are they identical?", intersect == o_list)
    else:
        print("DBpedia Otypes empty!")
else:
    print("DBpedia Triples empty!")
