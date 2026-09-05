You are an expert in SPARQL and knowledge graph querying. You are reviewing question-query pairs that were generated
from a subgraph pattern and then executed against a SPARQL endpoint.

Your task is to verify whether each question-query pair is correct based on the execution results.

### Original Subgraph Pattern:
<Subgraph>
    {{ subgraph_pattern }}
</Subgraph>

### Generated Question-Query Pairs with Execution Results:
{% for qa in qa_pairs %}
**Pair {{ loop.index }}:**
- **Question:** {{ qa.question }}
- **SPARQL Query:**
```sparql
{{ qa.sparql_query }}
```
- **Execution Success:** {{ qa.execution_results.success }}
- **Result Count:** {{ qa.execution_results.count }}
{% if qa.execution_results.error_message %}- **Error:** {{ qa.execution_results.error_message }}{% endif %}
{% if qa.execution_results.result_preview %}- **Result Preview (first 3 rows):** {{ qa.execution_results.result_preview
}}{% endif %}

{% endfor %}

### Task:
For each question-query pair, assess whether it is **correct**, **needs_fix**, or **unfixable** based on:
1. Did the SPARQL query execute successfully?
2. Does the query correctly answer the natural language question? Are they consistent?
3. Are there any necessary fixes to the text or sparql queries.

Set `all_correct` to true only if ALL pairs are correct. If ANY pair needs fixing, set `all_correct` to false.

For pairs that need fixing:
- Provide a brief explanation in `reason`
- Provide the corrected question in `fixed_text_query`
- Provide the corrected SPARQL query in `fixed_sparql_query`

For correct pairs, leave `fixed_text_query` and `fixed_sparql_query` as null.

**Important:** a query that errors out, returns no results when it should, or doesn't match the question
semantics should be marked as `needs_fix`. Use `unfixable` only when no reliable correction exists.