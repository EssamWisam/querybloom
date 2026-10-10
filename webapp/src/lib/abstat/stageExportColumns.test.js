import assert from "node:assert/strict";
import test from "node:test";
import { stageExportColumns } from "./stageExportColumns.js";

const generated = {
  original_question: "Who wrote the book?",
  original_sparql_query: "SELECT ?a WHERE { ?a a :Author }",
};

test("fills every stage when each one changed the pair", () => {
  const columns = stageExportColumns({
    ...generated,
    question: "Which authors wrote a book?",
    sparql_query: "SELECT ?a WHERE { ?a a :Author . ?a :wrote ?b }",
    pre_verify_question: "Who wrote a published book?",
    pre_verify_sparql_query: "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
    pre_reword_question: "Which person wrote a published book?",
    verification_status: "correct",
    verification_status_by_cycle: ["needs_fix", "correct"],
    stage_outputs: {
      generate: {
        text_query: generated.original_question,
        sparql_query: generated.original_sparql_query,
      },
      complexity: {
        skipped: false,
        augmented_text_query: "Who wrote a published book?",
        augmented_sparql_query:
          "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
      },
      verify: { status: "correct", fixed_text_query: null, fixed_sparql_query: null },
      reword: {
        status: "needs_reword",
        reworded_text_query: "Which authors wrote a book?",
      },
    },
  });

  assert.deepEqual(columns, {
    generated_text: "Who wrote the book?",
    generated_sparql: "SELECT ?a WHERE { ?a a :Author }",
    augmented_text: "Who wrote a published book?",
    augmented_sparql: "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
    verified_text: "Which person wrote a published book?",
    verified_sparql: "SELECT ?a WHERE { ?a a :Author . ?a :wrote ?b }",
    reworded_text: "Which authors wrote a book?",
  });
});

test("leaves later stages empty when they did not change the pair", () => {
  const columns = stageExportColumns({
    ...generated,
    question: generated.original_question,
    sparql_query: generated.original_sparql_query,
    pre_verify_question: generated.original_question,
    pre_verify_sparql_query: generated.original_sparql_query,
    verification_status: "correct",
    stage_outputs: {
      complexity: { skipped: true, augmented_text_query: null, augmented_sparql_query: null },
      verify: { status: "correct", fixed_text_query: null, fixed_sparql_query: null },
      reword: { status: "clean", reworded_text_query: null },
    },
  });

  assert.equal(columns.generated_text, generated.original_question);
  assert.equal(columns.generated_sparql, generated.original_sparql_query);
  assert.equal(columns.augmented_text, null);
  assert.equal(columns.augmented_sparql, null);
  assert.equal(columns.verified_text, null);
  assert.equal(columns.verified_sparql, null);
  assert.equal(columns.reworded_text, null);
});

test("reconstructs older runs that have no stage_outputs", () => {
  const columns = stageExportColumns({
    ...generated,
    question: "Which writers are known for the book?",
    sparql_query: "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
    pre_verify_question: "Who wrote a published book?",
    pre_verify_sparql_query: "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
    pre_reword_question: "Who wrote a published book?",
    verification_status: "correct",
    complexity_types: ["FILTER"],
  });

  assert.equal(columns.augmented_text, "Who wrote a published book?");
  assert.equal(
    columns.augmented_sparql,
    "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
  );
  assert.equal(columns.verified_text, null);
  assert.equal(columns.verified_sparql, null);
  assert.equal(columns.reworded_text, "Which writers are known for the book?");
});

test("uses the final verification pair when an earlier cycle applied the fix", () => {
  const columns = stageExportColumns({
    ...generated,
    question: "Who wrote the published book?",
    sparql_query: "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
    pre_verify_question: generated.original_question,
    pre_verify_sparql_query: generated.original_sparql_query,
    verification_status: "correct",
    verification_status_by_cycle: ["needs_fix", "correct"],
    stage_outputs: {
      verify: { status: "correct", reason: "", fixed_text_query: null, fixed_sparql_query: null },
    },
  });

  assert.equal(columns.augmented_text, null);
  assert.equal(columns.verified_text, "Who wrote the published book?");
  assert.equal(
    columns.verified_sparql,
    "SELECT ?a WHERE { ?a a :Author . ?a :published ?b }",
  );
  assert.equal(columns.reworded_text, null);
});

test("keeps both augmented columns when only the question changed", () => {
  const columns = stageExportColumns({
    ...generated,
    question: "Which author wrote the book?",
    sparql_query: generated.original_sparql_query,
    complexity_types: ["FILTER"],
  });

  assert.equal(columns.augmented_text, "Which author wrote the book?");
  assert.equal(columns.augmented_sparql, generated.original_sparql_query);
  assert.equal(columns.verified_text, null);
  assert.equal(columns.reworded_text, null);
});

test("returns nulls when the pair has no stage snapshots", () => {
  assert.deepEqual(
    stageExportColumns({ question: "Final?", sparql_query: "SELECT ?a WHERE { ?a ?b ?c }" }),
    {
      generated_text: null,
      generated_sparql: null,
      augmented_text: null,
      augmented_sparql: null,
      verified_text: null,
      verified_sparql: null,
      reworded_text: null,
    },
  );
});
