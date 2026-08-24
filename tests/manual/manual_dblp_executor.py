import sys
import os
from querybloom.executor.sparql_executor import execute_sparql_query

base_subquery = "SELECT ?s ?o WHERE { ?s <https://dblp.org/rdf/schema#authoredBy> ?o . } LIMIT 30000"

q_otypes = f"""
SELECT DISTINCT ?o ?oType WHERE {{
    {{ SELECT DISTINCT ?o WHERE {{
        {{ {base_subquery} }}
        FILTER(isIRI(?o))
    }} }}
    ?o a ?oType .
}}
"""
res = execute_sparql_query(q_otypes, endpoint="dblp", format_type="csv")
print("Success:", res.get("success"))
if res.get("success"):
    print("Row count:", len(res.get("results")))
else:
    print("Error:", res.get("error"))
