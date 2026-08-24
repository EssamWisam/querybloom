You are an expert in analyzing a subgraph sampled from a knowledge graph and generating natural language questions with corresponding SPARQL
queries.


{% if kg_title %}
**Knowledge Graph Title:** {{ kg_title }}
{% endif %}
{% if kg_description %}
**Knowledge Graph Description:** {{ kg_description }}
{% endif %}

Given the following subgraph description loaded from a YAML file, generate
natural language questions that could be answered by querying the full knowledge graph, along with their corresponding
SPARQL queries.

### YAML Subgraph Description:
&lt;Subgraph&gt;
    {{ subgraph_pattern }}
&lt;/Subgraph&gt;

Notes on the YAML structure (generic, do not assume any specific KG):
- Each subgraph includes: subgraph_id, num_types, min_support, types, edges, predicate_uris.
- types is a mapping from type label to:
- uri (class URI)
- sample_entities (a few example entity URIs, sometimes with attributes shown as a compact string like attr:type=value)
- edges is a list of triples in a readable form: "TypeA --predicateLabel --&gt; TypeB".
- if an edge ends with "\*" after the arrow, it denotes an optional property (after adding the edge, the graph doesn't
meet the support property).
- predicate_uris lists predicate URIs aligned with the edges.
- Attributes marked with "\*" are below the subgraph's support threshold (optional attributes).

### Task:
First, assess whether this subgraph allows for meaningful questions. If the subgraph is too trivial, lacks interesting
relationships (eg, graph metadata as opposed to actual knowledge), or doesn't support generating useful and meaningful questions, set is_meaningful to false and return an empty questions
list.

If is_meaningful is true, generate 2-4 question-query pairs as a JSON array where each item has:
- text_query: the natural language question
- sparql_query: the corresponding SPARQL query



### Requirements:
1. Generate 2-4 question-query pairs depending on your assessment of the subgraph's richness. Try to attain high coverage of all the meaningful aspects of the subgraph in the question-query pairs.
2. Questions should be grounded in the classes, entities, relationships and attributes in this YAML subgraph. Using classes, entities, relationships and attributes not in the YAML subgraph is strictly prohibited!
3. Do not reference the YAML or the subgraph itself in the natural language question (each of text and query should be self-contained) and never mention a URI/prefix in the text question (or use knowledge graph terminology like properties, types, etc.)
4. Questions should be certaintly answerable and avoid ontology/schema/documentation questions
5. Focus on questions that are interesting and meaningful (avoid meaningless questions like "what/how many entities are linked to.../useless patterns...")
{% if focus_entity_qa %}
6. Great questions are often centered around interesting entities in the graph. All of the questions you produce must be entity centric.
Meanwhile, set is_meaningful to False if no interesting entities are available.
7. Make questions diverse in style (what, who, whom, whose, when, which, yes/no questions, how compounds, statistics, etc.) and complexity but while maintaining the quality of the questions and meaningfulness
{% else %}
6. Whenever there is an interesting entity is in the graph, it's good to have a question or two specifically about it
7. Make questions diverse in style (SELECT, SELECT + AGGREGATION, ASK, as appropriate) and complexity (MIN/MAX/AVG/COUNT/SUM, GROUP BY/FILTER/HAVING, EXISTS/OPTIONAL, nesting, etc.) but while maintaining the quality of the questions and meaningfulness
{% endif %}
8. Declare meaningful prefixes in the query based on the URIs in the yaml
9. Use proper SPARQL syntax to generate valid queries. Your sparql query must produce exactly the results expected by the text query.
10. If the question does not have one answer/result, you may or may not use LIMIT in SELECT queries (e.g., LIMIT 100) to avoid too many results. BUT MAKE SURE to REFLECT THIS in the text query!
11. SPARQL queries should be stand-alone executable against a SPARQL endpoint containing the full graph
12. If a term is awkward in the graph, and you are confident it can be rephrased naturally without being inaccurate, do so
13. The phrasing of the natural language question should be always natural, fluent and not awkward or stilted. Question should always end with a question mark.

### Final Note:
The ultimate goal is to produce high-quality, diverse, and very meaningful questions together with their corresponding
accurate SPARQL queries that can be executed against the full knowledge graph.

Another essential property is that an expert in the knowledge graph should be able to reproduce the same sparql query when given text question only.
- You will be penalized if the generated SPARQL query and the text question do not properly align (eg, the sparql query has constraints unrequested in the question... or misses requested ones)
- You will be also highly penalized if the generated SPARQL query incorrectly answer the text question or provides no answer when there is one.
- You will be penalized if your question styles are not diverse enough, if questions are of low quality or are phrased awkwardly.
- You will be rewarded when you generate questions an expert in the domain would ask where the sparql query being perfectly aligned to the question and accurately answering it. 
- Flagging the subgraph as not meaningful when it's hard to generate high quality questions is better than generating low quality questions.
- Generating fewer high quality questions that a DOMAIN EXPERT may ask is MUCH better than generating more low quality questions. Quality over quantity.