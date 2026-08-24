import json
from querybloom.abstat import ABSTAT_v2

# Test DBLP ontology extraction using ABSTAT_v2 class with LIMIT 10 so it's super fast.
abstat = ABSTAT_v2(endpoint="https://qlever.cs.uni-freiburg.de/api/dblp", 
                save_dir="cache", 
                knowledge_graph_name="dblp_test2")
stats = abstat.summarize(
    limit_per_property=1000,
    max_properties=2, # Keep it very small
    min_ontology=True
)

file_path = abstat.save_path
with open(file_path, "r") as f:
    data = json.load(f)

print(f"Object Patterns: {len(data['patterns']['object'])}")
print(f"Attribute Patterns: {len(data['patterns']['attribute'])}")
print("Some Object Patterns:", list(data['patterns']['object'].keys())[:2])

