import sys, os
from querybloom.executor.sparql_executor import execute_sparql_query

# 1. Let's get a few objects of 'authoredBy'
q1 = """
SELECT ?o WHERE { 
    ?s <https://dblp.org/rdf/schema#authoredBy> ?o . 
} LIMIT 5
"""
res1 = execute_sparql_query(q1, endpoint='dblp', format_type='json')

if res1.get('success'):
    objects = [b['o']['value'] for b in res1['results']]
    print("Found author IRIs:", objects)
    
    # 2. Now let's ask for the type of the first one specifically
    for obj in objects[:2]:
        q2 = f"SELECT ?type WHERE {{ <{obj}> a ?type . }}"
        res2 = execute_sparql_query(q2, endpoint='dblp', format_type='json')
        if res2.get('success'):
            types = [b['type']['value'] for b in res2['results']]
            print(f"Types for {obj}:", types if types else "NO TYPES FOUND!")
        else:
            print(f"Failed to fetch types for {obj}:", res2)

