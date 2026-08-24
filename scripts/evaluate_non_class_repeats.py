import json
import urllib.request
from collections import Counter
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib import URIRef, Variable, Literal
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

gen_file = "cache/patterns_dblp_lim1500_max30000_minTrue_ms100_ex97f2b411_cl334c4a4c_inc334c4a4c_paper.json"
base_file = "cache/patterns_dblp-qlever_lim1500_max30000_minTrue_ms100_ex97f2b411_cl334c4a4c_inc334c4a4c_paper.json"

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
            elif isinstance(node, URIRef):
                entities.append(str(node))
            elif isinstance(node, Literal):
                entities.append(str(node))
        process_node(algebra)
    except Exception as e:
        pass
    return entities

def is_class(uri):
    if not str(uri).startswith("http"):
        return False
    from analyze.sparql_utils import _ENTITY_TYPE_CACHE
    return False # Just a heuristic, let's filter purely by dblp ontology

def analyze(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)
    if isinstance(data, dict) and "queries" in data:
        queries = [q["query"] if isinstance(q, dict) else q for q in data["queries"]]
    elif isinstance(data, list):
        queries = [q["query"] if isinstance(q, dict) else q for q in data]
    else:
        queries = [data]
        
    all_non_class = []
    for q in queries:
        ents = get_entities(q)
        for e in ents:
            if str(e).startswith("https://dblp.org/rdf/schema"):
                continue # Skip schema
            if str(e) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type":
                continue # Skip rdf:type
            if str(e).startswith("http://www.w3.org/2000/01/rdf-schema#"):
                continue # Skip rdfs
            if str(e).startswith("http://www.w3.org/2002/07/owl#"):
                continue # Skip owl
            all_non_class.append(str(e))
    
    c = Counter(all_non_class)
    return c

gen_c = analyze(gen_file)
base_c = analyze(base_file)

print("=== GENERATED QUERIES: NON-CLASS ENTITY REPEATS ===")
print(f"Total non-class entity occurrences: {sum(gen_c.values())}")
print(f"Unique non-class entities: {len(gen_c)}")
if sum(gen_c.values()) > 0:
    print(f"Ratio of unique/total: {len(gen_c) / sum(gen_c.values()):.2%}")
else:
    print("Ratio of unique/total: N/A")
print("Top 10 most frequent non-class entities:")
for k, v in gen_c.most_common(10):
    print(f"  {v} times: {k}")

print("\n=== BASELINE QUERIES: NON-CLASS ENTITY REPEATS ===")
print(f"Total non-class entity occurrences: {sum(base_c.values())}")
print(f"Unique non-class entities: {len(base_c)}")
if sum(base_c.values()) > 0:
    print(f"Ratio of unique/total: {len(base_c) / sum(base_c.values()):.2%}")
else:
    print("Ratio of unique/total: N/A")
print("Top 10 most frequent non-class entities:")
for k, v in base_c.most_common(10):
    print(f"  {v} times: {k}")
