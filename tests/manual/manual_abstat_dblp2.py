from querybloom.mining import SubgraphMiner

miner = SubgraphMiner(endpoint="https://qlever.cs.uni-freiburg.de/api/dblp")
miner.preprocess(property_limit=3)

print("Object patterns:", len(miner.abstat.minimal_patterns))
print("Attribute patterns:", len(miner.abstat.attribute_patterns))
