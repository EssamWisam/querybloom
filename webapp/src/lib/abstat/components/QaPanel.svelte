<script>
  import hljs from "highlight.js";
  import { cancelRun, formatCaughtError, loadRunQaPairs, reportBrowserError, streamLlm } from "../api.js";
  import FieldHelp from "./FieldHelp.svelte";
  import QaPatternSamplesModal from "./QaPatternSamplesModal.svelte";
  import QaEvolution from "./QaEvolution.svelte";
  import {
    normalizeGraph,
    shortName,
    SUBGRAPH_PALETTE,
    uriFallbackLabel,
  } from "../graph.js";
  import {
    displayEntity,
    isV5Subgraph,
    parseAttrs,
    parseRelationshipLine,
    samplePayload,
    v5Attributes,
    v5Properties,
    v5Samples,
  } from "../subgraphYaml.js";

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

  function formatCost(cost) {
    if (cost == null || isNaN(Number(cost))) return "";
    const num = Number(cost);
    if (num === 0) return "$0.00";
    if (num < 0.0001) return "< $0.0001";
    if (num < 0.01) return `$${num.toFixed(4)}`;
    return `$${num.toFixed(3)}`;
  }

  function costTooltip(entry) {
    if (!entry) return "";
    const cost = entry.cost_usd;
    const usage = entry.llm_usage;
    let text = "";
    if (cost != null && !isNaN(Number(cost))) {
      text = `Estimated LLM Cost: $${Number(cost).toFixed(6)}`;
    }
    if (usage && typeof usage === "object") {
      const tokens =
        usage.total_tokens ??
        ((usage.prompt_tokens || 0) + (usage.completion_tokens || 0));
      if (tokens) {
        text += `${text ? " • " : ""}Tokens: ${Number(tokens).toLocaleString()}`;
        if (usage.prompt_tokens || usage.completion_tokens) {
          text += ` (Prompt: ${(usage.prompt_tokens || 0).toLocaleString()}, Completion: ${(usage.completion_tokens || 0).toLocaleString()})`;
        }
      }
    }
    return text;
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
  let errorModalMessage = null;
  let errorModalDetails = null;

  function showErrorModal(message, details = "") {
    errorModalMessage = message;
    errorModalDetails = details;
  }

  function closeErrorModal() {
    errorModalMessage = null;
    errorModalDetails = null;
  }

  let showExportModal = false;
  let exportFormat = "yaml";
  let exportQuerySelection = "all";
  let exportIncludeValidReason = false;
  let exportIgnoreNoResults = true;
  let exportIgnoreNeedsFix = false;

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
   * @type {Record<number, any>}
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

  $: qaList = (() => {
    const seen = new Set();
    const list = [];
    for (const sg of subgraphs) {
      const idx = Number.isFinite(Number(sg?.index)) ? Number(sg.index) : 0;
      if (seen.has(idx)) continue;
      seen.add(idx);
      list.push({
        index: idx,
        status: "ready",
        qa_pairs: [],
        ...(qaMap[idx] ?? qaMap[sg?.index] ?? {}),
      });
    }
    return list.sort((a, b) => a.index - b.index);
  })();
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
  $: totalSelectedGeneratedPairs = qaList
    .filter((sg) => selectedSubgraphIndexes.has(sg.index))
    .reduce((sum, sg) => sum + (sg.qa_pairs?.length || 0), 0);

  $: allExportRows = showExportModal
    ? qaList
        .filter((sg) => selectedSubgraphIndexes.has(sg.index))
        .flatMap((sg) =>
          (sg.qa_pairs ?? []).map((pair) => {
            const count = executionCount(pair.execution_results);
            const hasResults =
              count > 0 ||
              typeof pair.execution_results === "boolean" ||
              typeof pair.execution_results?.boolean === "boolean";
            const isNeedsFix = pair.verification_status === "needs_fix";
            const isValid = getPairValid(pair);
            const reason = getPairReason(pair);
            const snippet = formatResultSnippet(pair.execution_results, 3);
            const llmBest = getPairLlmBest(pair);

            return {
              src_id: displaySubgraphId(sg.index),
              text: pair.text_query ?? pair.question ?? "",
              query: pair.sparql_query ?? "",
              llm_best: llmBest,
              result_count: count,
              result_snippet: snippet,
              valid: isValid,
              reason,
              hasResults,
              isNeedsFix,
            };
          }),
        )
    : [];

  $: filteredExportRows = showExportModal
    ? qaList
        .filter((sg) => selectedSubgraphIndexes.has(sg.index))
        .flatMap((sg) => {
          const pairRows = (sg.qa_pairs ?? []).map((pair) => {
            const count = executionCount(pair.execution_results);
            const hasResults =
              count > 0 ||
              typeof pair.execution_results === "boolean" ||
              typeof pair.execution_results?.boolean === "boolean";
            const isNeedsFix = pair.verification_status === "needs_fix";
            const isValid = getPairValid(pair);
            const reason = getPairReason(pair);
            const snippet = formatResultSnippet(pair.execution_results, 3);
            const llmBest = getPairLlmBest(pair);

            return {
              src_id: displaySubgraphId(sg.index),
              text: pair.text_query ?? pair.question ?? "",
              query: pair.sparql_query ?? "",
              llm_best: llmBest,
              result_count: count,
              result_snippet: snippet,
              valid: isValid,
              reason,
              hasResults,
              isNeedsFix,
            };
          });

          const eligible = pairRows.filter((row) => {
            if (exportIgnoreNoResults && !row.hasResults) return false;
            if (exportIgnoreNeedsFix && row.isNeedsFix) return false;
            return true;
          });

          if (!eligible.length) return [];

          if (exportQuerySelection === "best") {
            const best = eligible.find((r) => r.llm_best) || eligible[0];
            return [best];
          }

          if (exportQuerySelection === "random") {
            const idx = Math.abs((sg.index * 1103515245 + 12345) % eligible.length);
            return [eligible[idx]];
          }

          return eligible;
        })
    : [];

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
        stage_outputs: storedPair.stage_outputs ?? row.stage_outputs ?? null,
        metadata,
      };
      const costUsd =
        metadata.cost_usd ??
        metadata.subgraph_cost_usd ??
        metadata.llm_usage?.total_cost_usd ??
        storedPair.cost_usd ??
        null;
      const llmUsage = metadata.llm_usage ?? storedPair.llm_usage ?? null;
      const entry = restored[index] ?? {
        index,
        status: "completed",
        cost_usd: costUsd,
        llm_usage: llmUsage,
        qa_pairs: [],
      };
      if (entry.cost_usd == null && costUsd != null) {
        entry.cost_usd = costUsd;
      }
      if (entry.llm_usage == null && llmUsage != null) {
        entry.llm_usage = llmUsage;
      }
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
      const restored = buildQaMapFromRows(rows);
      const merged = { ...restored };
      for (const [idxStr, entry] of Object.entries(qaMap)) {
        if (entry.status === "failed") {
          merged[Number(idxStr)] = entry;
        }
      }
      qaMap = merged;
      hydratedSampleRunId = runId;
    } catch (err) {
      console.warn("QA pair restore failed:", err);
      if (force) error = err?.message || "Could not reload generated pairs";
      hydratedSampleRunId = runId;
    } finally {
      hydratingQa = false;
    }
  }

  function formatYamlBlockScalar(str, indent = 4) {
    const prefix = " ".repeat(indent);
    const normalized = String(str ?? "")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .trimEnd();
    if (!normalized) return ' ""';
    const lines = normalized.split("\n");
    return (
      " |\n" + lines.map((l) => (l.length > 0 ? prefix + l : "")).join("\n")
    );
  }

  function buildYamlString(rows, includeValidReason) {
    const entries = rows.map((r, idx) => {
      const questionId = idx + 1;
      const lines = [
        `- id: ${questionId}`,
        `  src_id: ${JSON.stringify(r.src_id)}`,
        `  text: ${JSON.stringify(r.text)}`,
        `  query:${formatYamlBlockScalar(r.query, 4)}`,
        `  llm_best: ${r.llm_best ? "true" : '""'}`,
        `  result_count: ${r.result_count}`,
        `  result_snippet:${formatYamlBlockScalar(r.result_snippet, 4)}`,
      ];
      if (includeValidReason) {
        lines.push('  valid: ""');
        lines.push('  reason: ""');
      }
      return lines.join("\n");
    });
    return entries.join("\n") + "\n";
  }

  function csvEscape(value) {
    if (value == null) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    const str = String(value);
    if (
      str.includes(",") ||
      str.includes('"') ||
      str.includes("\n") ||
      str.includes("\r")
    ) {
      return `"${str.replaceAll('"', '""')}"`;
    }
    return str;
  }

  function buildCsvString(rows, includeValidReason) {
    const headers = [
      "id",
      "src_id",
      "text",
      "query",
      "llm_best",
      "result_count",
      "result_snippet",
    ];
    if (includeValidReason) {
      headers.push("valid", "reason");
    }
    const lines = [
      headers.join(","),
      ...rows.map((r, idx) => {
        const questionId = idx + 1;
        const cols = [
          csvEscape(questionId),
          csvEscape(r.src_id),
          csvEscape(r.text),
          csvEscape(r.query),
          csvEscape(r.llm_best ? "true" : ""),
          csvEscape(r.result_count),
          csvEscape(r.result_snippet),
        ];
        if (includeValidReason) {
          cols.push("", "");
        }
        return cols.join(",");
      }),
    ];
    return lines.join("\n") + "\n";
  }

  function triggerDownload(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function executeExport() {
    if (!filteredExportRows.length) return;
    const filenameBase = `querybloom-qa-${sampleRunId || Date.now()}`;
    if (exportFormat === "yaml") {
      const yamlContent = buildYamlString(
        filteredExportRows,
        exportIncludeValidReason,
      );
      triggerDownload(
        yamlContent,
        `${filenameBase}.yaml`,
        "application/x-yaml;charset=utf-8",
      );
    } else {
      const csvContent = "\uFEFF" + buildCsvString(
        filteredExportRows,
        exportIncludeValidReason,
      );
      triggerDownload(
        csvContent,
        `${filenameBase}.csv`,
        "text/csv;charset=utf-8",
      );
    }
    showExportModal = false;
  }

  function typeLabels(entry) {
    if (!entry) return [];
    const payload = samplePayload(entry);
    const samplesTypes = payload?.types ?? {};
    if (samplesTypes && typeof samplesTypes === "object" && !Array.isArray(samplesTypes)) {
      return Object.keys(samplesTypes).map((name) => name);
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

  function samplesFor(entry) {
    const payload = samplePayload(entry);
    const types = payload?.types;
    if (!types || Array.isArray(types) || typeof types !== "object") return {};
    return types;
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

  function parseReadableEdge(edge) {
    const parsed = parseRelationshipLine(edge);
    if (!parsed) return null;
    return {
      source: parsed.source,
      label: parsed.label,
      target: parsed.target,
      optional: parsed.optional,
      readable: parsed.readable,
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
    const payload = samplePayload(entry);
    if (isV5Subgraph(payload)) return v5Properties(payload);
    const labels = labelMapFor(entry);
    const rawEdges = entry?.subgraph?.edges || [];
    const readableEdges = payload?.edges || [];
    const edges = rawEdges.length ? rawEdges : readableEdges;
    return edges
      .map((edge, index) =>
        normalizeSubgraphEdge(edge, labels, readableEdges[index]),
      )
      .filter(Boolean);
  }

  function subgraphAttributes(entry) {
    const payload = samplePayload(entry);
    if (isV5Subgraph(payload)) return v5Attributes(payload);
    const labels = labelMapFor(entry);
    const samples = payload;
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
          const displayAttrLabel = displayUri(uri, labels) || attr.label;
          const exists = rows.some(
            (row) =>
              (row.typeUri && typeUri && row.typeUri === typeUri && row.uri === uri) ||
              (row.typeLabel === (typeUri ? displayUri(typeUri, labels) : typeName) &&
                (row.uri === uri || row.label === displayAttrLabel || row.label === attr.label)),
          );
          if (!exists) {
            rows.push({
              typeUri,
              typeLabel: typeUri ? displayUri(typeUri, labels) : typeName,
              uri,
              label: displayAttrLabel,
              datatype: attr.datatype || "literal",
            });
          }
        }
      }
    }
    const seen = new Set();
    return rows.filter((row) => {
      const key = `${row.typeUri || row.typeLabel}|${row.uri || row.label}|${row.datatype || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function buildSamples(entry) {
    const payload = samplePayload(entry);
    if (isV5Subgraph(payload)) return v5Samples(payload);
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
    const willExpand = !expandedEvolutions[key];
    expandedEvolutions = {
      ...expandedEvolutions,
      [key]: willExpand,
    };
    if (willExpand && !expandedQuestions[key]) {
      expandedQuestions = {
        ...expandedQuestions,
        [key]: true,
      };
    }
  }

  function executionCount(result) {
    if (Array.isArray(result)) return result.length;
    if (typeof result?.count === "number") return result.count;
    if (Array.isArray(result?.results)) return result.results.length;
    if (Array.isArray(result?.result_preview?.rows))
      return result.result_preview.rows.length;
    if (typeof result?.boolean === "boolean" || typeof result === "boolean")
      return 1;
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

  function getPairValid(pair) {
    if (typeof pair?.valid === "boolean") return pair.valid;
    if (typeof pair?.valid === "string")
      return pair.valid.toLowerCase() === "true";
    if (pair?.verification_status) {
      return pair.verification_status === "correct";
    }
    if (pair?.execution_results != null) {
      if (pair.execution_results === false) return false;
      if (executionError(pair.execution_results)) return false;
      if (executionCount(pair.execution_results) === 0) return false;
      if (typeof pair.execution_results?.success === "boolean")
        return pair.execution_results.success;
      return true;
    }
    return true;
  }

  function getPairLlmBest(pair) {
    if (pair?.llm_best === true || pair?.llm_best === "true") return true;
    if (
      pair?.is_most_meaningful === true ||
      pair?.is_most_meaningful === "true"
    )
      return true;
    if (pair?.is_best === true || pair?.is_best === "true") return true;
    return false;
  }

  function getPairReason(pair) {
    if (pair?.reason != null && pair.reason !== "") return String(pair.reason);
    if (pair?.verification_reason != null && pair.verification_reason !== "")
      return String(pair.verification_reason);
    if (pair?.reword_reason != null && pair.reword_reason !== "")
      return String(pair.reword_reason);
    const execErr = executionError(pair?.execution_results);
    if (execErr) return String(execErr);
    return "";
  }

  function formatResultSnippet(result, maxRows = 3) {
    if (result == null) return "";
    if (typeof result === "boolean") return result ? "true" : "false";
    if (typeof result?.boolean === "boolean")
      return result.boolean ? "true" : "false";
    const err = executionError(result);
    if (err) return `Error: ${err}`;

    const preview = executionPreview(result);
    if (preview?.rows?.length) {
      const cols = preview.columns || [];
      const rows = preview.rows.slice(0, maxRows);
      if (cols.length === 1) {
        return rows.map((r) => previewCell(r, cols[0])).join("\n");
      }
      return rows
        .map((r) => cols.map((c) => `${c}: ${previewCell(r, c)}`).join(" | "))
        .join("\n");
    }
    if (Array.isArray(result?.results) && result.results.length) {
      const rows = result.results.slice(0, maxRows);
      const first = rows[0];
      if (first && typeof first === "object") {
        const cols = Object.keys(first);
        if (cols.length === 1) {
          return rows.map((r) => previewCell(r, cols[0])).join("\n");
        }
        return rows
          .map((r) => cols.map((c) => `${c}: ${previewCell(r, c)}`).join(" | "))
          .join("\n");
      }
      return rows.map(String).join("\n");
    }
    if (Array.isArray(result) && result.length) {
      const rows = result.slice(0, maxRows);
      const first = rows[0];
      if (first && typeof first === "object") {
        const cols = Object.keys(first);
        if (cols.length === 1) {
          return rows.map((r) => previewCell(r, cols[0])).join("\n");
        }
        return rows
          .map((r) => cols.map((c) => `${c}: ${previewCell(r, c)}`).join(" | "))
          .join("\n");
      }
      return rows.map(String).join("\n");
    }
    return "";
  }

  function hasReachedVerification(subgraph, pair) {
    if (!pair) return false;
    if (pair.verification_status != null) return true;
    const status = subgraph?.status;
    return (
      status === "verified" ||
      status === "rewording" ||
      status === "reworded" ||
      status === "completed"
    );
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
    const index = payload.subgraph_index ?? payload.index ?? data.subgraph_index ?? data.index;

    if (event === "error") {
      const errMsg =
        payload.error || payload.message || data.error || data.message || "QA generation failed";
      error = errMsg;
      showErrorModal("QA Generation Failed", errMsg);
      if (index != null) {
        updateSubgraph(index, { status: "failed", error: errMsg });
      }
    } else if (event === "subgraph.started") {
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
        stage_outputs: { generate: q },
      }));
      updateSubgraph(index, {
        status: "generated",
        is_meaningful: payload.is_meaningful,
        cost_usd: payload.cost_usd ?? payload.usage?.cost_usd,
        llm_usage: payload.usage,
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
          if (!pairs[i]) return;
          const currentStageOutputs = pairs[i].stage_outputs ?? {};
          pairs[i] = {
            ...pairs[i],
            stage_outputs: { ...currentStageOutputs, complexity: aug },
            ...(aug.skipped
              ? {}
              : {
                  question: aug.augmented_text_query ?? pairs[i].question,
                  sparql_query: aug.augmented_sparql_query ?? pairs[i].sparql_query,
                  complexity_types: aug.complexity_types,
                }),
          };
        });
        const patch = { status: "generated", qa_pairs: pairs };
        if (payload.cost_usd != null) {
          patch.cost_usd = (entry.cost_usd ?? 0) + Number(payload.cost_usd);
        }
        updateSubgraph(index, patch);
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
          const currentStageOutputs = pairs[i].stage_outputs ?? {};
          pairs[i] = {
            ...pairs[i],
            verification_status: vp.status,
            verification_reason: vp.reason,
            stage_outputs: { ...currentStageOutputs, verify: vp },
          };
        });
        const patch = { status: "verified", qa_pairs: pairs };
        if (payload.cost_usd != null) {
          patch.cost_usd = (entry.cost_usd ?? 0) + Number(payload.cost_usd);
        }
        updateSubgraph(index, patch);
      }
    } else if (event === "stage.started" && stage === "llm.reword") {
      updateSubgraph(index, { status: "rewording" });
    } else if (event === "stage.completed" && stage === "llm.reword") {
      const rwPairs = payload.pairs ?? [];
      const entry = qaMap[index];
      if (entry) {
        const pairs = [...(entry.qa_pairs ?? [])];
        rwPairs.forEach((rw, i) => {
          if (!pairs[i]) return;
          const currentStageOutputs = pairs[i].stage_outputs ?? {};
          pairs[i] = {
            ...pairs[i],
            stage_outputs: { ...currentStageOutputs, reword: rw },
            ...(rw.status === "needs_reword" && rw.reworded_text_query
              ? {
                  pre_reword_question: pairs[i].question,
                  question: rw.reworded_text_query,
                  reword_reason: rw.reason,
                }
              : {}),
          };
        });
        const patch = { status: "reworded", qa_pairs: pairs };
        if (payload.cost_usd != null) {
          patch.cost_usd = (entry.cost_usd ?? 0) + Number(payload.cost_usd);
        }
        updateSubgraph(index, patch);
      }
    } else if (event === "subgraph.completed") {
      // Final state — use streamed qa_pairs already built, just mark completed
      const result = payload.result ?? payload;
      const entry = qaMap[index];
      const costUsd =
        result.cost_usd ??
        payload.cost_usd ??
        entry?.cost_usd ??
        null;
      const llmUsage =
        result.llm_usage ??
        payload.llm_usage ??
        entry?.llm_usage ??
        null;
      // Prefer the final result's qa_pairs (most complete) but fall back to streamed
      updateSubgraph(index, {
        status: "completed",
        is_meaningful: result.is_meaningful,
        cost_usd: costUsd,
        llm_usage: llmUsage,
        qa_pairs: result.qa_pairs?.length
          ? result.qa_pairs
          : (entry?.qa_pairs ?? []),
      });
    } else if (event === "subgraph.failed") {
      const errMsg =
        payload.error ?? payload.message ?? data.error ?? data.message ?? "Pipeline failed";
      error = errMsg;
      showErrorModal("Subgraph Generation Failed", errMsg);
      updateSubgraph(index, {
        status: "failed",
        error: errMsg,
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

    let streamHadErrors = false;
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
        (frame) => {
          if (frame.event === "error" || frame.event === "subgraph.failed") {
            streamHadErrors = true;
          }
          addFrame(frame);
        },
        activeAbortController.signal,
      );

      const hasFailures = requested.some(
        (idx) => qaMap[idx]?.status === "failed",
      );
      if (!streamHadErrors && !hasFailures && !error) {
        await hydrateStoredQa(sampleRunId, { force: true });
      }
    } catch (err) {
      if (err?.name !== "AbortError" && !String(err?.message || "").includes("aborted")) {
        const formatted = formatCaughtError(err);
        error = formatted.message || "QA generation failed";
        console.error("QA generation failed", err, formatted);
        reportBrowserError(err, {
          source: "QaPanel.generateSubgraphs",
          sampleRunId,
          subgraphIndexes: requested,
        });
        showErrorModal("QA Generation Error", formatted.details);
      }
      for (const index of requested) {
        if (qaMap[index]?.status !== "completed") {
          updateSubgraph(index, {
            status: "failed",
            error: error || "Generation failed",
          });
        }
      }
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
  {#if errorModalMessage}
    <div
      class="modal-backdrop"
      role="presentation"
      on:click={closeErrorModal}
      on:keydown={(e) => e.key === "Escape" && closeErrorModal()}
    >
      <div
        class="modal-card"
        role="dialog"
        tabindex="-1"
        aria-modal="true"
        aria-labelledby="modal-title"
        on:click|stopPropagation
        on:keydown|stopPropagation
      >
        <div class="modal-header">
          <div class="modal-title-wrap">
            <h3 id="modal-title">{errorModalMessage}</h3>
          </div>
          <button class="modal-close-btn" type="button" aria-label="Close" on:click={closeErrorModal}>✕</button>
        </div>
        <div class="modal-body">
          {#if errorModalDetails}
            <pre class="modal-error-text">{errorModalDetails}</pre>
          {/if}
        </div>
        <div class="modal-actions">
          <button class="modal-primary-btn" type="button" on:click={closeErrorModal}>Dismiss</button>
        </div>
      </div>
    </div>
  {/if}

  {#if showExportModal}
    <div
      class="modal-backdrop"
      role="presentation"
      on:click={() => (showExportModal = false)}
      on:keydown={(e) => e.key === "Escape" && (showExportModal = false)}
    >
      <div
        class="modal-card export-modal"
        role="dialog"
        tabindex="-1"
        aria-modal="true"
        aria-labelledby="export-modal-title"
        on:click|stopPropagation
        on:keydown|stopPropagation
      >
        <div class="modal-header export-modal-header">
          <div class="modal-title-wrap">
            <span class="modal-icon" aria-hidden="true">📥</span>
            <h3 id="export-modal-title">Download QA Dataset</h3>
          </div>
          <button
            class="modal-close-btn"
            type="button"
            aria-label="Close"
            on:click={() => (showExportModal = false)}>✕</button
          >
        </div>
        <div class="modal-body export-modal-body">
          <div class="export-section">
            <span class="export-section-label">File Format</span>
            <div class="format-toggle-group">
              <label class="format-pill" class:active={exportFormat === "yaml"}>
                <input
                  type="radio"
                  name="exportFormat"
                  value="yaml"
                  bind:group={exportFormat}
                />
                <span class="format-pill-text">YAML</span>
                <span class="format-pill-badge">.yaml</span>
              </label>
              <label class="format-pill" class:active={exportFormat === "csv"}>
                <input
                  type="radio"
                  name="exportFormat"
                  value="csv"
                  bind:group={exportFormat}
                />
                <span class="format-pill-text">CSV</span>
                <span class="format-pill-badge">.csv</span>
              </label>
            </div>
          </div>

          <div class="export-section">
            <span class="export-section-label">Query Selection per Graph</span>
            <div class="query-selection-group">
              <label class="selection-pill" class:active={exportQuerySelection === "all"}>
                <input
                  type="radio"
                  name="exportQuerySelection"
                  value="all"
                  bind:group={exportQuerySelection}
                />
                <div class="option-text">
                  <span class="option-title">Keep all text-query pairs</span>
                  <span class="option-desc">Includes every generated pair that passes filters</span>
                </div>
              </label>
              <label class="selection-pill" class:active={exportQuerySelection === "best"}>
                <input
                  type="radio"
                  name="exportQuerySelection"
                  value="best"
                  bind:group={exportQuerySelection}
                />
                <div class="option-text">
                  <span class="option-title">Keep best LLM query per graph</span>
                  <span class="option-desc">Keeps the single highest-utility question annotated by the LLM</span>
                </div>
              </label>
              <label class="selection-pill" class:active={exportQuerySelection === "random"}>
                <input
                  type="radio"
                  name="exportQuerySelection"
                  value="random"
                  bind:group={exportQuerySelection}
                />
                <div class="option-text">
                  <span class="option-title">Keep random LLM query per graph</span>
                  <span class="option-desc">Keeps at most one random valid pair per subgraph</span>
                </div>
              </label>
            </div>
          </div>

          <div class="export-section">
            <span class="export-section-label">Dataset Filters & Options</span>
            <div class="export-options-list">
              <label class="export-option-row">
                <input
                  type="checkbox"
                  bind:checked={exportIgnoreNoResults}
                />
                <div class="option-text">
                  <span class="option-title">Ignore queries with no results</span>
                  <span class="option-desc">Excludes queries returning 0 results or execution errors (Default)</span>
                </div>
              </label>
              <label class="export-option-row">
                <input
                  type="checkbox"
                  bind:checked={exportIgnoreNeedsFix}
                />
                <div class="option-text">
                  <span class="option-title">Ignore unfixed queries</span>
                  <span class="option-desc">Excludes queries flagged by the verifier as needing fixes</span>
                </div>
              </label>
              <label class="export-option-row">
                <input
                  type="checkbox"
                  bind:checked={exportIncludeValidReason}
                />
                <div class="option-text">
                  <span class="option-title">Add empty valid and reason fields</span>
                  <span class="option-desc">Appends empty valid and reason columns/fields for external annotation</span>
                </div>
              </label>
            </div>
          </div>

          <div class="export-summary-box">
            <span class="export-summary-count">
              {#if filteredExportRows.length > 0}
                Ready to export <strong>{filteredExportRows.length}</strong> of {allExportRows.length} pairs (from {selectedSubgraphCount} selected subgraph{selectedSubgraphCount === 1 ? "" : "s"})
              {:else if allExportRows.length > 0}
                <span class="export-warn">No pairs match the selected filters ({allExportRows.length} pairs in {selectedSubgraphCount} selected subgraphs)</span>
              {:else}
                <span class="export-warn">No generated pairs found in the {selectedSubgraphCount} selected subgraph{selectedSubgraphCount === 1 ? "" : "s"}</span>
              {/if}
            </span>
          </div>
        </div>
        <div class="modal-actions">
          <button
            class="secondary-action modal-cancel-btn"
            type="button"
            on:click={() => (showExportModal = false)}>Cancel</button
          >
          <button
            class="modal-export-btn"
            type="button"
            disabled={!filteredExportRows.length}
            on:click={executeExport}
          >
            Download {exportFormat.toUpperCase()}
          </button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Large Subgraph Pattern & Samples Popup Modal -->
  {#if showSubgraphInspector && selectedInfo}
    <QaPatternSamplesModal
      subgraphs={subgraphs}
      selectedIndex={selectedIndex}
      properties={selectedPatternProperties}
      attributes={selectedPatternAttributes}
      samples={selectedSamples}
      emptySamplesText={samplePayload(selectedInfo)
        ? "No samples could be formed for this subgraph."
        : "Sample entities will appear once mining completes."}
      onClose={() => (showSubgraphInspector = false)}
      onSelectSubgraph={(idx) => (selectedIndex = idx)}
      on:close={() => (showSubgraphInspector = false)}
      on:selectSubgraph={(e) => (selectedIndex = e.detail)}
    />
  {/if}

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
        disabled={!totalSelectedGeneratedPairs}
        on:click={() => (showExportModal = true)}>Download</button
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
                <div class="sg-card-meta-row">
                  <div class="chips">
                    {#each types.slice(0, 3) as t}<span class="chip">{t}</span
                      >{/each}
                    {#if types.length > 3}<span class="chip more"
                        >+{types.length - 3}</span
                      >{/if}
                  </div>
                  {#if sg.cost_usd != null}
                    <span class="sg-cost" title={costTooltip(sg)}>
                      {formatCost(sg.cost_usd)}
                    </span>
                  {/if}
                </div>
              {:else}
                <div class="sg-card-meta-row">
                  <p class="no-type">No type info</p>
                  {#if sg.cost_usd != null}
                    <span class="sg-cost" title={costTooltip(sg)}>
                      {formatCost(sg.cost_usd)}
                    </span>
                  {/if}
                </div>
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
            <div class="detail-head-left">
              <h3>Subgraph {displaySubgraphId(selected.index)}</h3>
              {#if selected.cost_usd != null}
                <span class="batch-cost-badge" title={costTooltip(selected)}>
                  <span class="cost-label">Batch Cost:</span>
                  <span class="cost-val">{formatCost(selected.cost_usd)}</span>
                </span>
              {/if}
            </div>
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
                on:click={() => (showSubgraphInspector = true)}
                title="Open large pattern and samples popup"
              >
                <span class="inspector-btn-icon" aria-hidden="true">🔍</span>
                <span>Show pattern and samples</span>
              </button>
            </div>
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
              <div class="qa-section-header">
                <span class="qa-section-title">
                  Generated Questions ({pairs.length})
                </span>
                {#if selected.cost_usd != null}
                  <span class="batch-cost-note" title={costTooltip(selected)}>
                    LLM batch cost: <strong>{formatCost(selected.cost_usd)}</strong>
                    {#if selected.llm_usage?.total_tokens}
                      <span class="tokens-count">({selected.llm_usage.total_tokens.toLocaleString()} tokens)</span>
                    {/if}
                  </span>
                {/if}
              </div>
              <ol class="qa-list">
                {#each pairs as pair, i}
                  {@const key = questionKey(selected.index, i)}
                  {@const preview = executionPreview(pair.execution_results)}
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
                          {#if pair.is_most_meaningful}
                            <span class="badge badge-best">★ Best Question</span>
                          {/if}
                          {#if hasReachedVerification(selected, pair) && pair.execution_results != null}
                            {#if pair.execution_results === false || executionError(pair.execution_results)}
                              <span class="badge badge-fail">✗ error</span>
                            {:else if executionCount(pair.execution_results) === 0}
                              <span class="badge badge-neutral">0 results</span>
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

                    {#if expandedEvolutions[key]}
                      <QaEvolution {pair} />
                    {/if}

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

                        {#if hasReachedVerification(selected, pair) && pair.execution_results != null}
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

  .sg-card-meta-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
  }

  .sg-cost {
    font-size: 0.72rem;
    font-weight: 700;
    color: #4a5c88;
    background: #edf2fc;
    border-radius: 4px;
    padding: 1px 5px;
    margin-left: auto;
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
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
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 14px;
  }

  .detail-head-left {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
  }

  .batch-cost-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: #f0f4ff;
    border: 1px solid #d4e0fc;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.76rem;
    color: #2b4580;
    font-weight: 600;
  }

  .batch-cost-badge .cost-label {
    color: #6a7c9f;
    font-weight: 500;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .batch-cost-badge .cost-val {
    font-weight: 700;
    color: #1a3c87;
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
  }

  .qa-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    margin: 12px 0 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid #eef2fa;
  }

  .qa-section-title {
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #65708c;
  }

  .batch-cost-note {
    font-size: 0.76rem;
    color: #667290;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: #f6f8fd;
    border: 1px solid #e2e8f5;
    border-radius: 5px;
    padding: 2px 7px;
  }

  .batch-cost-note strong {
    color: #1a3c87;
    font-weight: 700;
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
  }

  .tokens-count {
    color: #8c97b2;
    font-size: 0.72rem;
  }

  h3 {
    color: var(--color-uni-dark-blue);
    font-size: 0.95rem;
    margin: 0;
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
    padding: 7px 12px;
    font-size: 0.8rem;
    font-weight: 700;
  }

  .inspector-toggle {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: #f8fafc;
    border-color: #cbd5e1;
    transition: all 0.15s ease;
  }

  .inspector-toggle:hover {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1d4ed8;
  }

  .inspector-btn-icon {
    font-size: 0.88rem;
    line-height: 1;
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

  .section-label {
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
  .badge-best {
    background: #fff4e5;
    color: #e67e22;
    border: 1px solid #ffe0b2;
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

  /* ── Modal / Popup ───────────────────────────────────── */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: rgba(15, 23, 42, 0.65);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }

  .modal-card {
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1);
    border: 1px solid #e2e8f0;
    max-width: 540px;
    width: 100%;
    overflow: hidden;
    animation: modalPop 0.18s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes modalPop {
    from {
      opacity: 0;
      transform: scale(0.96) translateY(6px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    background: #fff5f5;
    border-bottom: 1px solid #fed7d7;
  }

  .modal-title-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .modal-icon {
    font-size: 1.25rem;
  }

  .modal-header h3 {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
    color: #c53030;
  }

  .modal-close-btn {
    background: transparent;
    border: none;
    font-size: 1.1rem;
    color: #a0aec0;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    line-height: 1;
  }

  .modal-close-btn:hover {
    color: #4a5568;
    background: #edf2f7;
  }

  .modal-body {
    padding: 20px;
    display: grid;
    gap: 14px;
  }

  .modal-error-text {
    margin: 0;
    font-size: 0.78rem;
    line-height: 1.45;
    color: #2d3748;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 12px 14px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 420px;
    overflow: auto;
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    padding: 12px 20px 16px;
    background: #f8fafc;
    border-top: 1px solid #edf2f7;
  }

  .modal-primary-btn {
    background: #e53e3e;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .modal-primary-btn:hover {
    background: #c53030;
  }

  /* ── Export Modal ─────────────────────────────────────── */
  .export-modal-header {
    background: #f0f4ff;
    border-bottom: 1px solid #d8e2fd;
  }

  .export-modal-header h3 {
    color: #1e3a8a;
  }

  .export-modal-body {
    padding: 20px 24px;
    gap: 18px;
  }

  .export-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .export-section-label {
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
  }

  .format-toggle-group {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .format-pill {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    border-radius: 8px;
    border: 2px solid #e2e8f0;
    background: #f8fafc;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .format-pill input {
    position: absolute;
    opacity: 0;
    pointer-events: none;
  }

  .format-pill:hover {
    border-color: #cbd5e1;
    background: #f1f5f9;
  }

  .format-pill.active {
    border-color: #3b82f6;
    background: #eff6ff;
  }

  .format-pill-text {
    font-size: 0.95rem;
    font-weight: 700;
    color: #1e293b;
  }

  .format-pill.active .format-pill-text {
    color: #1d4ed8;
  }

  .format-pill-badge {
    font-size: 0.75rem;
    font-weight: 600;
    background: #e2e8f0;
    color: #475569;
    padding: 2px 6px;
    border-radius: 4px;
  }

  .format-pill.active .format-pill-badge {
    background: #bfdbfe;
    color: #1e40af;
  }

  .query-selection-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 8px;
  }

  .selection-pill {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    cursor: pointer;
    padding: 8px 10px;
    border-radius: 6px;
    border: 1px solid transparent;
    transition: all 0.12s ease;
  }

  .selection-pill:hover {
    background: #f1f5f9;
  }

  .selection-pill.active {
    background: #eff6ff;
    border-color: #bfdbfe;
  }

  .selection-pill input[type="radio"] {
    margin-top: 3px;
    accent-color: #2563eb;
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .export-options-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px;
  }

  .export-option-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    cursor: pointer;
    padding: 6px 8px;
    border-radius: 6px;
    transition: background 0.12s ease;
  }

  .export-option-row:hover {
    background: #f1f5f9;
  }

  .export-option-row input[type="checkbox"] {
    margin-top: 3px;
    accent-color: #2563eb;
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .option-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .option-title {
    font-size: 0.88rem;
    font-weight: 600;
    color: #1e293b;
  }

  .option-desc {
    font-size: 0.75rem;
    color: #64748b;
    line-height: 1.35;
  }

  .export-summary-box {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 8px;
    padding: 10px 14px;
    display: flex;
    align-items: center;
  }

  .export-summary-count {
    font-size: 0.84rem;
    color: #166534;
  }

  .export-summary-count strong {
    font-weight: 700;
    color: #14532d;
  }

  .export-warn {
    color: #b45309;
    font-weight: 600;
  }

  .modal-cancel-btn {
    margin-right: 8px;
  }

  .modal-export-btn {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .modal-export-btn:hover:not(:disabled) {
    background: #1d4ed8;
  }

  .modal-export-btn:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
</style>
