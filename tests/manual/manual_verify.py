import sys, os

from querybloom.executor.sparql_executor import execute_sparql_query

q1 = "SELECT ?o WHERE { ?s <https://dblp.org/rdf/schema#authoredBy> ?o . } LIMIT 5"
res1 = execute_sparql_query(q1, endpoint="dblp", format_type="json")

if res1.get("success"):
    objects = [b["o"]["value"] for b in res1["results"]]
    print("Found author IRIs:", objects)
    for obj in objects[:2]:
        q2 = f"SELECT ?type WHERE {{ <{obj}> a ?type . }}"
        res2 = execute_sparql_query(q2, endpoint="dblp", format_type="json")
        if res2.get("success"):
            types = [b["type"]["value"] for b in res2["results"]]
            print(f"Types for {obj}:", types if types else "NO TYPES FOUND!")

    # Check all properties of the object
    q3 = f"SELECT DISTINCT ?p WHERE {{ <{objects[0]}> ?p ?o . }}"
    res3 = execute_sparql_query(q3, endpoint="dblp", format_type="json")
    if res3.get("success"):
        print(f"\nAll properties for {objects[0]}:")
        for b in res3["results"]:
            print("-", b["p"]["value"])
