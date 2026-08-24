import json
import sys
from collections import Counter
sys.path.append('analyze')
from sparql_utils import parse_and_extract_rdflib_metrics

d1 = [json.loads(line) for line in open('subgraphs_output/qa_output/03-23-00-dblp.jsonl')]

all_entities = []
for row in d1:
    if 'sparql' in row:
        metrics = parse_and_extract_rdflib_metrics(row['sparql'])
        all_entities.extend(metrics['entities'])

counts = Counter(all_entities)
print("Most frequently used entities/literals in QueryBloom (Top 25):")
print("-" * 60)
for entity, count in counts.most_common(25):
    print(f"{count:3d} times: {entity}")
