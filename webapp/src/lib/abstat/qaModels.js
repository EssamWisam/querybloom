// Helpers for grouping stored QA questions by the LLM model that generated them.
// A model key is the trimmed model id, e.g. "openai/gpt-5.6-sol" or "openrouter/x/y".
// The empty key "" marks questions saved before model tracking existed.

export const UNRECORDED_MODEL = "";

export function normalizeModelKey(value) {
  return typeof value === "string" ? value.trim() : UNRECORDED_MODEL;
}

export function qaRowModelKey(row) {
  return normalizeModelKey(row?.metadata?.model);
}

export function modelLabel(key) {
  return key || "Model not recorded (saved before model tracking)";
}

export function modelFileSlug(key) {
  const slug = (key || "unrecorded")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || "unrecorded";
}

/**
 * Returns the stored QA result of each model for one subgraph, keyed by model.
 * Subgraphs written by the current backend carry `qa_results_by_model`.
 * Older subgraphs only have a single `qa_result`, which is its own model under UNRECORDED_MODEL.
 */
export function subgraphQaResultsByModel(subgraph) {
  const sources = [subgraph?.subgraph, subgraph?.payload, subgraph];
  const source = sources.find((s) => s && (s.qa_results_by_model || s.qa_result));
  if (!source) return {};
  if (source.qa_results_by_model && typeof source.qa_results_by_model === "object") {
    return { ...source.qa_results_by_model };
  }
  return { [UNRECORDED_MODEL]: source.qa_result };
}

/**
 * Re-keys the unrecorded (legacy) subgraph result to the model that produced it.
 * The result and its questions share `llm_run_id`, so the question row with the same
 * run id gives the model. `rowsForSubgraph` must include inactive rows, because a later
 * run may have replaced the questions that carry that id. If a named entry already
 * exists for that model, that entry is newer and wins, so the legacy one is dropped.
 */
export function attributeQaResults(resultsByModel, rowsForSubgraph) {
  const legacy = resultsByModel[UNRECORDED_MODEL];
  if (!legacy?.llm_run_id) return resultsByModel;
  const match = rowsForSubgraph.find(
    (row) => row?.metadata?.llm_run_id === legacy.llm_run_id,
  );
  if (!match) return resultsByModel;
  const key = qaRowModelKey(match);
  if (key === UNRECORDED_MODEL) return resultsByModel;
  const { [UNRECORDED_MODEL]: _legacy, ...rest } = resultsByModel;
  if (Object.hasOwn(rest, key)) return rest;
  return { ...rest, [key]: legacy };
}

/** True for rows that are not soft-deleted. Matches the filter in buildQaMapFromRows. */
export function qaRowIsActive(row) {
  const metadata = row?.metadata || {};
  return !metadata.deleted_at && metadata.active !== false;
}

export function orderedUnion(...lists) {
  const out = [];
  for (const list of lists) {
    for (const key of list) {
      if (!out.includes(key)) out.push(key);
    }
  }
  return out;
}

/**
 * Groups QA rows by model. `order` lists model keys by first appearance in `rows`.
 */
export function groupRowsByModel(rows) {
  const byModel = new Map();
  for (const row of rows ?? []) {
    const key = qaRowModelKey(row);
    if (!byModel.has(key)) byModel.set(key, []);
    byModel.get(key).push(row);
  }
  return { byModel, order: [...byModel.keys()] };
}

/**
 * Model keys to show as capsules: the selected model always, plus any other model that
 * has at least one question or a failed generation. A subgraph-level result with no
 * questions (for example "not meaningful") does not earn a capsule on its own.
 * `bucketsByModel` maps key -> qaMap-style object and must not contain the selected
 * model's live bucket (that one is `qaMap` in the component).
 */
export function capsuleModelKeys(order, selectedKey, bucketsByModel) {
  return order.filter((key) => {
    if (key === selectedKey) return true;
    const bucket = Object.hasOwn(bucketsByModel, key) ? bucketsByModel[key] : {};
    return Object.values(bucket).some(
      (entry) => (entry?.qa_pairs ?? []).length > 0 || entry?.status === "failed",
    );
  });
}
