import sys, os
import pandas as pd
from querybloom.executor.sparql_executor import execute_sparql_query
bs = 'SELECT ?s ?o WHERE { ?s <https://dblp.org/rdf/schema#authoredBy> ?o . } LIMIT 10'
q1 = f'SELECT ?s ?o (datatype(?o) AS ?dType) WHERE {{ {{ {bs} }} }}'
res1 = execute_sparql_query(q1, endpoint='dblp', format_type='csv')
df = res1.get('results')
print('Triples o type:', type(df['o'].iloc[0]))
print('Triples o:', df['o'].tolist())
q2 = f'SELECT DISTINCT ?o ?oType WHERE {{ {{ SELECT DISTINCT ?o WHERE {{ {{ {bs} }} FILTER(isIRI(?o)) }} }} ?o a ?oType . }}'
