import json
import sys
sys.path.append('analyze')
from sparql_utils import measure_syntactic_diversity
import random

d1 = [json.loads(line) for line in open('subgraphs_output/qa_output/03-23-00-dblp.jsonl')]
d2 = [json.loads(line) for line in open('subgraphs_output/qa_output/dblp-test.jsonl')]

random.seed(42)
target_size = min(len(d1), len(d2))
d1 = random.sample(d1, target_size)
d2 = random.sample(d2, target_size)

res = measure_syntactic_diversity(d1, d2)
b1 = res['benchmark1']
b2 = res['benchmark2']

print('--- QueryBloom (Generated) ---')
print(f"Total entities/literals used: {b1.get('num_total_entities')}")
print(f"Unique entities/literals found: {b1.get('num_unique_entities')}")
print(f"Entities per query on avg: {b1.get('entities_per_query')}")
print(f"Ratio of unique to total: {b1.get('unique_to_total_entities_ratio'):.2%} ({b1.get('unique_to_total_entities_ratio')})")
print()
print('--- Baseline ---')
print(f"Total entities/literals used: {b2.get('num_total_entities')}")
print(f"Unique entities/literals found: {b2.get('num_unique_entities')}")
print(f"Entities per query on avg: {b2.get('entities_per_query')}")
print(f"Ratio of unique to total: {b2.get('unique_to_total_entities_ratio'):.2%} ({b2.get('unique_to_total_entities_ratio')})")