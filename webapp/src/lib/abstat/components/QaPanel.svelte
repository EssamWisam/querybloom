<script>
  import hljs from "highlight.js";
  import { cancelRun, loadRunQaPairs, streamLlm } from "../api.js";
  import FieldHelp from "./FieldHelp.svelte";
  import MiniSubgraphGraphs from "./MiniSubgraphGraphs.svelte";
  import {
    normalizeGraph,
    shortName,
    SUBGRAPH_PALETTE,
    uriFallbackLabel,
  } from "../graph.js";

  export let token = null;
  export let endpoint = "";
  export let sampleRunId = "";
  export let subgraphs = [];
  export let defaults = null;

  $: llmFields = defaults?.ui?.llm?.fields ?? {};

  function fieldLabel(key, fallback) {
    return llmFields[key]?.label ?? fallback;
  }

  function fieldDescription(key, fallback) {
    return llmFields[key]?.description ?? fallback;
  }

  function statusLabel(status) {
    if (status === "generated") return "Drafted";
    return status;
  }

  const MODEL_OPTIONS = [
    "openai/gpt-5.6-sol",
    "openai/gpt-5.4",
    "openai/gpt-5.4-mini",
    "gemini/gemini-3.1-pro-preview",
    "gemini/gemini-3-flash-preview",
  ];

  let model = MODEL_OPTIONS[0];
  let verifyIterations = 0;
  let focusEntityQa = false;
  let entsRatio = 0.4;
  let additionalInstructions = "";
  let running = false;
  let hydratingQa = false;
  let error = "";
  let selectedIndex = null;
  let hydratedSampleRunId = null;
  let showSubgraphInspector = false;
  let expandedQuestions = {};
  let expandedEvolutions = {};
  let lastInspectorIndex = null;
  let subgraphSelectionKey = "";
  let selectedSubgraphIndexes = new Set();
  let runningIndexes = new Set();

  /**
   * @type {Record<number, {
   *   index: number,
   *   status: string,
   *   qa_pairs?: any[],
   *   is_meaningful?: boolean,
   *   error?: string
   * }>}
   */
  let qaMap = {};

  const ACTIVE_STATUSES = new Set([
    "pending",
    "generating",
    "generated",
    "complexity",
    "verifying",
    "verified",
    "rewording",
    "reworded",
  ]);

  $: qaList = subgraphs
    .map((sg) => ({
      index: sg.index,
      status: "ready",
      qa_pairs: [],
      ...(qaMap[sg.index] ?? {}),
    }))
    .sort((a, b) => a.index - b.index);
  $: subgraphByIndex = Object.fromEntries(subgraphs.map((s) => [s.index, s]));
  $: selected =
    selectedIndex != null
      ? {
          index: selectedIndex,
          status: "ready",
          qa_pairs: [],
          ...(qaMap[selectedIndex] ?? {}),
        }
      : null;
  $: selectedInfo =
    selectedIndex != null ? (subgraphByIndex[selectedIndex] ?? null) : null;
  $: if (selectedIndex !== lastInspectorIndex) {
    lastInspectorIndex = selectedIndex;
    showSubgraphInspector = false;
  }
  $: if (sampleRunId && sampleRunId !== hydratedSampleRunId && !running) {
    hydrateStoredQa(sampleRunId);
  }
  $: if (selectedIndex == null && subgraphs.length > 0) {
    selectedIndex = subgraphs[0].index;
  }
  $: currentSubgraphSelectionKey = subgraphs
    .map((sg) => sg.index)
    .sort((a, b) => a - b)
    .join(",");
  $: if (currentSubgraphSelectionKey !== subgraphSelectionKey) {
    subgraphSelectionKey = currentSubgraphSelectionKey;
    selectedSubgraphIndexes = new Set(subgraphs.map((sg) => sg.index));
  }
  $: selectedSubgraphCount = selectedSubgraphIndexes.size;
  $: exportRows = qaList.flatMap((sg) =>
    (sg.qa_pairs ?? []).map((pair) => ({
      subgraphId: displaySubgraphId(sg.index),
      text: pair.text_query ?? pair.question ?? "",
      query: pair.sparql_query ?? "",
    })),
  );

  function displaySubgraphId(index) {
    const info = subgraphByIndex[index];
    return info?.subgraph?.subgraph_id ?? info?.subgraph_id ?? index + 1;
  }

  function qaRowSubgraphIndex(row) {
    const metadata = row?.metadata || {};
    if (Number.isFinite(Number(metadata.subgraph_index))) {
      return Number(metadata.subgraph_index);
    }
    const match = subgraphs.find(
      (sg) => sg.dbId && sg.dbId === row?.subgraph_id,
    );
    return match ? match.index : null;
  }

  function buildQaMapFromRows(rows) {
    const restored = {};
    for (const row of rows ?? []) {
      const metadata = row?.metadata || {};
      if (metadata.deleted_at || metadata.active === false) continue;
      const index = qaRowSubgraphIndex(row);
      if (!Number.isFinite(index)) continue;
      const storedPair = metadata.qa_pair || {};
      const pair = {
        ...storedPair,
        id: row.id,
        question: row.question,
        sparql_query: row.sparql_query,
        execution_results: row.execution_result ?? storedPair.execution_results,
        verification_status:
          row.verification_status ?? storedPair.verification_status,
        metadata,
      };
      const entry = restored[index] ?? {
        index,
        status: "completed",
        qa_pairs: [],
      };
      entry.qa_pairs = [...entry.qa_pairs, pair];
      restored[index] = entry;
    }
    return restored;
  }

  async function hydrateStoredQa(runId, { force = false } = {}) {
    if (!token || !runId || hydratingQa) return;
    if (!force && runId === hydratedSampleRunId) return;
    hydratingQa = true;
    try {
      const rows = await loadRunQaPairs(token, runId);
      if (runId !== sampleRunId) return;
      qaMap = buildQaMapFromRows(rows);
      hydratedSampleRunId = runId;
    } catch (err) {
      console.warn("QA pair restore failed:", err);
      if (force) error = err?.message || "Could not reload generated pairs";
      hydratedSampleRunId = runId;
    } finally {
      hydratingQa = false;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function downloadExcel() {
    if (!exportRows.length) return;
    const rows = exportRows
      .map(
        (row) =>
          `<tr><td>${escapeHtml(row.subgraphId)}</td><td>${escapeHtml(
            row.text,
          )}</td><td>${escapeHtml(row.query)}</td></tr>`,
      )
      .join("");
    const html = `<!doctype html><html><head><meta charset="utf-8"></head><body><table><thead><tr><th>subgraph id</th><th>text</th><th>query</th></tr></thead><tbody>${rows}</tbody></table></body></html>`;
    const blob = new Blob([html], {
      type: "application/vnd.ms-excel;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `querybloom-text-query-${sampleRunId || Date.now()}.xls`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function typeLabels(entry) {
    if (!entry) return [];
    const samplesTypes = entry.samples?.types ?? {};
    if (Object.keys(samplesTypes).length > 0) {
      return Object.keys(samplesTypes).map(
        (uri) => uriFallbackLabel(uri) || shortName(uri) || uri,
      );
    }
    const raw = entry.subgraph?.types ?? [];
    if (Array.isArray(raw))
      return raw.map((uri) => uriFallbackLabel(uri) || shortName(uri) || uri);
    if (raw && typeof raw === "object") {
      return Object.keys(raw).map(
        (uri) => uriFallbackLabel(uri) || shortName(uri) || uri,
      );
    }
    return [];
  }

  function parseAttrs(str) {
    if (!str) return [];
    const inner = str.replace(/^\(|\)$/g, "");
    const re = /([^,=]+):([^=]+)=('(?:[^']|'')*'|[^,]+)/g;
    const entries = [];
    let match;
    while ((match = re.exec(inner)) !== null) {
      const label = match[1].trim();
      const datatype = shortName(match[2].trim()) || "literal";
      let value = match[3].trim();
      if (value.startsWith("'") && value.endsWith("'"))
        value = value.slice(1, -1);
      value = shortName(value) || value;
      entries.push({ label, datatype, value });
    }
    return entries;
  }

  function embeddedSamplePayload(entry) {
    const types = entry?.subgraph?.types;
    if (!types || Array.isArray(types) || typeof types !== "object")
      return null;
    const hasSampleEntities = Object.values(types).some((typeEntry) =>
      Array.isArray(typeEntry?.sample_entities),
    );
    return hasSampleEntities ? entry.subgraph : null;
  }

  function samplePayload(entry) {
    return entry?.samples || entry?.sampleData || embeddedSamplePayload(entry);
  }

  function samplesFor(entry) {
    return samplePayload(entry)?.types || {};
  }

  function labelMapFor(entry) {
    const map = new Map();
    const graphData = normalizeGraph(entry?.graph);
    for (const node of graphData.nodes) {
      map.set(
        node.data.uri || node.data.id,
        node.data.label ||
          uriFallbackLabel(node.data.id) ||
          shortName(node.data.id),
      );
    }
    for (const edge of graphData.edges) {
      const predicate = edge.data.predicate || edge.data.uri;
      if (predicate)
        map.set(
          predicate,
          edge.data.label ||
            uriFallbackLabel(predicate) ||
            shortName(predicate),
        );
    }
    for (const [typeName, typeData] of Object.entries(samplesFor(entry))) {
      if (typeData?.uri) map.set(typeData.uri, typeName);
    }
    return map;
  }

  function displayUri(uri, labels) {
    return (
      labels.get(uri) || uriFallbackLabel(uri) || shortName(uri) || uri || "-"
    );
  }

  function displayEntity(entity, fallback = "?") {
    return (
      entity?.label || uriFallbackLabel(entity?.uri) || entity?.uri || fallback
    );
  }

  function parseReadableEdge(edge) {
    if (typeof edge !== "string") return null;
    const match = edge.match(/^(.+?)\s+--(.+?)\s+-->(\*)?\s+(.+)$/);
    if (!match) return null;
    return {
      source: match[1].trim(),
      label: match[2].trim(),
      target: match[4].trim(),
      optional: Boolean(match[3]),
      readable: edge,
    };
  }

  function normalizeSubgraphEdge(edge, labels, readableEdge = null) {
    const readable = parseReadableEdge(readableEdge) || parseReadableEdge(edge);
    if (Array.isArray(edge)) {
      const [sourceUri, uri, targetUri] = edge;
      return {
        uri,
        label: displayUri(uri, labels),
        sourceUri,
        targetUri,
        source: displayUri(sourceUri, labels),
        target: displayUri(targetUri, labels),
        support: null,
        optional: false,
        readable: readableEdge || null,
      };
    }
    if (edge && typeof edge === "object") {
      const sourceUri = edge.s || edge.source;
      const uri = edge.p || edge.predicate || edge.uri;
      const targetUri = edge.o || edge.target;
      return {
        uri,
        label: uri ? displayUri(uri, labels) : readable?.label || "-",
        sourceUri,
        targetUri,
        source: sourceUri
          ? displayUri(sourceUri, labels)
          : readable?.source || "-",
        target: targetUri
          ? displayUri(targetUri, labels)
          : readable?.target || "-",
        support: edge.support,
        optional: Boolean(edge.is_optional || readable?.optional),
        readable: readableEdge || readable?.readable || null,
      };
    }
    if (readable) {
      return {
        uri: null,
        label: readable.label,
        sourceUri: null,
        targetUri: null,
        source: readable.source,
        target: readable.target,
        support: null,
        optional: readable.optional,
        readable: readable.readable,
      };
    }
    return null;
  }

  function sampleBucket(typeData, key, uri) {
    if (key && typeData[key]) return typeData[key];
    if (uri) {
      const match = Object.values(typeData).find((entry) => entry?.uri === uri);
      if (match) return match;
    }
    return null;
  }

  function attributeUriForLabel(attributeUris, label) {
    const normalize = (value) =>
      String(value)
        .toLowerCase()
        .replace(/[^a-z0-9]/g, "");
    const normalizedLabel = normalize(label);
    return attributeUris.find((uri) => {
      const name = shortName(uri);
      return normalize(name) === normalizedLabel;
    });
  }

  function subgraphProperties(entry) {
    const labels = labelMapFor(entry);
    const rawEdges = entry?.subgraph?.edges || [];
    const readableEdges = samplePayload(entry)?.edges || [];
    const edges = rawEdges.length ? rawEdges : readableEdges;
    return edges
      .map((edge, index) =>
        normalizeSubgraphEdge(edge, labels, readableEdges[index]),
      )
      .filter(Boolean);
  }

  function subgraphAttributes(entry) {
    const labels = labelMapFor(entry);
    const samples = samplePayload(entry);
    const rows = [];
    const byType = entry?.subgraph?.type_attributes || {};
    for (const [typeUri, attrs] of Object.entries(byType)) {
      for (const attr of attrs || []) {
        rows.push({
          typeUri,
          typeLabel: displayUri(typeUri, labels),
          uri: attr.property,
          label: attr.property_label || displayUri(attr.property, labels),
          datatype:
            attr.datatype_label || shortName(attr.datatype) || "literal",
          support: attr.support,
        });
      }
    }
    const attributeUris = samples?.attribute_uris || [];
    for (const [typeName, typeData] of Object.entries(samplesFor(entry))) {
      const typeUri = typeData?.uri || null;
      for (const entity of typeData?.sample_entities || []) {
        for (const attr of parseAttrs(entity?.attributes)) {
          const uri =
            attributeUriForLabel(attributeUris, attr.label) || attr.label;
          const exists = rows.some(
            (row) => row.typeUri === typeUri && row.label === attr.label,
          );
          if (!exists) {
            rows.push({
              typeUri,
              typeLabel: typeUri ? displayUri(typeUri, labels) : typeName,
              uri,
              label: displayUri(uri, labels) || attr.label,
              datatype: attr.datatype || "literal",
            });
          }
        }
      }
    }
    return rows;
  }

  function buildSamples(entry) {
    const typeData = samplesFor(entry);
    const props = subgraphProperties(entry);
    const allLists = Object.values(typeData).map(
      (typeEntry) => typeEntry?.sample_entities || [],
    );
    const count = allLists.length
      ? Math.min(...allLists.map((list) => list.length))
      : 0;
    const shown = Math.min(count, 3);
    const instances = [];

    for (let index = 0; index < shown; index += 1) {
      const triples = props.map((prop) => {
        const srcEnt = sampleBucket(typeData, prop.source, prop.sourceUri)
          ?.sample_entities?.[index];
        const tgtEnt = sampleBucket(typeData, prop.target, prop.targetUri)
          ?.sample_entities?.[index];
        return {
          src: displayEntity(srcEnt),
          prop: prop.label,
          tgt: displayEntity(tgtEnt),
          optional: prop.optional,
          kind: "triple",
        };
      });

      const attrLines = [];
      for (const [typeName, typeEntry] of Object.entries(typeData)) {
        const entity = typeEntry?.sample_entities?.[index];
        if (entity?.attributes) {
          const src = displayEntity(entity, typeName);
          for (const attr of parseAttrs(entity.attributes)) {
            attrLines.push({
              src,
              prop: attr.label,
              tgt: attr.value,
              kind: "attr-triple",
            });
          }
        }
      }

      instances.push({ triples: [...triples, ...attrLines] });
    }

    if (!props.length && count === 0) {
      const fallback = [];
      for (const [typeName, typeEntry] of Object.entries(typeData)) {
        for (const entity of (typeEntry?.sample_entities || []).slice(0, 3)) {
          fallback.push({
            src: displayEntity(entity),
            prop: typeName,
            tgt: null,
            optional: false,
          });
        }
      }
      if (fallback.length) instances.push({ triples: fallback });
    }

    return instances;
  }

  function questionKey(subgraphIndex, qaIndex) {
    return `${subgraphIndex}:${qaIndex}`;
  }

  function toggleQuestion(key) {
    expandedQuestions = {
      ...expandedQuestions,
      [key]: !expandedQuestions[key],
    };
  }

  function toggleEvolution(key) {
    expandedEvolutions = {
      ...expandedEvolutions,
      [key]: !expandedEvolutions[key],
    };
  }

  function executionCount(result) {
    if (Array.isArray(result)) return result.length;
    if (typeof result?.count === "number") return result.count;
    if (Array.isArray(result?.results)) return result.results.length;
    if (Array.isArray(result?.result_preview?.rows))
      return result.result_preview.rows.length;
    return 0;
  }

  function executionError(result) {
    return result?.error_message || result?.error || null;
  }

  function executionPreview(result) {
    if (!result) return null;
    if (result?.result_preview?.columns && result?.result_preview?.rows) {
      return result.result_preview;
    }
    if (Array.isArray(result)) {
      const first = result[0];
      if (!first || typeof first !== "object") return null;
      return {
        columns: Object.keys(first),
        rows: result.slice(0, 5),
      };
    }
    if (Array.isArray(result?.results)) {
      const first = result.results[0];
      if (!first || typeof first !== "object") return null;
      return {
        columns: Object.keys(first),
        rows: result.results.slice(0, 5),
      };
    }
    return null;
  }

  function previewCell(row, column) {
    const value = row?.[column];
    if (value == null || value === "") return "—";
    if (typeof value === "object") {
      if ("value" in value) return value.value;
      return JSON.stringify(value);
    }
    return String(value);
  }

  function sameSnapshot(left, right) {
    return (
      (left?.question ?? "") === (right?.question ?? "") &&
      (left?.sparql ?? "") === (right?.sparql ?? "")
    );
  }

  function pairEvolutionStages(pair) {
    const stages = [];
    const generated = {
      label: "Generate",
      agent: "Generator",
      question: pair.original_question ?? pair.question ?? "",
      sparql: pair.original_sparql_query ?? pair.sparql_query ?? "",
      note: null,
    };
    stages.push(generated);

    if (
      pair.pre_verify_question ||
      pair.pre_verify_sparql_query ||
      pair.complexity_types?.length
    ) {
      const complexity = {
        label: "Complexity",
        agent: "Complexity agent",
        question: pair.pre_verify_question ?? pair.question ?? "",
        sparql: pair.pre_verify_sparql_query ?? pair.sparql_query ?? "",
        note: pair.complexity_types?.length
          ? `Added ${pair.complexity_types.join(", ")}`
          : null,
      };
      if (!sameSnapshot(complexity, generated) || complexity.note)
        stages.push(complexity);
    }

    if (
      pair.verification_status ||
      pair.verification_reason ||
      pair.pre_reword_question
    ) {
      const verified = {
        label: "Verify",
        agent: "Verifier",
        question: pair.pre_reword_question ?? pair.question ?? "",
        sparql: pair.sparql_query ?? pair.pre_verify_sparql_query ?? "",
        note:
          pair.verification_reason ||
          (pair.verification_status
            ? `Status: ${pair.verification_status}`
            : null),
      };
      if (!sameSnapshot(verified, stages[stages.length - 1]) || verified.note)
        stages.push(verified);
    }

    const finalStage = {
      label:
        pair.pre_reword_question || pair.reword_reason ? "Reword" : "Final",
      agent:
        pair.pre_reword_question || pair.reword_reason
          ? "Reword agent"
          : "Stored result",
      question: pair.question ?? "",
      sparql: pair.sparql_query ?? "",
      note: pair.reword_reason || null,
    };
    if (
      !sameSnapshot(finalStage, stages[stages.length - 1]) ||
      finalStage.note ||
      stages.length === 1
    ) {
      stages.push(finalStage);
    }

    return stages;
  }

  $: selectedPatternProperties = selectedInfo
    ? subgraphProperties(selectedInfo)
    : [];
  $: selectedPatternAttributes = selectedInfo
    ? subgraphAttributes(selectedInfo)
    : [];
  $: selectedSamples = selectedInfo ? buildSamples(selectedInfo) : [];

  function highlightSparql(query) {
    if (!query) return "";
    try {
      return hljs.highlight(query, { language: "sql", ignoreIllegals: true })
        .value;
    } catch {
      return hljs.highlightAuto(query).value;
    }
  }

  function updateSubgraph(index, patch) {
    if (index == null) return;
    qaMap = { ...qaMap, [index]: { ...(qaMap[index] ?? { index }), ...patch } };
  }

  function updatePair(index, qaIndex, pairPatch) {
    if (index == null) return;
    const entry = qaMap[index] ?? { index };
    const pairs = [...(entry.qa_pairs ?? [])];
    if (!pairs[qaIndex]) pairs[qaIndex] = {};
    pairs[qaIndex] = { ...pairs[qaIndex], ...pairPatch };
    qaMap = { ...qaMap, [index]: { ...entry, qa_pairs: pairs } };
  }

  function addFrame(frame) {
    const data = frame.data ?? {};
    const payload = data.data ?? {};
    const event = frame.event;
    const stage = data.stage;
    const index = payload.subgraph_index ?? payload.index;

    if (event === "subgraph.started") {
      updateSubgraph(index, { status: "pending" });
      if (selectedIndex == null) selectedIndex = index;
    } else if (event === "stage.started" && stage === "llm.generate") {
      updateSubgraph(index, { status: "generating" });
    } else if (event === "stage.completed" && stage === "llm.generate") {
      // Seed qa_pairs immediately from the generated questions
      const questions = payload.questions ?? [];
      const pairs = questions.map((q) => ({
        question: q.text_query ?? q.question,
        sparql_query: q.sparql_query,
      }));
      updateSubgraph(index, {
        status: "generated",
        is_meaningful: payload.is_meaningful,
        qa_pairs: pairs,
      });
    } else if (event === "stage.started" && stage === "sparql.execute") {
      // Seed the pair with question/sparql so it appears while executing
      const i = payload.qa_index;
      if (i != null)
        updatePair(index, i, {
          question: payload.question,
          sparql_query: payload.sparql_query,
        });
    } else if (event === "stage.completed" && stage === "sparql.execute") {
      const i = payload.qa_index;
      if (i != null)
        updatePair(index, i, { execution_results: payload.execution_results });
    } else if (event === "stage.started" && stage === "llm.complexity") {
      updateSubgraph(index, { status: "complexity" });
    } else if (event === "stage.completed" && stage === "llm.complexity") {
      const augmentations = payload.augmentations ?? [];
      const entry = qaMap[index];
      if (entry) {
        const pairs = [...(entry.qa_pairs ?? [])];
        augmentations.forEach((aug, i) => {
          if (aug.skipped || !pairs[i]) return;
          pairs[i] = {
            ...pairs[i],
            question: aug.augmented_text_query ?? pairs[i].question,
            sparql_query: aug.augmented_sparql_query ?? pairs[i].sparql_query,
            complexity_types: aug.complexity_types,
          };
        });
        updateSubgraph(index, { status: "generated", qa_pairs: pairs });
      }
    } else if (event === "stage.started" && stage === "llm.verify") {
      updateSubgraph(index, { status: "verifying" });
    } else if (event === "stage.completed" && stage === "llm.verify") {
      const verPairs = payload.verification?.pairs ?? [];
      const entry = qaMap[index];
      if (entry) {
        const pairs = [...(entry.qa_pairs ?? [])];
        verPairs.forEach((vp, i) => {
          if (!pairs[i]) return;
          pairs[i] = {
            ...pairs[i],
            verification_status: vp.status,
            verification_reason: vp.reason,
          };
        });
        updateSubgraph(index, { status: "verified", qa_pairs: pairs });
      }
    } else if (event === "stage.started" && stage === "llm.reword") {
      updateSubgraph(index, { status: "rewording" });
    } else if (event === "stage.completed" && stage === "llm.reword") {
      const rwPairs = payload.pairs ?? [];
      const entry = qaMap[index];
      if (entry) {
        const pairs = [...(entry.qa_pairs ?? [])];
        rwPairs.forEach((rw, i) => {
          if (
            !pairs[i] ||
            rw.status !== "needs_reword" ||
            !rw.reworded_text_query
          )
            return;
          pairs[i] = {
            ...pairs[i],
            pre_reword_question: pairs[i].question,
            question: rw.reworded_text_query,
            reword_reason: rw.reason,
          };
        });
        updateSubgraph(index, { status: "reworded", qa_pairs: pairs });
      }
    } else if (event === "subgraph.completed") {
      // Final state — use streamed qa_pairs already built, just mark completed
      const result = payload.result ?? payload;
      const entry = qaMap[index];
      // Prefer the final result's qa_pairs (most complete) but fall back to streamed
      updateSubgraph(index, {
        status: "completed",
        is_meaningful: result.is_meaningful,
        qa_pairs: result.qa_pairs?.length
          ? result.qa_pairs
          : (entry?.qa_pairs ?? []),
      });
    } else if (event === "subgraph.failed") {
      updateSubgraph(index, {
        status: "failed",
        error: payload.error ?? payload.message ?? "Pipeline failed",
      });
    }
  }

  function setSubgraphSelected(index, selected) {
    const next = new Set(selectedSubgraphIndexes);
    if (selected) next.add(index);
    else next.delete(index);
    selectedSubgraphIndexes = next;
  }

  function selectAllSubgraphs() {
    selectedSubgraphIndexes = new Set(qaList.map((sg) => sg.index));
  }

  function clearSubgraphSelection() {
    selectedSubgraphIndexes = new Set();
  }

  function selectedGenerationIndexes() {
    return qaList
      .filter((sg) => selectedSubgraphIndexes.has(sg.index))
      .map((sg) => sg.index);
  }

  function generatedSelectionCount(indexes) {
    return indexes.filter((index) => (qaMap[index]?.qa_pairs ?? []).length > 0)
      .length;
  }

  let activeAbortController = null;

  async function cancelGeneration() {
    if (activeAbortController) {
      activeAbortController.abort();
      activeAbortController = null;
    }
    if (sampleRunId && token) {
      await cancelRun(token, sampleRunId).catch(() => {});
    }
    running = false;
    runningIndexes = new Set();
    await hydrateStoredQa(sampleRunId, { force: true });
  }

  async function generateSubgraphs(indexes) {
    const requested = [...new Set(indexes.map(Number))].filter(Number.isFinite);
    if (!requested.length) return;
    error = "";
    running = true;
    runningIndexes = new Set(requested);
    selectedIndex = requested[0];
    let nextQaMap = { ...qaMap };
    for (const index of requested) {
      nextQaMap[index] = { index, status: "scheduled", qa_pairs: [] };
    }
    qaMap = nextQaMap;
    activeAbortController = new AbortController();

    try {
      await streamLlm(
        token,
        {
          title: `QueryBloom QA: ${endpoint}`,
          request: {
            sample_run_id: sampleRunId,
            endpoint,
            model,
            subgraph_indices: requested,
            verify_iterations: Number(verifyIterations),
            focus_entity_qa: focusEntityQa,
            ents_ratio: Number(entsRatio),
            additional_instructions: additionalInstructions,
            introduce_complexity_step: true,
            reword_questions_step: true,
          },
        },
        addFrame,
        activeAbortController.signal,
      );
      await hydrateStoredQa(sampleRunId, { force: true });
    } catch (err) {
      if (err?.name !== "AbortError" && !String(err?.message || "").includes("aborted")) {
        error = err?.message || "QA generation failed";
      }
      await hydrateStoredQa(sampleRunId, { force: true });
    } finally {
      running = false;
      runningIndexes = new Set();
      activeAbortController = null;
    }
  }

  async function generateSelectedSubgraphs() {
    const requested = selectedGenerationIndexes();
    if (!requested.length) return;
    const generatedCount = generatedSelectionCount(requested);
    if (
      generatedCount > 0 &&
      !confirm(
        `${generatedCount} selected subgraph${generatedCount === 1 ? " has" : "s have"} existing QA. Regenerate and overwrite them?`,
      )
    ) {
      return;
    }
    await generateSubgraphs(requested);
  }

  async function submit() {
    await generateSelectedSubgraphs();
  }
</script>

<section class="qa-panel">
  <!-- Form bar -->
  <form on:submit|preventDefault={submit}>
    <div class="form-head">
      <h2>QA generation</h2>
      {#if sampleRunId}
        <p>
          Run <code>{sampleRunId}</code> via
          <code>{endpoint || "sampling endpoint"}</code>
        </p>
      {:else}
        <p class="warn">Run sampling first to enable QA generation.</p>
      {/if}
    </div>
    <div class="grid">
      <label>
        <span class="label-row">
          <span class="label-text">{fieldLabel("model", "Model")}</span>
          <FieldHelp
            description={fieldDescription(
              "model",
              "LiteLLM model identifier used by the generation, complexity, verifier, and rewording agents.",
            )}
          />
        </span>
        <select bind:value={model}>
          {#each MODEL_OPTIONS as option}
            <option value={option}>{option}</option>
          {/each}
        </select>
      </label>
      <label>
        <span class="label-row">
          <span class="label-text"
            >{fieldLabel("verify_iterations", "Verify iterations")}</span
          >
          <FieldHelp
            description={fieldDescription(
              "verify_iterations",
              "How many verifier repair cycles to run. Use 0 to skip verification.",
            )}
          />
        </span>
        <input bind:value={verifyIterations} type="number" min="0" />
      </label>
      <label>
        <span class="label-row">
          <span class="label-text"
            >{fieldLabel("ents_ratio", "Entity sample ratio")}</span
          >
          <FieldHelp
            description={fieldDescription(
              "ents_ratio",
              "Fraction of sampled entities from each subgraph shown to the LLM as examples.",
            )}
          />
        </span>
        <input
          bind:value={entsRatio}
          type="number"
          min="0.05"
          max="1"
          step="0.05"
        />
      </label>
      <label class="checkbox-field">
        <span class="label-row">
          <span class="label-text"
            >{fieldLabel("focus_entity_qa", "Entity-focused QA")}</span
          >
          <FieldHelp
            description={fieldDescription(
              "focus_entity_qa",
              "Bias generation toward questions about concrete sample entities instead of only schema-level relations.",
            )}
          />
        </span>
        <input bind:checked={focusEntityQa} type="checkbox" />
      </label>
      <label class="full-field">
        <span class="label-row">
          <span class="label-text"
            >{fieldLabel(
              "additional_instructions",
              "Additional instructions",
            )}</span
          >
          <FieldHelp
            description={fieldDescription(
              "additional_instructions",
              "Optional extra prompt guidance appended to the generator, complexity, and verifier agents.",
            )}
          />
        </span>
        <textarea
          bind:value={additionalInstructions}
          rows="3"
          placeholder="Optional extra prompt guidance"
        ></textarea>
      </label>
    </div>
    {#if error}<p class="error">{error}</p>{/if}
    <div class="form-actions">
      {#if running}
        <button class="danger-btn" type="button" on:click={cancelGeneration}>
          Cancel Generation
        </button>
      {:else}
        <button
          type="submit"
          disabled={!token || !sampleRunId || !selectedSubgraphCount}
        >
          Generate {selectedSubgraphCount} selected
        </button>
      {/if}
      <button
        class="secondary-action"
        type="button"
        disabled={running ||
          !qaList.length ||
          selectedSubgraphCount === qaList.length}
        on:click={selectAllSubgraphs}>Select all</button
      >
      <button
        class="secondary-action"
        type="button"
        disabled={running || !selectedSubgraphCount}
        on:click={clearSubgraphSelection}>Clear all</button
      >
      <button
        class="secondary-action"
        type="button"
        disabled={!exportRows.length}
        on:click={downloadExcel}>Download Excel</button
      >
      {#if hydratingQa}<span class="restore-note">Loading saved questions…</span
        >{/if}
    </div>
  </form>

  <!-- Workspace: list + detail -->
  {#if qaList.length > 0}
    <div class="workspace">
      <!-- Left: subgraph list -->
      <aside class="sg-list">
        {#each qaList as sg (sg.index)}
          {@const info = subgraphByIndex[sg.index]}
          {@const types = typeLabels(info)}
          <article
            class="sg-card"
            class:active={selectedIndex === sg.index}
            class:selected-for-generation={selectedSubgraphIndexes.has(
              sg.index,
            )}
          >
            <button
              class="sg-select"
              type="button"
              on:click={() => (selectedIndex = sg.index)}
            >
              <div class="sg-card-top">
                <span class="sg-index">
                  <span
                    class="sg-dot"
                    style="background:{SUBGRAPH_PALETTE[
                      sg.index % SUBGRAPH_PALETTE.length
                    ]}"
                    aria-hidden="true"
                  ></span>
                  Subgraph {displaySubgraphId(sg.index)}
                </span>
                <span class="pill pill-{sg.status}">
                  {#if ACTIVE_STATUSES.has(sg.status)}<span
                      class="pulse"
                      aria-hidden="true"
                    ></span>{/if}
                  {statusLabel(sg.status)}
                </span>
              </div>
              {#if types.length > 0}
                <div class="chips">
                  {#each types.slice(0, 3) as t}<span class="chip">{t}</span
                    >{/each}
                  {#if types.length > 3}<span class="chip more"
                      >+{types.length - 3}</span
                    >{/if}
                </div>
              {:else}
                <p class="no-type">No type info</p>
              {/if}
            </button>
            <label
              class="sg-check"
              title="Select for batch generation"
              aria-label={`Select subgraph ${displaySubgraphId(sg.index)} for generation`}
            >
              <input
                type="checkbox"
                checked={selectedSubgraphIndexes.has(sg.index)}
                disabled={running}
                on:change={(event) =>
                  setSubgraphSelected(sg.index, event.currentTarget.checked)}
              />
            </label>
          </article>
        {/each}
      </aside>

      <!-- Right: detail pane -->
      <div class="sg-detail">
        {#if selected == null}
          <p class="empty-hint">Select a subgraph to see details.</p>
        {:else}
          <header class="detail-head">
            <h3>Subgraph {displaySubgraphId(selected.index)}</h3>
            <span class="pill pill-{selected.status}"
              >{statusLabel(selected.status)}</span
            >
          </header>

          <!-- Subgraph info from sampling run -->
          {#if selectedInfo}
            {@const types = typeLabels(selectedInfo)}
            <div class="info-box">
              <div class="info-row">
                <span class="info-label">Types</span>
                <div class="chips">
                  {#each types as t}<span class="chip">{t}</span>{/each}
                  {#if types.length === 0}<span class="muted">—</span>{/if}
                </div>
              </div>
              {#if selectedInfo.subgraph?.edges?.length}
                <div class="info-row">
                  <span class="info-label">Patterns</span>
                  <span class="muted"
                    >{selectedInfo.subgraph.edges.length} edge pattern{selectedInfo
                      .subgraph.edges.length !== 1
                      ? "s"
                      : ""}</span
                  >
                </div>
              {/if}
              {#if selectedInfo.support}
                <div class="info-row">
                  <span class="info-label">Support</span>
                  <span class="muted">{selectedInfo.support}</span>
                </div>
              {/if}
            </div>

            <div class="detail-actions">
              <button
                class="inspector-toggle"
                type="button"
                on:click={() =>
                  (showSubgraphInspector = !showSubgraphInspector)}
              >
                {showSubgraphInspector
                  ? "Hide pattern and samples"
                  : "Show pattern and samples"}
              </button>
            </div>

            {#if showSubgraphInspector}
              <section class="inspector-card">
                <MiniSubgraphGraphs
                  properties={selectedPatternProperties}
                  attributes={selectedPatternAttributes}
                  samples={selectedSamples}
                  idPrefix={`qa-${selectedInfo.index}`}
                  emptySamplesText={samplePayload(selectedInfo)
                    ? "No samples could be formed for this subgraph."
                    : "Sample entities will appear once mining completes."}
                />
              </section>
            {/if}
          {/if}

          <!-- State-specific content -->
          {#if selected.status === "failed"}
            <p class="error detail-error">
              {selected.error ?? "Pipeline failed"}
            </p>
          {:else if selected.is_meaningful === false}
            <p class="not-meaningful">
              LLM determined this subgraph does not yield meaningful questions.
            </p>
          {:else}
            {@const pairs = selected.qa_pairs ?? []}
            {#if pairs.length === 0 && (selected.status === "pending" || selected.status === "generating")}
              <p class="empty-hint">Processing…</p>
            {:else if pairs.length === 0 && selected.status === "scheduled"}
              <p class="empty-hint">Waiting to start.</p>
            {:else if pairs.length === 0 && selected.status === "ready"}
              <p class="empty-hint">
                No questions generated for this subgraph yet.
              </p>
            {:else if pairs.length === 0}
              <p class="empty-hint">No questions generated.</p>
            {:else}
              <ol class="qa-list">
                {#each pairs as pair, i}
                  {@const key = questionKey(selected.index, i)}
                  {@const preview = executionPreview(pair.execution_results)}
                  {@const evolution = pairEvolutionStages(pair)}
                  <li
                    class="qa-item"
                    class:expanded={expandedQuestions[key] ||
                      expandedEvolutions[key]}
                  >
                    <div class="qa-summary">
                      <button
                        class="qa-toggle"
                        type="button"
                        on:click={() => toggleQuestion(key)}
                        aria-expanded={expandedQuestions[key]
                          ? "true"
                          : "false"}
                      >
                        <span class="qa-chevron"
                          >{expandedQuestions[key] ? "▾" : "▸"}</span
                        >
                        <span class="question"
                          >{pair.text_query ??
                            pair.question ??
                            "(no question)"}</span
                        >
                      </button>
                      <div class="qa-summary-actions">
                        <div class="badges">
                          {#if pair.execution_results != null}
                            {#if pair.execution_results === false || executionError(pair.execution_results)}
                              <span class="badge badge-fail">✗ no results</span>
                            {:else}
                              <span class="badge badge-ok"
                                >✓ {executionCount(pair.execution_results)} result{executionCount(
                                  pair.execution_results,
                                ) !== 1
                                  ? "s"
                                  : ""}</span
                              >
                            {/if}
                          {/if}
                          {#if pair.verification_status}
                            <span
                              class="badge badge-{pair.verification_status ===
                              'correct'
                                ? 'ok'
                                : pair.verification_status === 'needs_fix'
                                  ? 'warn'
                                  : 'neutral'}">{pair.verification_status}</span
                            >
                          {/if}
                          {#if pair.complexity_types?.length}
                            <span class="badge badge-neutral"
                              >{pair.complexity_types.join(", ")}</span
                            >
                          {/if}
                        </div>
                        <button
                          class="evolution-toggle"
                          type="button"
                          on:click={() => toggleEvolution(key)}
                          aria-expanded={expandedEvolutions[key]
                            ? "true"
                            : "false"}
                        >
                          {expandedEvolutions[key]
                            ? "Hide evolution"
                            : "Show evolution"}
                        </button>
                      </div>
                    </div>

                    {#if expandedQuestions[key]}
                      <div class="qa-body">
                        {#if pair.sparql_query}
                          <div class="qa-section">
                            <span class="section-label">SPARQL</span>
                            <pre class="sparql"><code class="hljs language-sql"
                                >{@html highlightSparql(
                                  pair.sparql_query,
                                )}</code
                              ></pre>
                          </div>
                        {/if}

                        {#if pair.execution_results != null}
                          <div class="qa-section">
                            <span class="section-label">Output</span>
                            <div class="result-panel">
                              <div class="result-meta">
                                <span class="badge badge-neutral"
                                  >count {executionCount(
                                    pair.execution_results,
                                  )}</span
                                >
                                {#if executionError(pair.execution_results)}
                                  <span class="badge badge-fail"
                                    >{executionError(
                                      pair.execution_results,
                                    )}</span
                                  >
                                {/if}
                              </div>
                              {#if preview?.rows?.length}
                                <div class="result-table-wrap">
                                  <table class="result-table">
                                    <thead>
                                      <tr>
                                        {#each preview.columns as column}
                                          <th>{column}</th>
                                        {/each}
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {#each preview.rows as row}
                                        <tr>
                                          {#each preview.columns as column}
                                            <td>{previewCell(row, column)}</td>
                                          {/each}
                                        </tr>
                                      {/each}
                                    </tbody>
                                  </table>
                                </div>
                              {:else if !executionError(pair.execution_results)}
                                <p class="empty-hint compact">
                                  No preview rows returned.
                                </p>
                              {/if}
                            </div>
                          </div>
                        {/if}
                      </div>
                    {/if}

                    {#if expandedEvolutions[key]}
                      <div class="qa-body qa-evolution-body">
                        <div class="qa-section">
                          <span class="section-label">Evolution</span>
                          <ol class="evolution-list">
                            {#each evolution as stage, stageIndex}
                              <li class="evolution-step">
                                <div class="evolution-head">
                                  <div>
                                    <strong
                                      >{stageIndex + 1}. {stage.label}</strong
                                    >
                                    <span class="muted evolution-agent"
                                      >{stage.agent}</span
                                    >
                                  </div>
                                  {#if stage.note}
                                    <span class="badge badge-neutral">note</span
                                    >
                                  {/if}
                                </div>
                                {#if stage.note}
                                  <p class="evolution-note">{stage.note}</p>
                                {/if}
                                <div class="evolution-block">
                                  <span class="evolution-label">Text</span>
                                  <p class="evolution-text">
                                    {stage.question || "—"}
                                  </p>
                                </div>
                                {#if stage.sparql}
                                  <div class="evolution-block">
                                    <span class="evolution-label">SPARQL</span>
                                    <pre class="sparql"><code
                                        class="hljs language-sql"
                                        >{@html highlightSparql(
                                          stage.sparql,
                                        )}</code
                                      ></pre>
                                  </div>
                                {/if}
                              </li>
                            {/each}
                          </ol>
                        </div>
                      </div>
                    {/if}
                  </li>
                {/each}
              </ol>
            {/if}
          {/if}
        {/if}
      </div>
    </div>
  {:else if running}
    <p class="start-hint">Starting QA pipeline…</p>
  {:else}
    <p class="start-hint">
      Mine or restore subgraphs first, then generate text-query pairs here.
    </p>
  {/if}
</section>

<style>
  /* ── Layout ─────────────────────────────────────────── */
  .qa-panel {
    height: 100%;
    display: grid;
    grid-template-rows: auto 1fr;
    min-height: 0;
  }

  form {
    display: grid;
    gap: 12px;
    padding: 16px;
    border-bottom: 1px solid var(--border-default);
    background: #fff;
  }

  .workspace {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    min-height: 0;
    overflow: hidden;
  }

  /* ── Form ────────────────────────────────────────────── */
  .form-head {
    display: flex;
    align-items: baseline;
    gap: 12px;
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    color: var(--color-uni-dark-blue);
    font-size: 1rem;
  }

  .form-head p,
  .form-head p code {
    color: #66708a;
    font-size: 0.8rem;
  }

  .form-head p code {
    border-radius: 4px;
    background: #f4f6fb;
    padding: 1px 5px;
    color: #242c49;
  }

  .warn {
    color: #b06200 !important;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }

  label {
    display: grid;
    gap: 5px;
  }

  .label-row {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }

  .label-text {
    color: #66708a;
    font-size: 0.77rem;
    font-weight: 800;
    text-transform: uppercase;
  }

  input,
  select {
    width: 100%;
    border: 1px solid #d8deed;
    border-radius: 6px;
    padding: 8px 9px;
    font: inherit;
    font-size: 0.88rem;
  }

  textarea {
    width: 100%;
    min-height: 76px;
    resize: vertical;
    border: 1px solid #d8deed;
    border-radius: 6px;
    padding: 8px 9px;
    font: inherit;
    font-size: 0.88rem;
  }

  .checkbox-field {
    align-content: start;
  }

  .full-field {
    grid-column: 1 / -1;
  }

  .checkbox-field input {
    width: auto;
    margin-top: 7px;
    justify-self: start;
    accent-color: var(--color-uni-blue);
  }

  .form-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
  }

  button[type="submit"] {
    justify-self: flex-start;
    border: 0;
    border-radius: 6px;
    padding: 9px 13px;
    background: var(--color-uni-blue);
    color: #fff;
    cursor: pointer;
    font-weight: 800;
    font-size: 0.88rem;
  }

  .danger-btn {
    border: 0;
    border-radius: 6px;
    padding: 9px 13px;
    background: #e53e3e;
    color: #fff;
    cursor: pointer;
    font-weight: 800;
    font-size: 0.88rem;
    transition: background 0.15s ease;
  }

  .danger-btn:hover {
    background: #c53030;
  }

  button[type="submit"]:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .secondary-action {
    border: 1px solid #d8deed;
    border-radius: 6px;
    background: #fff;
    color: #2e3d72;
    cursor: pointer;
    padding: 8px 12px;
    font-size: 0.85rem;
    font-weight: 800;
  }

  .secondary-action:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .restore-note {
    color: #66708a;
    font-size: 0.8rem;
    font-weight: 700;
  }

  .error {
    color: var(--color-uni-red);
    font-size: 0.82rem;
    margin: 0;
  }

  /* ── Subgraph list ───────────────────────────────────── */
  .sg-list {
    overflow-y: auto;
    border-right: 1px solid var(--border-default);
    padding: 10px 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    background: #f9fafd;
  }

  .sg-card {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    width: 100%;
    text-align: left;
    border: 1px solid #e2e7f2;
    border-radius: 8px;
    background: #fff;
    padding: 9px 10px;
    transition:
      border-color 0.12s,
      box-shadow 0.12s;
  }

  .sg-select {
    width: 100%;
    min-width: 0;
    display: grid;
    gap: 6px;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    text-align: left;
    cursor: pointer;
    font: inherit;
  }

  .sg-select:hover {
    background: transparent;
  }

  .sg-card:hover {
    border-color: var(--color-uni-blue);
  }

  .sg-card.selected-for-generation {
    border-color: #9fb1e8;
    background: #f7f9ff;
  }

  .sg-card.active {
    border-color: var(--color-uni-blue);
    box-shadow: 0 0 0 2px
      color-mix(in srgb, var(--color-uni-blue) 18%, transparent);
    background: #f0f4ff;
  }

  .sg-card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }

  .sg-check {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border: 1px solid #d8deed;
    border-radius: 6px;
    background: #fff;
    cursor: pointer;
  }

  .sg-check:hover {
    border-color: var(--color-uni-blue);
    background: #f0f4ff;
  }

  .sg-check input {
    width: auto;
    margin: 0;
    accent-color: var(--color-uni-blue);
  }

  .sg-index {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 0.8rem;
    font-weight: 700;
    color: #3a4260;
    min-width: 0;
  }

  .sg-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  /* ── Status pills ────────────────────────────────────── */
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border-radius: 20px;
    padding: 2px 8px;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    white-space: nowrap;
  }

  .pill-scheduled {
    background: #f0f1f5;
    color: #7a829e;
  }
  .pill-ready {
    background: #eef1fa;
    color: #68728f;
  }
  .pill-pending {
    background: #edf2ff;
    color: #3d5af1;
  }
  .pill-generating {
    background: #e8f4ff;
    color: #0070cc;
  }
  .pill-generated {
    background: #e8f4ff;
    color: #0070cc;
  }
  .pill-verifying {
    background: #fef3e6;
    color: #b06200;
  }
  .pill-verified {
    background: #edfcf0;
    color: #1a8a3a;
  }
  .pill-rewording {
    background: #fef3e6;
    color: #b06200;
  }
  .pill-reworded {
    background: #edfcf0;
    color: #1a8a3a;
  }
  .pill-completed {
    background: #edfcf0;
    color: #1a7a30;
  }
  .pill-failed {
    background: #fdeeed;
    color: #c0392b;
  }

  /* Animated pulse dot for active states */
  .pulse {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
    animation: blink 1.1s ease-in-out infinite;
  }

  @keyframes blink {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.2;
    }
  }

  /* ── Type chips ──────────────────────────────────────── */
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .chip {
    border-radius: 4px;
    background: #eef1fa;
    padding: 1px 6px;
    font-size: 0.73rem;
    color: #3a4a7a;
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chip.more {
    background: #dfe3f0;
    color: #5a6490;
  }

  .no-type {
    color: #aab2cc;
    font-size: 0.75rem;
    margin: 0;
  }

  /* ── Detail pane ─────────────────────────────────────── */
  .sg-detail {
    overflow-y: auto;
    padding: 16px 18px 24px;
  }

  .detail-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
  }

  h3 {
    color: var(--color-uni-dark-blue);
    font-size: 0.95rem;
  }

  .info-box {
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    background: #f9fafd;
    padding: 10px 14px;
    margin-bottom: 14px;
    display: grid;
    gap: 8px;
  }

  .detail-actions {
    margin-bottom: 14px;
  }

  .inspector-toggle,
  .evolution-toggle,
  .qa-toggle {
    border: 1px solid #d8deed;
    border-radius: 6px;
    background: #fff;
    color: #2e3d72;
    cursor: pointer;
    font: inherit;
  }

  .inspector-toggle,
  .evolution-toggle {
    padding: 7px 10px;
    font-size: 0.8rem;
    font-weight: 700;
  }

  .inspector-card {
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    background: #f9fafd;
    padding: 12px 14px;
    margin-bottom: 16px;
    display: grid;
    gap: 16px;
  }

  .evolution-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .compact {
    padding: 0;
  }

  .info-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  .info-label {
    font-size: 0.76rem;
    font-weight: 800;
    text-transform: uppercase;
    color: #8892af;
    min-width: 70px;
    padding-top: 2px;
  }

  .muted {
    color: #8892af;
    font-size: 0.82rem;
  }

  .not-meaningful {
    color: #8a6000;
    font-size: 0.85rem;
    background: #fffbeb;
    border: 1px solid #f0d070;
    border-radius: 6px;
    padding: 10px 12px;
    margin: 0;
  }

  .detail-error {
    background: #fff5f5;
    border: 1px solid #f8c8c8;
    border-radius: 6px;
    padding: 10px 12px;
  }

  /* ── QA list ─────────────────────────────────────────── */
  .qa-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 14px;
  }

  .qa-item {
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    background: #fff;
    padding: 13px 14px;
    display: grid;
    gap: 10px;
  }

  .qa-item.expanded {
    border-color: #ccd6ee;
    box-shadow: 0 8px 20px rgba(26, 45, 94, 0.05);
  }

  .qa-summary {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    justify-content: space-between;
  }

  .qa-toggle {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 0;
    border: 0;
    background: transparent;
    text-align: left;
    flex: 1 1 auto;
    min-width: 0;
  }

  .qa-chevron {
    display: inline-grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border: 1px solid #d8deed;
    border-radius: 6px;
    background: #f8faff;
    color: #66708a;
    font-size: 1.55rem;
    line-height: 1;
    flex: 0 0 auto;
  }

  .qa-summary-actions {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .qa-body {
    display: grid;
    gap: 14px;
  }

  .qa-section {
    display: grid;
    gap: 8px;
  }

  .section-label,
  .evolution-label {
    color: #66708a;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .question {
    font-size: 0.9rem;
    color: #1c2543;
    margin: 0;
    font-weight: 500;
  }

  .sparql {
    margin: 0;
    border-radius: 6px;
    background: #f4f6fb;
    padding: 10px 11px;
    overflow-x: auto;
  }

  .sparql code {
    font-size: 0.78rem;
    white-space: pre;
  }

  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }

  .result-panel {
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    background: #f9fafd;
    padding: 10px 12px;
    display: grid;
    gap: 10px;
  }

  .result-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .result-table-wrap {
    overflow-x: auto;
  }

  .result-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
    background: #fff;
  }

  .result-table th,
  .result-table td {
    border: 1px solid #e4e8f4;
    padding: 7px 8px;
    text-align: left;
    vertical-align: top;
  }

  .result-table th {
    background: #eef1fa;
    color: #334269;
    font-weight: 700;
  }

  .evolution-list {
    display: grid;
    gap: 12px;
  }

  .evolution-step {
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    background: #f9fafd;
    padding: 12px;
    display: grid;
    gap: 10px;
  }

  .evolution-head {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: flex-start;
  }

  .evolution-agent {
    display: block;
    margin-top: 2px;
  }

  .evolution-note,
  .evolution-text {
    margin: 0;
    color: #334269;
    font-size: 0.82rem;
  }

  .evolution-block {
    display: grid;
    gap: 6px;
  }

  .badge {
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 0.72rem;
    font-weight: 600;
  }

  .badge-ok {
    background: #edfcf0;
    color: #1a7a30;
  }
  .badge-fail {
    background: #fdeeed;
    color: #c0392b;
  }
  .badge-warn {
    background: #fef3e6;
    color: #a05800;
  }
  .badge-neutral {
    background: #eef1fa;
    color: #3a4a7a;
  }

  /* ── Empty / hint states ─────────────────────────────── */
  .empty-hint,
  .start-hint {
    color: #8892af;
    font-size: 0.85rem;
    margin: 0;
  }

  .start-hint {
    padding: 20px 18px;
  }

  .empty-hint {
    padding: 16px 0;
  }

  @media (max-width: 920px) {
    .grid {
      grid-template-columns: 1fr 1fr;
    }

    .workspace {
      grid-template-columns: 1fr;
      grid-template-rows: auto 1fr;
    }

    .sg-list {
      border-right: none;
      border-bottom: 1px solid var(--border-default);
      max-height: 200px;
    }

    .qa-summary {
      flex-direction: column;
    }

    .qa-summary-actions {
      justify-content: flex-start;
    }
  }
</style>
