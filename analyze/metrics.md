# SPARQL Diversity Metrics

This document outlines how the structural and semantic SPARQL diversity metrics are computed for the benchmarking analysis. The underlying extraction relies heavily on generating an Abstract Syntax Tree (AST) of the SPARQL queries using `rdflib`.

## 1. Unique Entities
- **Definition:** The average number of unique knowledge graph entities used per query in the dataset.
- **Computation:** 
  1. Each query is parsed into an AST using `rdflib`.
  2. The AST is traversed to extract all `URIRef` nodes that appear in the **Subject** or **Object** positions of any triple pattern.
  3. A global set of these unique URIs is maintained across the entire dataset.
  4. Finally, the total count of unique entities is divided by the total number of queries in the dataset to yield the **Entities per Query (Density)** metric.

## 2. Unique Relations
- **Definition:** The average number of unique knowledge graph properties/relations used per query in the dataset.
- **Computation:** 
  1. Similar to entities, the query is parsed into an AST.
  2. The AST is traversed to extract all `URIRef` nodes that appear specifically in the **Predicate** position of any triple pattern.
  3. A global set of these unique property URIs is collected across the dataset.
  4. The total count of unique relations is divided by the total number of queries in the dataset to yield the **Relations per Query (Density)** metric.

## 3. Variables
- **Definition:** The average number of variables (`?var`) present within a single query.
- **Computation:** 
  1. The AST is traversed to identify all nodes of type `Variable`.
  2. These are collected into a mathematical `set` per query to calculate the exact number of unique variables defined within that specific query.
  3. The mean of these counts is calculated across the entire dataset.

## 4. Triples
- **Definition:** The average number of triple patterns defined within a single query.
- **Computation:**
  1. The AST is traversed to locate all `triples` blocks within the query structure (including those inside `OPTIONAL`, `UNION`, etc.).
  2. The exact number of triple definitions is counted per query.
  3. The mean of these counts is calculated across the entire dataset.

## 5. Unique Templates Ratio
- **Definition:** The ratio of structurally unique query skeletons (templates) relative to the total dataset size. High values indicate that the dataset relies on diverse query structures rather than repeating the same format with different entities.
- **Computation:** 
  1. `PREFIX` definitions are stripped from the query.
  2. A Regex-based anonymization pipeline sanitizes the query:
     - All variables (`?x`, `?name`) are replaced with `?VAR`.
     - All full URIs (`<http://.../Resource>`) are replaced with `<URI>`.
     - All literals (`"String"`, numbers) are replaced with `<LITERAL>`.
     - All prefixed names (`dbo:Person`) are replaced with `PREFIX:NAME`.
  3. The resulting string is the query's structural "Template".
  4. The number of unique templates is counted and divided by the total number of queries in the dataset to calculate the ratio (Max: 1.0).
