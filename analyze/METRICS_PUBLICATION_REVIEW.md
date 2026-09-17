# Publication Review of `kg-benchmark-eval` Metrics

## Bottom line

The package is a useful **descriptive benchmark-audit toolkit**, but the complete metric suite is
not yet strong enough to present as a validated measurement framework in a peer-reviewed paper.
Vendi Score, average pairwise semantic distance, raw feature frequencies, and ontology coverage
are defensible when their dependencies and uncertainty are reported. Several custom metrics shown
in the figures have construct-validity or interpretation problems. The current `DISTINCT`
redundancy calculation is also invalid, although `DISTINCT` is excluded from the feature plot by
default and is therefore a lower-priority issue for the reported figures.

A paper can publish results from this package after the blockers below are fixed and the claims are
narrowed. The metrics support statements such as "benchmark A contains more varied question
embeddings under encoder E" or "touches a larger fraction of ontology snapshot O." They do not, by
themselves, establish that a benchmark is higher quality, more representative, more difficult, or
better at discriminating NL-to-SPARQL systems.

## Metric-by-metric assessment

| Metric | Verdict | What it validly measures | Main qualification |
| --- | --- | --- | --- |
| Semantic APD | Keep with changes | Mean pairwise cosine distance under one encoder | Encoder-dependent; report uncertainty and note the mathematical range is 0–2, not approximately 0–1 |
| Vendi Score | Keep | Effective semantic diversity under one similarity kernel | Report encoder/version, full score, score relative to corpus size, and a same-size resampling comparison |
| Unique template ratio | Replace current implementation | Intended to measure repeated query skeletons | Current templates preserve whitespace and use regex substitution, so formatting can count as structural novelty |
| Feature usage percentages | Keep | Prevalence of selected SPARQL constructs | Use parser-derived features and confidence intervals; the current regex detector can count text in comments or literals |
| Feature entropy | Rename or replace | Evenness of aggregate feature marginals | It is not entropy of query structures or feature combinations, and correlated features are treated as separate mass |
| Operator-count distribution | Rename and supplement | Distribution of the number of detected feature types per query | It is not a full operator count and ignores triple count, joins, nesting, path length, and repeated operators |
| Row/column-count distributions | Descriptive only | Endpoint-specific result cardinality and arity | Heavy-tailed, time-dependent, and currently contaminated by failed executions recorded as zero |
| Class/property coverage | Keep with provenance | Fraction of a declared ontology snapshot touched | Depends on snapshot and resolver behavior; missing-universe handling is low priority here because both KGs have universes |
| Feature coverage | Supplement only | Whether each of 13 selected features appears at least once | Saturates easily and gives one occurrence the same credit as systematic coverage |
| Distinct classes/properties/entities per query | Rename | Corpus-level unique-term richness divided by query count | With equal-size benchmarks it ranks richness correctly, but it is not the mean number of terms in a query |
| Class/property/entity novelty | Replace or rename | Reciprocal mean query incidence per observed term | Equal benchmark size controls its largest comparability problem, but it still ignores the term-frequency distribution |
| Feature redundancy hatching | Redesign before interpretation | Intended effect of removing or weakening a feature | Failures and broad interventions can be mistaken for semantic effects; `DISTINCT` is excluded from the plot by default |

The table intentionally includes only metrics displayed in the package's plots. Metrics that are
computed or serialized but not plotted, such as filter-template ratio and aggregate standard
deviations, are outside the scope of the publication verdict.

## Findings and publication priorities

### Lower-priority implementation note: `DISTINCT`

The package removes `DISTINCT` and compares result rows as sets. Set conversion discards duplicate
multiplicity, which is precisely the observable behavior controlled by `DISTINCT`. For example,
`[a, a]` and `[a]` compare equal, so the metric labels an effective `DISTINCT` as redundant.
The behavior is implemented in
[`metrics/redundancy.py`](kg-benchmark-eval/src/kg_benchmark_eval/metrics/redundancy.py) and explicitly
asserted by [`tests/test_metrics.py`](kg-benchmark-eval/tests/test_metrics.py).

**Required fix:** compare `DISTINCT` results as multisets (`collections.Counter` over canonical RDF
term rows), not sets. Preserve RDF term identity: lexical value, term type, datatype, and language
tag. Add fixtures where removing `DISTINCT` changes only multiplicity. This does not block the
current feature figure because `DISTINCT` is excluded from feature coverage and the feature bar
chart by default. It becomes a publication blocker if a separate redundancy figure reports
`DISTINCT`.

### 1. Redundancy mixes semantic change with execution failure

Failed original/modified executions stay in the eligible denominator and contribute zero to the
redundant numerator. Endpoint instability therefore lowers reported redundancy. In addition,
`ASK` observations cannot match because `canonical_rows` accepts only `SELECT`; a `FILTER` or
`OPTIONAL` used in an `ASK` query is consequently classified as changed even when both Boolean
answers are equal.

Removing every `FILTER` or every `OPTIONAL` at once estimates a joint intervention, not the
necessity of each occurrence. Regex/balanced-delimiter rewriting can also generate a query whose
meaning changes beyond the target construct. These are useful diagnostics, but not yet a validated
measure of semantic redundancy.

**Required fix:** report `redundant / successfully compared` together with `failed / attempted`;
never encode failures as evidence. Compare `ASK` Boolean values directly. Mutate one algebra node
at a time, validate the rewritten query, and report both occurrence-level and query-level effects.
For `ORDER BY`, repeat execution or impose deterministic tie-breaking before interpreting order
changes.

### 2. Execution failures contaminate complexity

Failed endpoint calls are stored as zero rows and zero columns before standard deviations are
computed in [`evaluator.py`](kg-benchmark-eval/src/kg_benchmark_eval/evaluator.py). A zero is a valid
empty result, so outage and data are indistinguishable in the statistic. This can reverse a
comparison when one benchmark contains more expensive queries or is evaluated during a less stable
endpoint period.

**Required fix:** represent failed counts as missing. Report success rate and failure reasons, then
compute cardinality summaries only over successful executions. Include a sensitivity result that
shows whether conclusions change when failures are excluded. Pin the KG dump or endpoint snapshot,
date, timeout, concurrency, and cache policy.

### 3. Template diversity is formatting-sensitive

Whole-query anonymization replaces variables, terms, and literals but does not canonicalize
whitespace. Semantically identical queries with different indentation can therefore produce
different templates. Regex substitution also does not canonicalize triple order, commutative
FILTER expressions, prefix aliases, or equivalent SPARQL algebra.

**Required fix:** derive templates from parsed SPARQL algebra. Canonicalize variable names, prefix
expansion, whitespace, and order only where algebraic order is irrelevant. Report exact normalized
query duplication separately from algebra-template duplication. Manually label a stratified sample
of query pairs and report precision/recall or agreement for the claim "same structure."

### 4. Novelty and richness remain limited under equal-size comparison

The two benchmarks compared in this study always contain the same number of queries. This is an
important control: for `distinct_*_per_query` $=S/n$, equal $n$ makes the comparison equivalent to
comparing raw richness $S$. The metric therefore ranks corpus-level richness correctly in this
experimental design. Its name is still misleading because it is not the mean number of terms in a
query.

For a term type, the implemented novelty is

$$
N = \frac{S}{\sum_{i=1}^{S} f_i} = \frac{1}{\bar f},
$$

where $S$ is the number of observed terms and $f_i$ is the number of queries containing term $i$.
Equal query counts substantially reduce sample-size bias, so $N$ can compare the fraction of term
incidences represented by distinct terms in these experiments. However, it uses only richness and
total incidence. Two benchmarks can receive the same score when one is dominated by a few terms
and the other uses terms evenly, despite having meaningfully different schema diversity. The score
is better described as reciprocal mean term incidence than as novelty.

**Recommended change:** label $S/n$ as `term_richness_per_query`, report raw richness $S$, and add
the actual mean number of distinct terms per query. Supplement or replace novelty with Hill numbers
computed from normalized document frequencies $p_i=f_i/\sum_j f_j$:

$$
{}^1D=\exp\left(-\sum_i p_i\log p_i\right), \qquad
{}^2D=\frac{1}{\sum_i p_i^2}.
$$

Report evenness ${}^1D/S$ when the intended question is whether usage is concentrated among a few
terms. Hill numbers retain the frequency distribution and have an interpretable unit: effective
number of terms. Same-size bootstrap intervals remain useful for uncertainty; rarefaction is
optional here because benchmark size is already matched.

### 5. Feature entropy does not measure structural diversity

The implementation computes entropy after normalizing the 13 marginal feature-use rates to sum to
one. Those entries are not mutually exclusive outcomes: one query contributes to several features,
and features such as `SELECT`, `GROUP BY`, `HAVING`, and `COUNT` are logically correlated. A nearly
universal `SELECT` flag also consumes probability mass. The result is a valid entropy of a chosen
frequency profile, but it is not entropy over queries, structures, or feature combinations.

**Required fix:** rename it `marginal_feature_profile_entropy` if retained. Prefer entropy or Hill
diversity over observed feature-set signatures, and separately report pairwise feature dependence
(for example, Jaccard similarity or normalized mutual information). Exclude query form from the
operator vocabulary or analyze `SELECT` and `ASK` as a separate dimension.

### 6. Coverage robustness is low priority for the two KGs studied

Class/property coverage is interpretable relative to the exact ontology snapshot. Both KGs in the
reported comparisons have ontology universes, so the package's behavior when a universe is missing
does not threaten these results. Equal benchmark sizes also control the main sample-size effect.
The relevant remaining risk is reproducibility: coverage can change with the ontology snapshot and
with resolver success or fallback behavior.

**Recommendation:** publish hashes and extraction rules for ontology snapshots, resolver
success/fallback rates, and parse success. Returning missing/undefined when a universe is absent is
still correct package behavior, but it is a low-priority robustness fix for this paper. A
hierarchy-aware coverage supplement would add information because flat coverage cannot distinguish
one narrow ontology branch from several top-level domains.

## Recommended publication metric set

Use a small set with explicit constructs rather than one composite "quality" score:

1. **Semantic diversity:** full-corpus Vendi Score, Vendi/$n$, APD distribution (median and
   interquartile range, not only mean), and same-size bootstrap/rarefaction curves. Repeat with at
   least one independently trained sentence encoder; report rank stability.
2. **Structural diversity:** parser/algebra-based unique-template rate, template Hill diversity,
   exact normalized duplicate rate, and the frequency distribution of templates.
3. **Schema breadth:** raw class/property/entity richness and ontology coverage with snapshot
  provenance. Add same-size bootstrap intervals; rarefaction is optional while benchmark sizes
  are matched.
4. **Schema balance:** term-frequency Hill numbers ${}^1D$ and ${}^2D$, evenness ${}^1D/S$, and
   the share of mentions accounted for by the top 10 terms.
5. **SPARQL construct breadth:** parser-derived feature prevalence with Wilson intervals,
   feature-set-signature diversity, and counts for nesting depth, basic graph patterns, triple
   patterns, joins, unions, optionals, subqueries, aggregates, and property-path length.
6. **Execution complexity:** median and IQR of `log1p(row_count)`, zero-result rate, timeout/error
   rate, and result arity distribution. Keep standard deviation only as a secondary statistic.
7. **Feature necessity:** corrected intervention results with multiset/RDF-term comparison,
   occurrence-level mutations, successful-comparison denominator, and manually inspected examples.
8. **Benchmark utility:** system-level difficulty and discrimination. Evaluate multiple materially
   different NL-to-SPARQL systems and report accuracy distributions, confidence intervals, item
   difficulty, and whether proposed diversity measures predict complementary system failures.

The final item is essential if the paper claims these are metrics of benchmark **quality** rather
than only benchmark composition.

## Validation needed for a metric paper

- **Construct validity:** state one construct per metric and expected behavior under controlled
  transformations: exact duplication, paraphrasing, whitespace changes, term substitution, query
  expansion, and endpoint failure.
- **Convergent/discriminant validity:** test whether metrics intended to measure the same construct
  correlate, and whether semantic, structural, schema, and execution dimensions remain distinct.
- **Human validation:** have SPARQL experts judge sampled query pairs for semantic and structural
  similarity; compare those judgments with APD and template decisions.
- **Robustness:** vary encoder, ontology snapshot, random seed, sample size, and endpoint conditions.
  Report confidence/stability intervals and rank reversals, not only point estimates.
- **Predictive validity:** test whether higher measured coverage/diversity exposes additional system
  failures or changes model rankings. Without this evidence, avoid claiming that higher is better.
- **Reproducibility:** publish benchmark hashes, query exclusions, parse and execution success rates,
  model revision, ontology hashes, endpoint snapshot, cached artifacts, and metric code version.

## Priority order

1. Remove failed executions from complexity and redundancy values; compare `ASK` results correctly.
2. Replace text templates and regex feature flags with parser/algebra-derived representations.
3. Relabel novelty and `distinct_*_per_query`; add raw richness, per-query means, Hill diversity,
  and same-size bootstrap intervals.
4. Add uncertainty, provenance, and robustness analyses.
5. Fix `DISTINCT` comparison before reporting `DISTINCT` redundancy; it is not required for the
  current default feature plot.
6. Validate metric behavior against expert judgments and downstream system discrimination.

Until items 1–3 are complete, the safest paper framing is **an exploratory descriptive analysis
using a reproducible toolkit**, not a claim that the package defines validated benchmark-quality
metrics.

## References informing the recommendations

- Friedman, D. and Dieng, A. B. (2023). [The Vendi Score: A Diversity Evaluation Metric for Machine
  Learning](https://openreview.net/forum?id=g97OHbQyk1). *Transactions on Machine Learning Research*.
- Hill, M. O. (1973). [Diversity and Evenness: A Unifying Notation and Its
  Consequences](https://doi.org/10.2307/1934352). *Ecology*, 54(2), 427–432.
- Chao, A. et al. (2014). [Rarefaction and extrapolation with Hill numbers: a framework for sampling
  and estimation in species diversity studies](https://doi.org/10.1890/13-0133.1). *Ecological
  Monographs*, 84(1), 45–67.
- W3C (2013). [SPARQL 1.1 Query Language](https://www.w3.org/TR/sparql11-query/), especially solution
  sequences, `DISTINCT`, ordering, and RDF-term semantics.

## Reviewed implementation surface

This assessment checked the numerical contract and the production implementations in
[`metrics.md`](metrics.md),
[`metric_definitions.md`](kg-benchmark-eval/docs/metric_definitions.md),
[`metrics/diversity.py`](kg-benchmark-eval/src/kg_benchmark_eval/metrics/diversity.py),
[`metrics/coverage.py`](kg-benchmark-eval/src/kg_benchmark_eval/metrics/coverage.py),
[`metrics/redundancy.py`](kg-benchmark-eval/src/kg_benchmark_eval/metrics/redundancy.py),
[`preprocessing.py`](kg-benchmark-eval/src/kg_benchmark_eval/preprocessing.py), and
[`evaluator.py`](kg-benchmark-eval/src/kg_benchmark_eval/evaluator.py), together with the metric
tests. Class, property, and entity novelty are included even though they may not appear in older
copies of the root documentation.