import json, re
from collections import Counter

_LIT_RE = re.compile(r'"([^"]+)"')

def get_literals(filename):
    lits = []
    with open(filename) as f:
        for line in f:
            row = json.loads(line)
            q = row.get('sparql', row.get('query', ''))
            lits.extend(_LIT_RE.findall(q))
    return Counter(lits)

c_gen = get_literals('subgraphs_output/qa_output/03-23-00-dblp.jsonl')
c_base = get_literals('subgraphs_output/qa_output/dblp-test.jsonl')

print('QueryBloom -- Total literals:', sum(c_gen.values()), '| Unique:', len(c_gen))
print('Top 15:')
for k, v in c_gen.most_common(15):
    print(' ', v, 'x', repr(k))

print()
print('Baseline  -- Total literals:', sum(c_base.values()), '| Unique:', len(c_base))
print('Top 5:')
for k, v in c_base.most_common(5):
    print(' ', v, 'x', repr(k))
