import json
from collections import Counter
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib import URIRef, Literal
import random

gen_file = "subgraphs_output/qa_output/03-23-00-dblp.jsonl"
base_file = "subgraphs_output/qa_output/dblp-test.jsonl"

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

def extract(data):
    ents = []
    for q_obj in data:
        q = q_obj.get("query", "")
        for e in get_entities(q):
            s = str(e)
            if s.startswith("http://www.w3.org/") or s.startswith("https://dblp.org/rdf/schema#"):
                continue
            ents.append(s)
    return Counter(ents)

d1 = [json.loads(line) for line in open(gen_file)]
d2 = [json.loads(line) for line in open(base_file)]

random.seed(42)
target_size = min(len(d1), len(d2))
d1 = random.sample(d1, target_size)
d2 = random.sample(d2, target_size)

c1 = extract(d1)
c2 = extract(d2)

print(f"Generated Total Instances (non-schema): {sum(c1.values())}")
print(f"Generated Unique Instances: {len(c1)}")
if sum(c1.values()) > 0:
    print(f"Ratio: {len(c1)/sum(c1.values()):.2%}")
print("\nGenerated Top 20 repeated instances:")
for k, v in c1.most_common(20):
    print(f"{v}: {k}")

print("\n-------------------------")
print(f"Baseline Total Instances (non-schema): {sum(c2.values())}")
print(f"Baseline Unique Instances: {len(c2)}")
if sum(c2.values()) > 0:
    print(f"Ratio: {len(c2)/sum(c2.values()):.2%}")
print("\nBaseline Top 20 repeated instances:")
for k, v in c2.most_common(20):
    print(f"{v}: {k}")
