import json
import re
from collections import Counter

gen_file = "subgraphs_output/qa_output/03-23-00-dblp.jsonl"
base_file = "subgraphs_output/qa_output/dblp-test.jsonl"

# Regex: match <uri> tokens directly from the raw SPARQL string — no endpoint calls needed
_URI_RE = re.compile(r'<([^>]+)>')

SCHEMA_PREFIXES = (
    "http://www.w3.org/",
    "https://www.w3.org/",
    "http://dblp.org/rdf/schema#",
    "https://dblp.org/rdf/schema#",
)

def extract_non_schema_entities(filename):
    ents = []
    with open(filename) as f:
        for line in f:
            row = json.loads(line)
            q = row.get("sparql", row.get("query", ""))
            for uri in _URI_RE.findall(q):
                if not any(uri.startswith(p) for p in SCHEMA_PREFIXES):
                    ents.append(uri)
    return Counter(ents)

c_gen = extract_non_schema_entities(gen_file)
c_base = extract_non_schema_entities(base_file)

print(f"Generated Total Instances (non-schema): {sum(c_gen.values())}")
print(f"Generated Unique Instances: {len(c_gen)}")
if sum(c_gen.values()) > 0:
    print(f"Ratio: {len(c_gen)/sum(c_gen.values()):.2%}")
print("\nGenerated Top 20 repeated instances:")
for k, v in c_gen.most_common(20):
    print(f"{v}: {k}")

print("\n-------------------------")
print(f"Baseline Total Instances (non-schema): {sum(c_base.values())}")
print(f"Baseline Unique Instances: {len(c_base)}")
if sum(c_base.values()) > 0:
    print(f"Ratio: {len(c_base)/sum(c_base.values()):.2%}")
print("\nBaseline Top 20 repeated instances:")
for k, v in c_base.most_common(20):
    print(f"{v}: {k}")
