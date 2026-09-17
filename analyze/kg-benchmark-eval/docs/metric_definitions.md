# Metric Definitions

This document is the numerical contract for `kg-benchmark-eval` 0.1.

## Semantic Diversity

- `diversity.semantic.apd`: mean of $1-K_{ij}$ over the strict upper triangle
  of the cosine matrix of L2-normalized question embeddings. The reported value
  is rounded to four decimals and is undefined for fewer than two questions.
- `diversity.semantic.vendi`: if $\lambda_i$ are the positive eigenvalues of
  $K/n$, the score is $\exp(-\sum_i \lambda_i\log\lambda_i)$. Positive
  eigenvalues are not renormalized. The result is rounded to four decimals.

## Structural Diversity

- `unique_template_ratio`: distinct whole-query templates divided by query
  count, rounded to four decimals.
- `distinct_entities_per_query`: size of the union of resolved entities divided
  by query count, unrounded.
- `filter_template_ratio`: distinct FILTER templates divided by FILTER clause
  occurrences, rounded to four decimals.
- `feature_entropy_bits`: Shannon entropy over the normalized means of the 13
  binary feature columns, rounded to four decimals.
- `distinct_classes_per_query` and `distinct_properties_per_query`: corresponding
  coverage numerators divided by query count, unrounded.
- `class_richness`, `property_richness`, and `entity_richness`: the number of
  distinct resolved terms observed in the benchmark.
- `*_mean_per_query`: mean number of distinct terms of the indicated type per
  query. A term contributes at most once per query.
- `*_hill_1` and `*_hill_2`: Hill diversity from normalized per-query document
  frequencies $p_i=f_i/\sum_j f_j$: $^1D=\exp(-\sum_i p_i\log p_i)$ and
  $^2D=1/\sum_i p_i^2$. Both have units of effective number of terms.
- `*_evenness`: $^1D/S$, where $S$ is the corresponding raw richness. All
  floating-point term-diversity values are rounded to four decimals.

The feature order is `SELECT`, `ASK`, `DISTINCT`, `COUNT`, `OPTIONAL`, `UNION`,
`FILTER`, `EXISTS`, `GROUP BY`, `HAVING`, `ORDER BY`, `LIMIT`, and
`Property Paths`. Usage percentages are the percentage of queries with each
binary flag, rounded to one decimal. FILTER subtype percentages use query count
as their denominator.

## Complexity

Operator count is the per-query sum of all binary features except `SELECT` and
`ASK`. Row count is the normalized result-list length. A successful ASK counts
as one row and one column regardless of its boolean value. For an empty SELECT,
column count uses `head.vars`; otherwise it uses bindings in the first row.
Failures and disabled execution contribute zero. Standard deviations are
population values over untrimmed arrays and are rounded to four decimals.

## Coverage

Class and property coverage intersect observed terms with the corresponding
ontology universe and divide by universe size. Feature coverage divides the
number of used base flags by 13. Ratios are rounded to four decimals. If an
ontology universe is unavailable, the ratio is zero and the raw numerator is
the observed benchmark count, preserving the documented legacy behavior.

## Redundancy

For each of `DISTINCT`, `FILTER`, `OPTIONAL`, `ORDER BY`, and `LIMIT`, mutate the
query with the production helper and compare original and modified results.
No-op mutations are excluded. Eligible pairs with unavailable results remain in
the denominator and contribute zero to the numerator. Result rows compare as
sets except `ORDER BY`, which compares ordered lists. Bindings compare variable
names and lexical `value` only; duplicate multiplicity is ignored outside
`ORDER BY`. Modified queries alone receive the 100,000-row cap.