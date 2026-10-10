/** Columns appended to a QA download when per-stage snapshots are requested. */
export const STAGE_EXPORT_COLUMNS = [
  "generated_text",
  "generated_sparql",
  "augmented_text",
  "augmented_sparql",
  "verified_text",
  "verified_sparql",
  "reworded_text",
];

function presentText(value) {
  if (value == null) return null;
  const text = String(value);
  return text.length ? text : null;
}

function pairChanged(next, prevText, prevSparql) {
  if (next == null) return false;
  const textDiff =
    prevText != null && next.text != null && next.text !== prevText;
  const sparqlDiff =
    prevSparql != null && next.sparql != null && next.sparql !== prevSparql;
  return textDiff || sparqlDiff;
}

function verificationRan(pair) {
  if (pair?.stage_outputs?.verify) return true;
  if (pair?.verification_status) return true;
  if (pair?.pre_verify_question != null || pair?.pre_verify_sparql_query != null)
    return true;
  return (
    Array.isArray(pair?.verification_status_by_cycle) &&
    pair.verification_status_by_cycle.length > 0
  );
}

/**
 * Pair immediately after augmentation.
 * Returns null when that snapshot was not stored separately from generation.
 */
function postAugmentationPair(pair, generatedText, generatedSparql) {
  const complexity = pair?.stage_outputs?.complexity;
  if (complexity) {
    if (complexity.skipped) return { text: generatedText, sparql: generatedSparql };
    return {
      text: presentText(complexity.augmented_text_query) ?? generatedText,
      sparql: presentText(complexity.augmented_sparql_query) ?? generatedSparql,
    };
  }

  // Saved before stage_outputs existed. pre_verify_* is the pair entering
  // verification, which is the post-augmentation pair.
  if (pair?.pre_verify_question != null || pair?.pre_verify_sparql_query != null) {
    return {
      text: presentText(pair.pre_verify_question) ?? generatedText,
      sparql: presentText(pair.pre_verify_sparql_query) ?? generatedSparql,
    };
  }

  if (verificationRan(pair)) return null;

  // Verification never ran, so the question rewording saw and the stored
  // SPARQL are still the post-augmentation pair.
  const textBeforeReword =
    presentText(pair?.pre_reword_question) ??
    presentText(pair?.question) ??
    presentText(pair?.text_query);
  const sparql = presentText(pair?.sparql_query);
  const markedChanged =
    Array.isArray(pair?.complexity_types) && pair.complexity_types.length > 0;
  const snapshot = { text: textBeforeReword ?? generatedText, sparql: sparql ?? generatedSparql };
  if (markedChanged || pairChanged(snapshot, generatedText, generatedSparql)) return snapshot;
  return null;
}

/** Final pair after the verification loop, before rewording. */
function postVerificationPair(pair) {
  if (!verificationRan(pair)) return null;
  const sparql =
    presentText(pair?.sparql_query) ?? presentText(pair?.pre_verify_sparql_query);
  const text =
    presentText(pair?.pre_reword_question) ??
    presentText(pair?.question) ??
    presentText(pair?.text_query) ??
    presentText(pair?.pre_verify_question);
  if (text == null && sparql == null) return null;
  return { text, sparql };
}

function rewordedText(pair, afterVerify) {
  const reword = pair?.stage_outputs?.reword;
  const fromStage =
    reword?.status === "needs_reword" ? presentText(reword.reworded_text_query) : null;
  const previous = presentText(pair?.pre_reword_question);
  const fromStored =
    previous != null && presentText(pair?.question) !== previous
      ? presentText(pair?.question)
      : null;
  const next = fromStage ?? fromStored;
  if (next == null) return null;
  const baseline = previous ?? afterVerify?.text ?? null;
  if (baseline != null && next === baseline) return null;
  return next;
}

/**
 * Per-stage question and SPARQL for one saved QA pair.
 * A stage that left the pair unchanged contributes nulls.
 * Verification is the pair after the last cycle, not each intermediate fix.
 */
export function stageExportColumns(pair) {
  const generate = pair?.stage_outputs?.generate;
  const generatedText =
    presentText(generate?.text_query) ?? presentText(pair?.original_question);
  const generatedSparql =
    presentText(generate?.sparql_query) ?? presentText(pair?.original_sparql_query);

  const afterAug = postAugmentationPair(pair, generatedText, generatedSparql);
  const augChanged = pairChanged(afterAug, generatedText, generatedSparql);

  const afterVerify = postVerificationPair(pair);
  const baseline = augChanged
    ? afterAug
    : generatedText != null || generatedSparql != null
      ? { text: generatedText, sparql: generatedSparql }
      : afterAug;
  const verifyChanged = pairChanged(afterVerify, baseline?.text, baseline?.sparql);

  return {
    generated_text: generatedText,
    generated_sparql: generatedSparql,
    augmented_text: augChanged ? afterAug.text : null,
    augmented_sparql: augChanged ? afterAug.sparql : null,
    verified_text: verifyChanged ? afterVerify.text : null,
    verified_sparql: verifyChanged ? afterVerify.sparql : null,
    reworded_text: rewordedText(pair, afterVerify),
  };
}
