import sys, os
sys.path.append(os.path.abspath("../src"))
from querybloom.executor.sparql_executor import execute_sparql_query as execute

endpoint = "sockg-local"
uri = "http://sockg.org/instances/project/2448" # Need an actual URI
query = f"""
SELECT ?p ?o WHERE {{
    <http://sockg.org/instances/project/2448> ?p ?o .
}} LIMIT 10
"""
print(execute(query, endpoint=endpoint))
