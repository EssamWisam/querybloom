# Benchmark Metrics

Every metric reported in the notebooks comes from one of three measurement passes over a
benchmark (a parallel list of natural-language questions and SPARQL queries):

| Pass | Module | What it answers |
| --- | --- | --- |
| Diversity | `metrics/diversity.py` | How varied are the questions, query structures, and query complexity? |
| Comprehensiveness | `metrics/comprehensiveness.py` | How much of the knowledge graph and of SPARQL itself does the benchmark touch? |
| Redundancy | `metrics/redundancy.py` | Do the SPARQL features actually change the answer, or are they decoration? |

Sections 1–3 describe the shared preprocessing that all metrics depend on; read them first,
because every later definition assumes it.

---

## 1. Shared preprocessing

### 1.1 Query normalisation

Before any query is parsed or executed it is repaired, because benchmark files contain
formatting defects that `rdflib` rejects:

- Backslash escapes inside angle-bracket URIs are dropped, so `<...Barons\'_Crusade>` becomes
  `<...Barons'_Crusade>`. The punctuation is legal in an IRI; the backslash is not.
- Whitespace between a closing quote and a language tag or datatype suffix is removed, since
  `"foo" @en` and `"foo" ^^xsd:string` are single lexical tokens in SPARQL.
- For QALD-9 files only (detected from the dataset filename), three prefixes that the benchmark
  uses without declaring — `dbc`, `dct`, `yago` — are prepended as `PREFIX` lines, but only when
  the query actually uses that prefix and has not declared it itself.

### 1.2 Query body and boilerplate filters

Most textual analyses work on the *query body*: the query with all `PREFIX ...` lines removed.

Within the body, language-gate `FILTER`s are deleted before any feature is counted. Two forms are
removed: `FILTER(lang(?x) = "en")` and `FILTER(langMatches(lang(?x), "en"))`, in either quote
style and case-insensitively. These are boilerplate that adds no structural variety, and leaving
them in would inflate the FILTER usage percentage and the FILTER redundancy rate.

### 1.3 Parsing a query into terms

A query is parsed with `rdflib` into its algebra tree, and the tree is walked to collect, from
every triple pattern anywhere in the query (including inside `OPTIONAL`, `UNION`, subqueries):

- **Triple count** — the number of triple patterns, summed across all pattern blocks.
- **Properties** — every URI in the predicate position. Variables in that position are added to
  the variable set instead; nothing else can legally appear there.
- **Literals** — every literal constant in the subject or object position, kept in a separate list
  so that they can never count as entities.
- **Variables** — if the query has a `SELECT` projection list, the variable set is exactly that
  projection list (the true output columns). Otherwise (e.g. `ASK`), it is every variable seen in
  the subject, predicate, or object position anywhere in the graph pattern.
- **Classes** — every URI in the object position of an `rdf:type` triple is a class. Each remaining
  subject/object URI is then a class, in order, when its endpoint types include `owl:Class`,
  `rdfs:Class`, or `rdfs:Datatype`; when it has no non-meta endpoint types of its own and an
  endpoint existence check finds a resource typed with it; or, only when the type lookup returned
  no types, when it is present in the indexed `classes.yaml` list. The no-non-meta-types condition
  prevents a URI that is also a real instance from being promoted by RDF punning. Successful type
  and existence lookups are cached on disk.
- **Entities** — every eligible subject/object URI that is not classified as a class. Literals and
  variables are excluded, as are `rdf:type` objects. Entity URIs remain an append-to-list result
  with no deduplication.
- **Endpoint outage** — failed endpoint lookups log the dataset and 1-based query index, are not
  cached, and skip their evidence rule. A URI then falls through to the indexed class-list
  fallback and finally to entity, so an outage can inflate entity counts.

**Parse failure.** If `rdflib` cannot parse the query, a warning is logged with the dataset name
and the query's 1-based index, and the query contributes zero triples and empty term sets. It is
still counted in the denominator of any per-query average.

### 1.4 Query anonymisation (templates)

A query is reduced to a structural *template* by taking the query body and, in order:

1. Replacing every variable (`?name`, `?x`) with `?VAR`.
2. Replacing every full URI (`<http://...>`) with `<URI>`.
3. Replacing every quoted literal (with optional `^^<datatype>`) and every bare number with
   `<LITERAL>`.
4. Replacing every prefixed name (`dbo:Person`) with `<URI>` — the *same* token as step 2, so that
   two queries differing only in whether they spell a term out or abbreviate it produce identical
   templates.

Two queries share a template when they have the same shape after this substitution. Whitespace is
not normalised for whole-query templates, so formatting differences do produce distinct templates;
for FILTER-clause templates (§3.3) runs of whitespace are collapsed to a single space.

### 1.5 SPARQL feature flags

Thirteen features are tracked per query as binary flags (present / absent, never a count):

`SELECT`, `ASK`, `DISTINCT`, `COUNT`, `OPTIONAL`, `UNION`, `FILTER`, `EXISTS`, `GROUP BY`,
`HAVING`, `ORDER BY`, `LIMIT`, `Property Paths`.

Detection rules:

- `SELECT`, `ASK`, `DISTINCT`, `COUNT` are matched as whole words against the **full query text**
  (prefixes included), because they live in the header.
- The remaining keyword features are matched against the **body with language filters stripped**
  (§1.2), so a `PREFIX` line containing the substring `limit` cannot trigger a false positive.
- `Property Paths` is detected heuristically: URIs are blanked to the token `URI` and literals to
  `LITERAL`, then the query is searched for a term (a prefixed name or `URI`) immediately followed
  by one of `*`, `+`, `|`, `/`. This will also fire on a few non-path uses of `/` and is therefore
  an upper bound.

**Bar-chart exclusions.** `COUNT`, `DISTINCT`, and `EXISTS` are excluded from the feature bar chart
(`FILTER` is shown as a single aggregate bar). Only features used by at least 5 % of queries in at
least one of the two benchmarks being compared are drawn.

### 1.6 FILTER subtypes

Each `FILTER` clause is additionally given a label of the form `FILTER:<X>`, derived automatically
rather than from a hand-written category list:

- `FILTER NOT EXISTS` → `FILTER:NOT EXISTS`; `FILTER EXISTS` (not preceded by `NOT`) →
  `FILTER:EXISTS`. These are keyword-level and detected separately from parenthesised filters.
- For each `FILTER(...)` clause, the parenthesised body is extracted by balanced-parenthesis
  scanning (so nested calls are kept whole). Every `NAME(` occurrence inside it is checked against
  the list of SPARQL 1.1 built-in functions. Helper functions that are almost always nested —
  `NOW`, `STR`, `URI`, `IRI`, `BNODE` — are discarded whenever a more informative function is also
  present, so `YEAR(NOW())` is labelled `FILTER:YEAR`. The first (outermost) surviving function
  gives the label.
- If no recognised function call is present, the clause is classified by operator, in this
  priority order: `!=` → `FILTER:!=`; any of `>=`, `<=`, `>`, `<` → `FILTER:comparison`; `=` →
  `FILTER:=`; the word `IN` → `FILTER:IN`; otherwise `FILTER:other`.

Subtypes are collected as a **set per query**, so a query with three `REGEX` filters contributes
one `FILTER:REGEX`. The reported number for each subtype is the percentage of queries containing
it at least once. These percentages are merged into the same dictionary as the feature
percentages of §1.5.

---

## 2. Semantic diversity (natural-language questions)

Questions are encoded with a SentenceTransformer model into L2-normalised embeddings, so the dot
product of any two embeddings is their cosine similarity. For BGE models the prefix
`"Represent this sentence: "` is prepended to each question, as that family expects it.
Embeddings are cached on disk keyed by model name plus the sorted question list.

### 2.1 Average Pairwise Distance (APD)

- **Definition:** mean cosine *distance* between two distinct questions. Ranges 0 (all questions
  identical in meaning) to ~1; higher is more diverse.
- **Computation:** build the full cosine-similarity matrix of the embeddings, take only the
  strictly upper triangle (each unordered pair once, no self-pairs), and average `1 - similarity`
  over those entries.

### 2.2 Vendi Score

- **Definition:** an "effective number of distinct questions". A benchmark of 200 questions that
  are all paraphrases scores near 1; one with 200 mutually unrelated questions scores near 200.
  Unlike APD it is not saturated by a few far-apart outliers — it counts how many *directions* the
  set actually spans.
- **Computation:** take the cosine-similarity matrix, divide it by the number of questions, and
  compute its eigenvalues. Discard non-positive eigenvalues (numerical noise). The score is the
  exponential of the Shannon entropy (natural log) of the remaining eigenvalues treated as a
  probability distribution.

### 2.3 Semantic space plot

The two benchmarks' embeddings are projected together with a single t-SNE fit (perplexity 30, or
*n*−1 if the combined set is smaller), then drawn in two panels sharing identical axis limits so
the panels are visually comparable. Before projection, the furthest 5 % of points from each
benchmark's own centroid are dropped (configurable; the notebooks pass 1 %) so a handful of
outliers cannot compress the rest of the layout.

---

## 3. Structural diversity (SPARQL queries)

### 3.1 Unique template ratio

- **Definition:** the fraction of query skeletons that are structurally distinct. 1.0 means no two
  queries share a shape; 0.1 means the benchmark is ten fills of the same handful of templates.
- **Computation:** anonymise every query (§1.4), count the distinct template strings, and divide
  by the number of queries. An empty benchmark yields 0.

### 3.2 Average entities per query

- **Definition:** how many *distinct* KG instances the benchmark as a whole names, amortised over
  its size. It measures entity breadth, not per-query entity count — a benchmark that asks 100
  questions about the same person scores near 0.01.
- **Computation:** pool the entity URIs of every query into one set across the whole benchmark
  after applying the evidence-based class rules in §1.3, then divide the size of that set by the
  number of queries. When no KG name is supplied, the syntactic and endpoint rules still apply but
  the indexed-class fallback does not. The result is not rounded.

### 3.3 Filter template ratio

- **Definition:** the fraction of FILTER clauses that are structurally distinct — how much genuine
  variety exists in the filtering, as opposed to the same comparison repeated with different
  constants.
- **Computation:** from every query, extract each FILTER clause and anonymise it (§1.4 rules plus
  whitespace collapsing). `FILTER EXISTS` and `FILTER NOT EXISTS` are emitted as the fixed tokens
  `FILTER EXISTS { ... }` and `FILTER NOT EXISTS { ... }` rather than being expanded. Parenthesised
  filters become `FILTER ( <anonymised body> )`. Pool the templates across the benchmark — note
  this is a **list, not a set**, so a query with two filters contributes two entries — and divide
  the number of distinct templates by the total number of clauses. Returns 0 when the benchmark
  has no FILTER clauses at all.

### 3.4 Feature entropy

- **Definition:** how evenly the benchmark spreads its usage across the 13 tracked SPARQL features
  (§1.5). Low entropy means the benchmark leans on one or two constructs; high entropy means usage
  is spread out. Measured in bits, with a ceiling of log₂(13) ≈ 3.70.
- **Computation:** build the queries × 13 binary feature matrix, take the column means (the usage
  rate of each feature), normalise those means to sum to 1, drop zero entries, and compute the
  Shannon entropy in base 2. Returns 0 if no feature is used at all.
- **Caveat:** this is the entropy of the *usage-rate profile*, not of the joint distribution of
  feature combinations. Because `SELECT` is present in nearly every query, it dominates the
  profile and compresses the achievable range.

### 3.5 Feature usage percentages

For each of the 13 features, the percentage of queries in which its flag is set, rounded to one
decimal. The FILTER subtype percentages of §1.6 are added to the same table. These are what the
feature-distribution bar panel plots, drawn back-to-back: one benchmark extends upward, the other
downward, from a shared zero line.

### 3.6 Class, property, and entity novelty

- **Definition:** the inverse of cross-query repetition for each term type. A score of 1 means
  every observed term appears in exactly one query; lower values mean terms recur across queries.
- **Computation:** for each query, deduplicate its resolved classes, predicate properties, or
  resolved entities. Divide the number of unique terms across the benchmark by the sum of these
  per-query set sizes. An empty term type yields 0. Classes use the same explicit `rdf:type` and
  entity-type resolution rules as §1.3.

---

## 4. Complexity spread

These are per-query distributions rather than single numbers; the notebooks show them as
back-to-back histograms (or KDE curves) and additionally report the standard deviation of each.
Spread, not magnitude, is the point: a benchmark where every query returns exactly one row tests a
narrower range of engine behaviour than one whose result sizes vary.

### 4.1 Operator count per query

- **Definition:** how many distinct SPARQL constructs a single query combines.
- **Computation:** sum the binary feature flags of §1.5 for that query, excluding `SELECT` and
  `ASK` — these are query *forms* rather than structural operators, and every query has one, so
  including them would add a constant offset. Maximum possible value is therefore 11.
- **Reported scalar:** the population standard deviation of this count across the benchmark.

### 4.2 Output row count and column count per query

- **Definition:** the number of result rows and result columns each query actually returns when
  executed against the live endpoint.
- **Computation:** each query is normalised (§1.1) and executed, with up to 7 queries in flight
  concurrently. Rows is the length of the result list. Columns is the number of bindings in the
  first row; if the result is empty, the column count is recovered from the `head.vars` list of
  the raw SPARQL-JSON response instead, so a legitimately empty result still reports its arity.
  An `ASK` query — detected by the whole word `ASK` anywhere in the query — is recorded as 1 row
  and 1 column regardless of whether the answer was true or false.
- **Failure handling:** a query that errors, times out, or returns no result set is logged with
  its dataset, 1-based index, and endpoint, and is recorded as **0 rows and 0 columns**. These
  zeros are indistinguishable in the plots from a query that genuinely returned nothing, so a
  spike at zero should be checked against the warning log.
- **Caching:** successful (rows, cols) pairs are cached on disk keyed by endpoint plus query text.
  Failures are deliberately not treated as valid cache hits, so they are retried on the next run.
- **Disabled mode:** if no execution endpoint is supplied, both arrays are returned as all zeros
  and no network calls are made.
- **Reported scalars:** the population standard deviation of the row counts and of the column
  counts.
- **Plot caveat:** for display, output-row values are first clipped at the 95th percentile and
  then winsorised to 10 (the top bin is labelled "10+"); all three panels are drawn on a 0–12
  axis. The standard deviations above are computed on the *unclipped* data.

---

## 5. Comprehensiveness

The KG's vocabulary is read from per-KG YAML files under `kg-index/<kg>/classes.yaml` and
`properties.yaml` (with a legacy `kgs_data/` fallback). URIs in the RDF, RDFS, OWL, and XSD
namespaces are stripped from both lists, since those are meta-vocabulary rather than the KG's own
schema.

### 5.1 Class coverage

- **Definition:** the fraction of the KG's ontology classes that the benchmark exercises at least
  once, measured against the indexed schema in `classes.yaml`.
- **Computation:** pool the classes resolved from terms directly named in every query, intersect
  that pool with the indexed ontology class list, and divide by the size of that list. Report both
  a ratio and a raw `covered/total` string. The YAML index is an extracted schema snapshot, so its
  completeness bounds what this ratio means. Returns 0 when the ontology file is missing.

### 5.2 Property coverage

- **Definition:** the fraction of the indexed schema properties in `properties.yaml` used at least
  once.
- **Computation:** pool every predicate URI across all queries, intersect with the ontology
  property list (this removes `rdf:type` and similar), and divide by the size of that list.
  Reported as a ratio and as `covered/total`. The YAML index is an extracted schema snapshot, so
  its completeness bounds what this ratio means. Returns 0 when the ontology file is missing.

### 5.3 Feature coverage

- **Definition:** the fraction of the 13 tracked SPARQL features (§1.5) that the benchmark uses at
  least once anywhere. It is a *breadth* measure: a benchmark where one single query uses `HAVING`
  gets full credit for `HAVING`.
- **Computation:** union the set of features flagged across all queries and divide by 13. Reported
  as a ratio and as `used/13`.

### 5.4 Average new classes / properties per query

- **Definition:** a fallback pair of measures used when both benchmarks cover under 10 % of the
  KG's properties, where coverage ratios are all near zero and visually indistinguishable.
- **Computation:** the number of distinct ontology classes the benchmark touches divided by its
  query count, and likewise for properties. On the radar chart these replace the class- and
  property-coverage spokes.
- **Note:** despite the name, the numerator is the *total distinct* count for the benchmark, not a
  count of newly introduced terms in query order.

### 5.5 Coverage-gap table

Not a scalar metric but a diagnostic view: for classes and for properties separately, the terms
used only by benchmark A, only by benchmark B, and by neither. Each column shows a seeded random
sample (default 8 items, seed 42) with the full set size in the column header, and URIs are
shortened to a known prefix form or their last path/fragment segment.

### 5.6 Caching

Comprehensiveness results are cached on disk as a whole under the key `comprehensiveness_v4`;
pass `rewrite_cache=True` to recompute. Entity-type lookups dominate the cost, which is why the
whole pass is cached rather than individual steps.

---

## 6. Feature redundancy

**The question:** when a query uses a SPARQL feature, does that feature do any work? Remove or
weaken it, re-run, and see whether the answer changes. If it does not, the feature was decoration
and the query does not really test it.

Five features are probed, each with its own modification:

| Feature | Modification |
| --- | --- |
| `DISTINCT` | `SELECT DISTINCT` → `SELECT` |
| `FILTER` | every `FILTER(...)` clause deleted, found by balanced-parenthesis scanning so nested calls are removed whole |
| `OPTIONAL` | every `OPTIONAL { ... }` block deleted, found by balanced-brace scanning so nested groups are removed whole |
| `ORDER BY` | the `ORDER BY` clause deleted, up to the next `LIMIT` / `OFFSET` / `HAVING`, a closing brace, or end of query |
| `LIMIT` | `LIMIT N` → `LIMIT 2N` (not a deletion — doubling the cap reveals whether the original cap was actually binding) |

### Procedure

1. Normalise every query (§1.1) and compute its feature flags (§1.5).
2. For each query and each feature it uses, apply the modification. If the modified text is
   identical to the original after stripping whitespace, the pair is skipped entirely — it counts
   neither toward the denominator nor the numerator.
3. Cap the modified query's result size: if it has no `LIMIT`, append `LIMIT 100000`; if its
   `LIMIT` exceeds 100000, lower it to 100000. This prevents an unbounded result set after, say,
   deleting the only `FILTER` from a query. Note the cap is applied to the modified query only;
   the original is executed as written.
4. Execute the original and modified versions. All distinct query strings across the whole work
   list are deduplicated first, then executed with 2 concurrent workers, with every response
   cached on disk keyed by a hash of the query text. Failed responses *are* cached, so a run after
   an endpoint outage needs `rewrite_cache=True` to retry.
5. Compare results. Each row is reduced to a sorted tuple of (variable, value) pairs, and at most
   the first 100000 rows are compared. `None` rows are skipped with a message. For every feature
   except `ORDER BY`, the two result lists are compared as **sets**, so ordering and duplicate
   multiplicity are ignored. For `ORDER BY` they are compared as **ordered lists**, since order is
   exactly what that clause controls.
6. If either side failed to execute or returned no result set, the comparison returns "not equal",
   i.e. **execution failures are counted as non-redundant**. This biases redundancy rates
   downward when the endpoint is flaky.

### Reported values

- **Redundancy rate per feature** — of the queries that use the feature (and where the
  modification changed the text), the percentage whose results were unchanged by the
  modification. A feature used by zero queries reports 0 %.
- **Raw counts per feature** — `redundant / has`, annotated on each bar, so a 100 % rate backed by
  one query is visible as such.
- **Hatched bar overlay** — in the feature-distribution panel, each feature's bar can be split so
  that the redundant share is drawn with hatching, showing at a glance how much of the reported
  feature usage is doing real work.
- **Example browser** — `show_redundancy_examples` re-runs the same comparison and renders, per
  feature, syntax-highlighted redundant queries paired with their NL questions, so you can judge
  whether the question itself justified the feature. `DISTINCT` is excluded by default.
