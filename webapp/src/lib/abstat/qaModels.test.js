import assert from "node:assert/strict";
import test from "node:test";
import {
  UNRECORDED_MODEL,
  attributeQaResults,
  capsuleModelKeys,
  groupRowsByModel,
  modelFileSlug,
  orderedUnion,
  qaRowIsActive,
  qaRowModelKey,
  subgraphQaResultsByModel,
} from "./qaModels.js";

test("qaRowModelKey trims the stored model and falls back to unrecorded", () => {
  assert.equal(qaRowModelKey({ metadata: { model: " openai/gpt-5.6-sol " } }), "openai/gpt-5.6-sol");
  assert.equal(qaRowModelKey({ metadata: {} }), UNRECORDED_MODEL);
  assert.equal(qaRowModelKey({ metadata: { model: null } }), UNRECORDED_MODEL);
  assert.equal(qaRowModelKey(undefined), UNRECORDED_MODEL);
});

test("groupRowsByModel keeps first-seen model order", () => {
  const rows = [
    { id: 1, metadata: { model: "a" } },
    { id: 2, metadata: { model: "b" } },
    { id: 3, metadata: { model: "a" } },
  ];
  const { byModel, order } = groupRowsByModel(rows);
  assert.deepEqual(order, ["a", "b"]);
  assert.deepEqual(byModel.get("a").map((r) => r.id), [1, 3]);
});

test("subgraphQaResultsByModel reads per-model results", () => {
  const subgraph = {
    payload: {
      qa_result: { status: "completed", llm_run_id: "r2" },
      qa_results_by_model: {
        a: { status: "completed", llm_run_id: "r1" },
        b: { status: "completed", llm_run_id: "r2" },
      },
    },
  };
  assert.deepEqual(Object.keys(subgraphQaResultsByModel(subgraph)), ["a", "b"]);
});

test("subgraphQaResultsByModel files a legacy qa_result under the unrecorded key", () => {
  const legacy = { payload: { qa_result: { status: "completed" } } };
  assert.deepEqual(subgraphQaResultsByModel(legacy), {
    [UNRECORDED_MODEL]: { status: "completed" },
  });
  assert.deepEqual(subgraphQaResultsByModel({ payload: {} }), {});
});

test("capsuleModelKeys keeps the selected model and other models with questions or failures", () => {
  const buckets = {
    a: {},
    b: { 0: { qa_pairs: [{}] } },
    // A "not meaningful" result has no questions, so it does not earn a capsule.
    c: { 0: { status: "completed", is_meaningful: false, qa_pairs: [] } },
    d: { 0: { status: "failed", qa_pairs: [] } },
  };
  assert.deepEqual(
    capsuleModelKeys(["a", "b", "c", "d", "sel"], "sel", buckets),
    ["b", "d", "sel"],
  );
  assert.deepEqual(capsuleModelKeys(["a"], "a", buckets), ["a"]);
});

test("attributeQaResults re-keys a legacy result to the model of its matching run", () => {
  const legacy = { status: "completed", is_meaningful: false, llm_run_id: "run-1" };
  const rows = [
    { metadata: { llm_run_id: "run-2", model: "openrouter/x/y" } },
    { metadata: { llm_run_id: "run-1", model: "openai/gpt-5.6-sol" } },
  ];
  assert.deepEqual(attributeQaResults({ [UNRECORDED_MODEL]: legacy }, rows), {
    "openai/gpt-5.6-sol": legacy,
  });
});

test("attributeQaResults keeps the legacy key when no row matches", () => {
  const legacy = { status: "completed", llm_run_id: "run-9" };
  const input = { [UNRECORDED_MODEL]: legacy };
  assert.deepEqual(attributeQaResults(input, []), input);
});

test("attributeQaResults drops the legacy result when a named entry already exists", () => {
  const newer = { status: "completed", llm_run_id: "run-2" };
  const legacy = { status: "completed", llm_run_id: "run-1" };
  const rows = [{ metadata: { llm_run_id: "run-1", model: "m1" } }];
  assert.deepEqual(
    attributeQaResults({ [UNRECORDED_MODEL]: legacy, m1: newer }, rows),
    { m1: newer },
  );
});

test("qaRowIsActive rejects soft-deleted and inactive rows", () => {
  assert.equal(qaRowIsActive({ metadata: { active: true } }), true);
  assert.equal(qaRowIsActive({ metadata: {} }), true);
  assert.equal(qaRowIsActive({ metadata: { active: false } }), false);
  assert.equal(qaRowIsActive({ metadata: { deleted_at: "2026-01-01" } }), false);
});

test("orderedUnion dedupes while keeping first occurrence", () => {
  assert.deepEqual(orderedUnion(["a", "b"], ["b", "c", "a"]), ["a", "b", "c"]);
});

test("modelFileSlug makes model ids safe for filenames", () => {
  assert.equal(modelFileSlug("openrouter/anthropic/claude-sonnet-4.5"), "openrouter_anthropic_claude-sonnet-4.5");
  assert.equal(modelFileSlug(""), "unrecorded");
});
