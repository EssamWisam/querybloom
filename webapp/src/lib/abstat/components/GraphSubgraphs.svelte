<script>
  import { onDestroy, onMount } from "svelte";
  import AbstatGraph from "./AbstatGraph.svelte";
  import QaPatternSamplesModal from "./QaPatternSamplesModal.svelte";
  import {
    normalizeGraph,
    shortName,
    subgraphNodeIds,
    SUBGRAPH_PALETTE,
    uriFallbackLabel,
  } from "../graph.js";

  export let graph = null;
  export let subgraphs = [];
  export let selectedIndex = null;
  export let onSelect = (_idx = null) => {};
  export let running = false;
  export let miningPhase = false;
  export let skipSubgraphsPending = false;
  export let onSkipSubgraphs = null;

  let showGraph = false;
  let graphFrameOne = null;
  let graphFrameTwo = null;

  onMount(() => {
    graphFrameOne = requestAnimationFrame(() => {
      graphFrameTwo = requestAnimationFrame(() => {
        showGraph = true;
      });
    });
  });

  onDestroy(() => {
    if (graphFrameOne) cancelAnimationFrame(graphFrameOne);
    if (graphFrameTwo) cancelAnimationFrame(graphFrameTwo);
  });

  $: selected = subgraphs.find((item) => item.index === selectedIndex) || null;

  function parseAttrs(str) {
    if (!str) return [];
    const inner = str.replace(/^\(|\)$/g, "");
    const re = /([^,=]+):([^=]+)=('(?:[^']|'')*'|[^,]+)/g;
    const entries = [];
    let m;
    while ((m = re.exec(inner)) !== null) {
      const label = m[1].trim();
      const datatype = shortName(m[2].trim()) || "literal";
      let value = m[3].trim();
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

  function subgraphClasses(entry) {
    const labels = labelMapFor(entry);
    const ids = subgraphNodeIds(entry);
    for (const edge of entry?.subgraph?.edges || []) {
      const parsed = normalizeSubgraphEdge(edge, labels);
      if (parsed?.sourceUri) ids.add(parsed.sourceUri);
      if (parsed?.targetUri) ids.add(parsed.targetUri);
    }
    return [...ids]
      .filter(Boolean)
      .map((uri) => ({ uri, label: displayUri(uri, labels) }));
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

  $: classes = selected ? subgraphClasses(selected) : [];
  $: properties = selected ? subgraphProperties(selected) : [];
  $: attributes = selected ? subgraphAttributes(selected) : [];
  $: sampleEntries = selected ? Object.entries(samplesFor(selected)) : [];

  function buildSamples(entry) {
    const typeData = samplesFor(entry);
    const props = subgraphProperties(entry);

    const allLists = Object.values(typeData).map(
      (td) => td?.sample_entities || [],
    );
    const count = allLists.length
      ? Math.min(...allLists.map((l) => l.length))
      : 0;
    const shown = Math.min(count, 3);

    const instances = [];
    for (let i = 0; i < shown; i++) {
      const triples = props.map((prop) => {
        const srcEnt = sampleBucket(typeData, prop.source, prop.sourceUri)
          ?.sample_entities?.[i];
        const tgtEnt = sampleBucket(typeData, prop.target, prop.targetUri)
          ?.sample_entities?.[i];
        return {
          src: displayEntity(srcEnt),
          prop: prop.label,
          tgt: displayEntity(tgtEnt),
          optional: prop.optional,
          kind: "triple",
        };
      });

      const attrLines = [];
      for (const [typeName, td] of Object.entries(typeData)) {
        const ent = td?.sample_entities?.[i];
        if (ent?.attributes) {
          const src = displayEntity(ent, typeName);
          for (const attr of parseAttrs(ent.attributes)) {
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
      for (const [typeName, td] of Object.entries(typeData)) {
        for (const entity of (td?.sample_entities || []).slice(0, 3)) {
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

  $: samples = selected ? buildSamples(selected) : [];

  let pinnedNodeId = null;
  let pinnedNodeLabel = null;
  let showPatternModal = false;

  function handleNodeClick(info) {
    pinnedNodeId = info?.id ?? null;
    pinnedNodeLabel = info?.label ?? null;
    if (pinnedNodeId) {
      onSelect(null);
    }
  }

  function selectSubgraph(index) {
    const nextIndex = index === selectedIndex ? null : index;
    onSelect(nextIndex);
  }

  function openPatternModal(index) {
    onSelect(index);
    showPatternModal = true;
  }

  $: filteredSubgraphs = (() => {
    const list = pinnedNodeId
      ? subgraphs.filter((item) => subgraphNodeIds(item).has(pinnedNodeId))
      : subgraphs;
    const seen = new Set();
    const result = [];
    for (const item of list) {
      const idx = Number.isFinite(Number(item?.index)) ? Number(item.index) : 0;
      if (seen.has(idx)) continue;
      seen.add(idx);
      result.push({ ...item, index: idx });
    }
    return result;
  })();
</script>

<section class="subgraph-workspace">
  <div class="graph-region">
    {#if graph && showGraph}
      <AbstatGraph
        {graph}
        {subgraphs}
        {selectedIndex}
        preferGridLayout={true}
        onNodeClick={handleNodeClick}
      />
    {:else if graph}
      <div class="graph-empty">Preparing graph view...</div>
    {:else}
      <div class="graph-empty">
        Pattern graph will render as soon as `graph.updated` arrives.
      </div>
    {/if}
  </div>

  <aside class="subgraph-list" aria-label="Subgraphs">
    <header>
      <h2>Subgraphs</h2>
      {#if running && miningPhase && onSkipSubgraphs}
        <button
          class="skip-btn"
          type="button"
          disabled={skipSubgraphsPending}
          on:click={onSkipSubgraphs}
          >{#if skipSubgraphsPending}<span
              class="skip-spinner"
              aria-hidden="true"
            ></span>{/if}{skipSubgraphsPending
            ? "Skipping to questions..."
            : "Skip to questions →"}</button
        >
      {/if}
      {#if pinnedNodeId}
        <p class="filter-notice">
          Filtered by <strong>{pinnedNodeLabel || pinnedNodeId}</strong>
          <button
            class="clear-filter"
            type="button"
            on:click={() => {
              pinnedNodeId = null;
              pinnedNodeLabel = null;
            }}>✕</button
          >
        </p>
      {:else}
        <p>{subgraphs.length} discovered</p>
      {/if}
    </header>
    <div class="rows">
      {#if !subgraphs.length}
        <p class="empty">Subgraph groups appear as mining streams.</p>
      {:else if filteredSubgraphs.length === 0}
        <p class="empty">No subgraphs contain this node.</p>
      {/if}
      {#each filteredSubgraphs as item (item.index)}
        <div
          class:selected={item.index === selectedIndex}
          class="subgraph-card"
        >
          <button
            class="subgraph-select"
            type="button"
            on:click={() => selectSubgraph(item.index)}
          >
            <span class="sg-row">
              <span
                class="sg-dot"
                style="background:{SUBGRAPH_PALETTE[
                  item.index % SUBGRAPH_PALETTE.length
                ]}"
              ></span>
              Subgraph {item.index + 1}
            </span>
            <small
              >{item.subgraph?.num_types || item.numTypes || "?"} types · support
              {item.subgraph?.support || item.support || "?"}</small
            >
          </button>

          <button
            class="open-modal-btn"
            type="button"
            on:click|stopPropagation={() => openPatternModal(item.index)}
            aria-label={`View Subgraph ${item.index + 1} pattern and samples in popup`}
            title={`View Subgraph ${item.index + 1} pattern and samples in popup`}
          >
            <span class="open-icon" aria-hidden="true">↗</span>
          </button>
        </div>
      {/each}
    </div>
  </aside>
</section>

{#if showPatternModal && selected}
  <QaPatternSamplesModal
    subgraphs={subgraphs}
    selectedIndex={selectedIndex}
    properties={properties}
    attributes={attributes}
    samples={samples}
    emptySamplesText={samplePayload(selected)
      ? "No samples could be formed for this subgraph."
      : "Sample entities will appear once mining completes."}
    onClose={() => (showPatternModal = false)}
    onSelectSubgraph={(idx) => onSelect(idx)}
    on:close={() => (showPatternModal = false)}
    on:selectSubgraph={(e) => onSelect(e.detail)}
  />
{/if}

<style>
  .subgraph-workspace {
    height: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    grid-template-rows: minmax(0, 1fr);
    min-height: 0;
    overflow: hidden;
  }

  aside {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
    background: #fff;
  }

  .subgraph-list {
    border-left: 1px solid var(--border-default);
  }

  .skip-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    margin-bottom: 18px;
    padding: 9px 14px;
    background: var(--color-uni-dark-blue, #1f2947);
    color: #fff;
    border: none;
    border-radius: 7px;
    font-size: 0.85rem;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .skip-btn:disabled {
    cursor: wait;
    opacity: 0.9;
  }

  .skip-spinner {
    width: 12px;
    height: 12px;
    border: 2px solid rgba(255, 255, 255, 0.35);
    border-top-color: #fff;
    border-radius: 50%;
    flex-shrink: 0;
    animation: skip-spin 0.7s linear infinite;
  }

  .skip-btn:hover {
    opacity: 0.85;
  }

  @keyframes skip-spin {
    to {
      transform: rotate(360deg);
    }
  }

  .sg-row {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .sg-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .filter-notice {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.78rem;
    color: #2b6cb0;
    margin: 4px 0 0;
    flex-wrap: wrap;
  }

  .clear-filter {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.78rem;
    color: #718096;
    padding: 0 2px;
    line-height: 1;
  }

  .clear-filter:hover {
    color: #c1002a;
  }

  header {
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-default);
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    color: var(--color-uni-dark-blue);
    font-size: 1rem;
  }

  header p,
  .empty,
  small {
    color: #65708c;
    font-size: 0.8rem;
  }

  .rows {
    flex: 1 1 0;
    overflow-y: auto;
    display: grid;
    gap: 6px;
    padding: 10px;
    align-content: start;
  }

  .open-modal-btn {
    grid-column: 2;
    grid-row: 1;
    align-self: center;
    width: 28px;
    height: 28px;
    display: grid;
    place-items: center;
    padding: 0;
    border: 1px solid rgba(52, 74, 154, 0.25);
    border-radius: 6px;
    background: #f7f9ff;
    color: var(--color-uni-blue, #273763);
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .open-modal-btn:hover {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1d4ed8;
    transform: translate(1px, -1px);
  }

  .open-icon {
    font-size: 1.05rem;
    font-weight: 700;
    line-height: 1;
  }

  .subgraph-card {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 7px;
    border: 1px solid #e1e6f2;
    border-radius: 7px;
    background: #fff;
    padding: 8px;
  }

  .subgraph-card.selected {
    border-color: rgba(0, 160, 130, 0.55);
    background: rgba(0, 160, 130, 0.06);
  }

  .subgraph-select {
    grid-column: 1;
    grid-row: 1;
    display: grid;
    gap: 3px;
    width: 100%;
    border: 0;
    background: transparent;
    padding: 2px;
    text-align: left;
    cursor: pointer;
  }



  .subgraph-select span {
    color: #17203b;
    font-weight: 800;
  }

  .graph-region {
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: grid;
    overflow: hidden;
    background: #fbfcff;
  }

  .graph-empty {
    display: grid;
    place-items: center;
    height: 100%;
    color: #66708a;
  }



  @media (max-width: 1100px) {
    .subgraph-workspace {
      grid-template-columns: minmax(0, 1fr) 210px;
    }
  }
</style>
