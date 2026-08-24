import json
from collections import Counter
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib import URIRef, Literal

gen_file = 'cache/patterns_dblp_lim1500_max30000_minTrue_ms100_ex97f2b411_cl334c4a4c_inc334c4a4c_paper.json'
base_file = 'cache/patterns_dblp-qlever_lim1500_max30000_minTrue_ms100_ex97f2b411_cl334c4a4c_inc334c4a4c_paper.json'

def get_entities(query_str):
    entities = []
    try:
        q = parseQuery(query_str)
        algebra = translateQuery(q)
        def process_node(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    process_node(v)
            elif isinstance(node, list):
                for item in node:
                    process_node(item)
            elif isinstance(node, URIRef) or isinstance(node, Literal):
                entities.append(str(node))
        process_node(algebra)
    except Exception:
        pass
    return entities

def analyze(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'queries' in data:
        queries = [q.get('query', q) if isinstance(q, dict) else q for q in data['queries']]
    else:
        queries = [q.get('query', q) if isinstance(q, dict) else q for q in data]
        
    ents = []
    for q in queries:
        for e in get_entities(q):
            if str(e).startswith('http://www.w3.org/') or str(e).startswith('https://dblp.org/rdf/schema#'):
                continue
            ents.append(str(e))
    return Counter(ents)

print('Generated instance frequencies (top 20):')
for k, v in analyze(gen_file).most_common(20):
    print(f'{v}: {k}')

print('\nBaseline instance frequencies (top 20):')
for k, v in analyze(base_file).most_common(20):
    print(f'{v}: {k}')
