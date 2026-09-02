<script>
  import { createEventDispatcher, onDestroy, onMount, tick } from "svelte";
  import {
    isUri,
    shortName,
    SUBGRAPH_PALETTE,
    uriFallbackLabel,
  } from "../graph.js";

  export let subgraphs = [];
  export let selectedIndex = null;
  export let properties = [];
  export let attributes = [];
  export let samples = [];
  export let emptyPatternText = "No pattern details yet.";
  export let emptySamplesText = "No samples could be formed for this subgraph.";
  export let idPrefix = "qa-modal";
  export let onClose = () => {};
  export let onSelectSubgraph = () => {};

  const dispatch = createEventDispatcher();

  // Switching States
  // viewMode: "both" | "pattern" | "sample"
  let viewMode = "both";
  let currentSample = 0;

  // Active hover tooltip for truncated node labels
  // { text: string, rawUri?: string, sublabel?: string, x: number, y: number, kind: "pattern" | "sample" }
  let activeTooltip = null;

  // Cytoscape References & State
  let patternContainer;
  let sampleContainer;
  let modalContainerEl;
  let cytoscapeLib = null;
  let patternCy = null;
  let sampleCy = null;
  let patternRenderToken = 0;
  let sampleRenderToken = 0;
  let resizeObserver = null;

  const NODE_W = 136;
  const NODE_H = 46;
  const ATTR_W = 120;
  const ATTR_H = 38;

  $: currentSubgraphInfo =
    subgraphs.find((sg) => sg.index === selectedIndex) || null;

  $: currentSubgraphPaletteColor =
    SUBGRAPH_PALETTE[(selectedIndex ?? 0) % SUBGRAPH_PALETTE.length] ||
    "#3b82f6";

  $: sortedSubgraphs = [...subgraphs].sort(
    (a, b) => (Number(a.index) || 0) - (Number(b.index) || 0),
  );

  $: currentSubgraphPos = sortedSubgraphs.findIndex(
    (sg) => sg.index === selectedIndex,
  );
  $: hasPrevSubgraph = currentSubgraphPos > 0;
  $: hasNextSubgraph =
    currentSubgraphPos >= 0 && currentSubgraphPos < sortedSubgraphs.length - 1;

  $: if (currentSample >= samples.length) {
    currentSample = Math.max(0, samples.length - 1);
  }

  $: patternGraph = buildPatternGraph(properties, attributes);
  $: sampleGraph = buildSampleGraph(samples[currentSample]);

  onMount(async () => {
    const [cytoscapeMod, colaMod] = await Promise.all([
      import("cytoscape"),
      import("cytoscape-cola"),
    ]);
    const cytoscape = cytoscapeMod.default ?? cytoscapeMod;
    const cola = colaMod.default ?? colaMod;
    try {
      cytoscape.use(cola);
    } catch (_) {
      // already registered
    }
    cytoscapeLib = cytoscape;

    if (modalContainerEl && typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => {
        handleResize();
      });
      resizeObserver.observe(modalContainerEl);
    }
  });

  onDestroy(() => {
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    destroyGraph("pattern");
    destroyGraph("sample");
  });

  // Re-render when graph data or container becomes available
  $: if (
    cytoscapeLib &&
    patternContainer &&
    patternGraph &&
    (viewMode === "both" || viewMode === "pattern")
  ) {
    renderGraph("pattern", patternContainer, patternGraph);
  }

  $: if (
    cytoscapeLib &&
    sampleContainer &&
    sampleGraph &&
    (viewMode === "both" || viewMode === "sample")
  ) {
    renderGraph("sample", sampleContainer, sampleGraph);
  }

  function handleResize() {
    requestAnimationFrame(() => {
      if (patternCy && !patternCy.destroyed()) {
        patternCy.resize();
      }
      if (sampleCy && !sampleCy.destroyed()) {
        sampleCy.resize();
      }
    });
  }

  async function setViewMode(mode) {
    if (viewMode === mode) return;
    viewMode = mode;
    activeTooltip = null;
    await tick();
    requestAnimationFrame(() => {
      if (patternCy && !patternCy.destroyed()) {
        patternCy.resize();
        patternCy.fit(patternCy.elements(), 30);
      }
      if (sampleCy && !sampleCy.destroyed()) {
        sampleCy.resize();
        sampleCy.fit(sampleCy.elements(), 30);
      }
    });
  }

  function handleClose() {
    onClose();
    dispatch("close");
  }

  function handleKeydown(event) {
    if (event.key === "Escape") {
      handleClose();
    }
  }

  function selectSubgraphIndex(idx) {
    if (idx === selectedIndex) return;
    activeTooltip = null;
    onSelectSubgraph(idx);
    dispatch("selectSubgraph", idx);
  }

  function prevSubgraph() {
    if (!hasPrevSubgraph) return;
    const prevItem = sortedSubgraphs[currentSubgraphPos - 1];
    if (prevItem) selectSubgraphIndex(prevItem.index);
  }

  function nextSubgraph() {
    if (!hasNextSubgraph) return;
    const nextItem = sortedSubgraphs[currentSubgraphPos + 1];
    if (nextItem) selectSubgraphIndex(nextItem.index);
  }

  function nextSample(offset) {
    if (!samples.length) return;
    activeTooltip = null;
    currentSample = (currentSample + offset + samples.length) % samples.length;
  }

  function selectSample(idx) {
    if (idx >= 0 && idx < samples.length) {
      activeTooltip = null;
      currentSample = idx;
    }
  }

  function fitGraph(kind) {
    const target = kind === "pattern" ? patternCy : sampleCy;
    if (target && !target.destroyed()) {
      target.fit(target.elements(), 30);
      target.center(target.elements());
    }
  }

  function zoomGraph(kind, factor) {
    const target = kind === "pattern" ? patternCy : sampleCy;
    if (target && !target.destroyed()) {
      const zoom = target.zoom();
      target.zoom({
        level: zoom * factor,
        renderedPosition: {
          x: target.width() / 2,
          y: target.height() / 2,
        },
      });
    }
  }

  function displaySubgraphId(index) {
    const info = subgraphs.find((s) => s.index === index);
    return info?.subgraph?.subgraph_id ?? info?.subgraph_id ?? index + 1;
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

  // Graph Data Builders
  function safeId(value) {
    return String(value || "mini")
      .replace(/[^a-zA-Z0-9_-]/g, "-")
      .replace(/^-+/, "id-");
  }

  function visualKey(prefix, value) {
    return `${prefix}-${String(value || "?")
      .toLowerCase()
      .trim()}`;
  }

  function displayLabel(value, max = 28) {
    const label = String(uriFallbackLabel(value) || value || "?").trim();
    if (label.length <= max) return label;
    return `${label.slice(0, Math.max(1, max - 1)).trimEnd()}...`;
  }

  function addNode(nodes, id, label, kind = "entity", sublabel = "") {
    const key = String(id || label || `node-${nodes.size}`);
    if (!nodes.has(key)) {
      const fullText = String(uriFallbackLabel(label) || label || key).trim();
      const maxLen = kind === "attr-value" ? 22 : 26;
      const shortText = displayLabel(label, maxLen);
      const isTruncated =
        fullText.length > shortText.length ||
        shortText.endsWith("...") ||
        (isUri(label) && shortText !== label);

      nodes.set(key, {
        data: {
          id: key,
          label: shortText,
          fullLabel: fullText,
          rawUri: isUri(label) ? label : "",
          isTruncated,
          sublabel: sublabel ? displayLabel(sublabel, 18) : "",
          kind,
          width: kind === "attr-value" ? ATTR_W : NODE_W,
          height: kind === "attr-value" ? ATTR_H : NODE_H,
        },
      });
    }
    return key;
  }

  function mergeEdges(edges) {
    const merged = new Map();
    for (const edge of edges) {
      const key = [edge.kind, edge.source, edge.target].join("|");
      if (!merged.has(key)) {
        merged.set(key, {
          ...edge,
          labels: new Set(edge.label ? [edge.label] : []),
          optional: Boolean(edge.optional),
        });
        continue;
      }
      const existing = merged.get(key);
      if (edge.label) existing.labels.add(edge.label);
      existing.optional = existing.optional && Boolean(edge.optional);
    }

    return [...merged.values()].map((edge, index) => {
      const labels = [...edge.labels].filter(Boolean);
      const label =
        labels.length > 2
          ? `${labels.slice(0, 2).join("\n")}\n+${labels.length - 2} more`
          : labels.join("\n");
      return {
        data: {
          id: `${edge.kind}-${index}-${safeId(edge.source)}-${safeId(edge.target)}`,
          source: edge.source,
          target: edge.target,
          label,
          fullLabel: labels.join(" / "),
          kind: edge.kind,
          optional: edge.optional ? "yes" : "no",
        },
      };
    });
  }

  function buildPatternGraph(objectEdges, attrEdges) {
    const nodes = new Map();
    const edges = [];

    for (const edge of objectEdges || []) {
      const source = addNode(
        nodes,
        visualKey("class", edge.source),
        edge.source,
      );
      const target = addNode(
        nodes,
        visualKey("class", edge.target),
        edge.target,
      );
      edges.push({
        source,
        target,
        label: edge.label,
        kind: "object",
        optional: edge.optional,
      });
    }

    for (const attr of attrEdges || []) {
      const source = addNode(
        nodes,
        visualKey("class", attr.typeLabel || attr.typeUri),
        attr.typeLabel || "?",
      );
      const target = addNode(
        nodes,
        visualKey(
          "attr",
          `${attr.uri || attr.label}-${attr.datatype || "literal"}`,
        ),
        attr.datatype || "literal",
        "attr-value",
        attr.label,
      );
      edges.push({
        source,
        target,
        label: attr.label,
        kind: "attribute",
        optional: false,
      });
    }

    return buildGraph([...nodes.values()], mergeEdges(edges));
  }

  function buildSampleGraph(sample) {
    const nodes = new Map();
    const edges = [];

    for (const triple of sample?.triples || []) {
      const source = addNode(
        nodes,
        visualKey("entity", triple.src),
        triple.src,
      );
      if (triple.tgt == null) {
        addNode(
          nodes,
          visualKey("type", `${triple.src}-${triple.prop}`),
          triple.prop,
          "attr-value",
        );
        continue;
      }
      const isAttribute = triple.kind === "attr-triple";
      const target = addNode(
        nodes,
        isAttribute
          ? visualKey("attr", `${triple.src}-${triple.prop}-${triple.tgt}`)
          : visualKey("entity", triple.tgt),
        triple.tgt,
        isAttribute ? "attr-value" : "entity",
      );
      edges.push({
        source,
        target,
        label: triple.prop,
        kind: isAttribute ? "attribute" : "object",
        optional: triple.optional,
      });
    }

    return buildGraph([...nodes.values()], mergeEdges(edges));
  }

  function buildGraph(nodes, edges) {
    const elements = [...nodes, ...edges];
    return {
      elements,
      hasElements: nodes.length > 0,
      size: graphSize(elements),
    };
  }

  function graphSize(elements) {
    const nodes = elements.filter((element) => !element.data.source).length;
    return { nodes, edges: elements.length - nodes };
  }

  function getCyStyle() {
    return [
      {
        selector: "node",
        style: {
          shape: "round-rectangle",
          width: "data(width)",
          height: "data(height)",
          "background-color": "#f0f4ff",
          "border-color": "#adc2f5",
          "border-width": 1.6,
          label: "data(label)",
          color: "#1a2750",
          "font-size": 12,
          "font-weight": 700,
          "text-wrap": "ellipsis",
          "text-max-width": "data(width)",
          "text-valign": "center",
          "text-halign": "center",
          "overlay-opacity": 0,
        },
      },
      {
        selector: "node[kind = 'attr-value']",
        style: {
          "background-color": "#fff8ed",
          "border-color": "#f3c78d",
          color: "#8c440a",
          "font-size": 11,
          "text-max-width": 104,
        },
      },
      {
        selector: "node.node-hovered",
        style: {
          "border-color": "#2563eb",
          "border-width": 2.4,
          "z-index": 9999,
        },
      },
      {
        selector: "node[kind = 'attr-value'].node-hovered",
        style: {
          "border-color": "#d97706",
          "border-width": 2.4,
          "z-index": 9999,
        },
      },
      {
        selector: "edge",
        style: {
          width: 2.4,
          "curve-style": "bezier",
          "line-color": "#4361c4",
          "target-arrow-color": "#4361c4",
          "target-arrow-shape": "triangle",
          "arrow-scale": 0.88,
          label: "data(label)",
          color: "#223f99",
          "font-size": 11,
          "font-weight": 700,
          "text-wrap": "ellipsis",
          "text-max-width": 110,
          "text-background-color": "rgba(255, 255, 255, 0.94)",
          "text-background-opacity": 1,
          "text-background-padding": 3,
          "text-background-shape": "roundrectangle",
          "text-border-color": "#d8e1f8",
          "text-border-width": 1,
          "text-border-opacity": 1,
          "text-rotation": "autorotate",
          "overlay-opacity": 0,
        },
      },
      {
        selector: "edge[kind = 'attribute']",
        style: {
          "line-color": "#d97706",
          "target-arrow-color": "#d97706",
          color: "#92400e",
          "text-border-color": "#fde68a",
        },
      },
      {
        selector: "edge[optional = 'yes']",
        style: {
          "line-style": "dashed",
        },
      },
    ];
  }

  async function renderGraph(kind, container, graph) {
    const localToken =
      kind === "pattern" ? ++patternRenderToken : ++sampleRenderToken;
    await tick();
    const activeToken =
      kind === "pattern" ? patternRenderToken : sampleRenderToken;
    if (localToken !== activeToken || !cytoscapeLib || !container) return;

    destroyGraph(kind);
    if (!graph?.hasElements) return;

    const cy = cytoscapeLib({
      container,
      elements: graph.elements,
      style: getCyStyle(),
      layout: { name: "grid" },
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      autoungrabify: false,
      autounselectify: true,
      pixelRatio: Math.min(
        3,
        Math.max(2, Number(globalThis.devicePixelRatio || 1)),
      ),
    });

    // Handle node hover to show full text in smaller font for truncated nodes
    cy.on("mouseover", "node", (evt) => {
      const node = evt.target;
      const data = node.data();
      node.addClass("node-hovered");
      if (data.isTruncated || data.fullLabel !== data.label) {
        const bb = node.renderedBoundingBox();
        const renderedPos = node.renderedPosition();
        activeTooltip = {
          text: data.fullLabel || data.label,
          rawUri: data.rawUri && data.rawUri !== data.fullLabel ? data.rawUri : null,
          sublabel: data.sublabel || null,
          x: renderedPos.x,
          y: bb.y1 - 6,
          kind,
        };
      }
    });

    cy.on("mouseout", "node", (evt) => {
      evt.target.removeClass("node-hovered");
      activeTooltip = null;
    });

    cy.on("pan zoom drag", () => {
      activeTooltip = null;
    });

    cy.resize();
    requestAnimationFrame(() => {
      if (!cy || cy.destroyed()) return;
      const useCola = graph.size.nodes <= 24 && graph.size.edges <= 32;
      const fitGraphNow = () => {
        if (!cy || cy.destroyed()) return;
        cy.fit(cy.elements(), 32);
        cy.center(cy.elements());
      };
      const layout = useCola
        ? cy.layout({
            name: "cola",
            animate: false,
            fit: true,
            padding: 32,
            avoidOverlap: true,
            handleDisconnected: true,
            nodeDimensionsIncludeLabels: true,
            nodeSpacing: () => 32,
            edgeLength: 124,
            maxSimulationTime: 700,
            convergenceThreshold: 0.015,
            stop: fitGraphNow,
          })
        : cy.layout({
            name: "grid",
            fit: true,
            padding: 32,
            avoidOverlap: true,
            spacingFactor: 0.95,
            stop: fitGraphNow,
          });
      layout.run();
      if (!useCola) fitGraphNow();
    });

    if (kind === "pattern") patternCy = cy;
    else sampleCy = cy;
  }

  function destroyGraph(kind) {
    const target = kind === "pattern" ? patternCy : sampleCy;
    if (target) {
      try {
        target.destroy();
      } catch (_) {}
    }
    if (kind === "pattern") patternCy = null;
    else sampleCy = null;
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<div
  class="popup-backdrop"
  role="presentation"
  on:click={handleClose}
>
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="popup-dialog"
    role="dialog"
    tabindex="-1"
    aria-modal="true"
    aria-labelledby="popup-title"
    bind:this={modalContainerEl}
    on:click|stopPropagation
    on:keydown={(e) => e.stopPropagation()}
  >
    <!-- Modal Header -->
    <header class="popup-header">
      <div class="header-left">
        <div class="sg-badge-wrap">
          <span
            class="sg-color-dot"
            style="background: {currentSubgraphPaletteColor}"
            aria-hidden="true"
          ></span>
          <h3 id="popup-title">
            Subgraph {displaySubgraphId(selectedIndex)}: Pattern & Samples
          </h3>
        </div>

        {#if currentSubgraphInfo}
          {@const types = typeLabels(currentSubgraphInfo)}
          <div class="header-meta">
            {#if types.length}
              <div class="header-types">
                {#each types.slice(0, 3) as t}
                  <span class="meta-chip">{t}</span>
                {/each}
                {#if types.length > 3}
                  <span class="meta-chip more">+{types.length - 3}</span>
                {/if}
              </div>
            {/if}
            {#if currentSubgraphInfo.subgraph?.edges?.length}
              <span class="meta-stat">
                <strong>{currentSubgraphInfo.subgraph.edges.length}</strong> patterns
              </span>
            {/if}
            {#if currentSubgraphInfo.support}
              <span class="meta-stat">
                support: <strong>{currentSubgraphInfo.support}</strong>
              </span>
            {/if}
          </div>
        {/if}
      </div>

      <!-- Subgraph Switcher in Header -->
      <div class="header-center">
        {#if subgraphs.length > 1}
          <div class="sg-switcher" title="Switch between subgraphs">
            <button
              type="button"
              class="sg-nav-btn"
              disabled={!hasPrevSubgraph}
              on:click={prevSubgraph}
              aria-label="Previous subgraph"
            >
              ◀
            </button>

            <select
              class="sg-select"
              aria-label="Select subgraph"
              value={selectedIndex}
              on:change={(e) => selectSubgraphIndex(Number(e.currentTarget.value))}
            >
              {#each sortedSubgraphs as sg}
                {@const sId = displaySubgraphId(sg.index)}
                {@const sgTypes = typeLabels(sg)}
                <option value={sg.index}>
                  Subgraph {sId} ({sgTypes.slice(0, 2).join(", ") || "no types"})
                </option>
              {/each}
            </select>

            <button
              type="button"
              class="sg-nav-btn"
              disabled={!hasNextSubgraph}
              on:click={nextSubgraph}
              aria-label="Next subgraph"
            >
              ▶
            </button>
          </div>
        {/if}
      </div>

      <div class="header-right">
        <button
          class="popup-close-btn"
          type="button"
          aria-label="Close popup"
          on:click={handleClose}
        >
          ✕
        </button>
      </div>
    </header>

    <!-- Toolbar: View Switching & Sample Switching -->
    <section class="popup-toolbar">
      <!-- Layout Mode Switcher -->
      <div class="toolbar-section">
        <span class="toolbar-label">View:</span>
        <div class="mode-tabs">
          <button
            type="button"
            class="mode-btn"
            class:active={viewMode === "both"}
            on:click={() => setViewMode("both")}
            title="Show Pattern and Sample graphs side-by-side"
          >
            <span class="icon">⊞</span>
            <span>Side-by-Side</span>
          </button>
          <button
            type="button"
            class="mode-btn"
            class:active={viewMode === "pattern"}
            on:click={() => setViewMode("pattern")}
            title="Maximize Pattern graph"
          >
            <span class="icon">⬡</span>
            <span>Pattern Only</span>
          </button>
          <button
            type="button"
            class="mode-btn"
            class:active={viewMode === "sample"}
            on:click={() => setViewMode("sample")}
            title="Maximize Sample graph"
          >
            <span class="icon">◈</span>
            <span>Sample Only</span>
          </button>
        </div>
      </div>

      <!-- Sample Switcher (when samples exist and view includes sample) -->
      {#if (viewMode === "both" || viewMode === "sample") && samples.length > 0}
        <div class="toolbar-section sample-section">
          <span class="toolbar-label">Samples ({samples.length}):</span>
          <div class="sample-pills">
            <button
              type="button"
              class="sample-step-btn"
              disabled={samples.length <= 1}
              on:click={() => nextSample(-1)}
              aria-label="Previous sample"
              title="Previous sample"
            >
              ◀
            </button>
            <div class="sample-direct-list">
              {#each samples as _, idx}
                <button
                  type="button"
                  class="sample-pill-btn"
                  class:active={currentSample === idx}
                  on:click={() => selectSample(idx)}
                >
                  Sample {idx + 1}
                </button>
              {/each}
            </div>
            <button
              type="button"
              class="sample-step-btn"
              disabled={samples.length <= 1}
              on:click={() => nextSample(1)}
              aria-label="Next sample"
              title="Next sample"
            >
              ▶
            </button>
          </div>
        </div>
      {/if}
    </section>

    <!-- Main Graphs Area -->
    <main class="graphs-workspace mode-{viewMode}">
      <!-- Pattern Graph Card -->
      {#if viewMode === "both" || viewMode === "pattern"}
        <section class="graph-card">
          <header class="graph-card-header">
            <div class="graph-title-group">
              <h4>Pattern Graph</h4>
              {#if patternGraph.hasElements}
                <span class="graph-size-pill">
                  {patternGraph.size.nodes} nodes · {patternGraph.size.edges} edges
                </span>
              {/if}
            </div>

            <!-- Legend & Graph Controls -->
            <div class="graph-header-controls">
              <div class="mini-legend" aria-hidden="true">
                <span class="legend-item">
                  <span class="legend-line object"></span> object
                </span>
                <span class="legend-item">
                  <span class="legend-line attribute"></span> attribute
                </span>
                <span class="legend-item">
                  <span class="legend-line dashed"></span> optional
                </span>
              </div>
              <div class="graph-zoom-btns">
                <button
                  type="button"
                  on:click={() => fitGraph("pattern")}
                  title="Fit pattern graph"
                >
                  ⛶ Fit
                </button>
                <button
                  type="button"
                  on:click={() => zoomGraph("pattern", 1.25)}
                  title="Zoom in"
                >
                  +
                </button>
                <button
                  type="button"
                  on:click={() => zoomGraph("pattern", 0.8)}
                  title="Zoom out"
                >
                  −
                </button>
              </div>
            </div>
          </header>

          <div class="cy-wrapper">
            {#if patternGraph.hasElements}
              <div
                class="cy-canvas"
                data-graph-id={`${idPrefix}-pattern`}
                bind:this={patternContainer}
                role="img"
                aria-label="Pattern graph"
              ></div>
            {:else}
              <div class="graph-empty">
                <p>{emptyPatternText}</p>
              </div>
            {/if}

            <!-- Node hover tooltip for truncated labels -->
            {#if activeTooltip && activeTooltip.kind === "pattern"}
              <div
                class="node-hover-tooltip"
                style="left: {activeTooltip.x}px; top: {activeTooltip.y}px;"
                role="tooltip"
              >
                <div class="tooltip-text">{activeTooltip.text}</div>
                {#if activeTooltip.rawUri}
                  <div class="tooltip-uri">{activeTooltip.rawUri}</div>
                {/if}
                {#if activeTooltip.sublabel}
                  <div class="tooltip-sub">({activeTooltip.sublabel})</div>
                {/if}
              </div>
            {/if}
          </div>
        </section>
      {/if}

      <!-- Sample Graph Card -->
      {#if viewMode === "both" || viewMode === "sample"}
        <section class="graph-card">
          <header class="graph-card-header">
            <div class="graph-title-group">
              <h4>
                Sample Graph
                {#if samples.length}
                  <span class="sample-title-badge">
                    Instance #{currentSample + 1} of {samples.length}
                  </span>
                {/if}
              </h4>
              {#if sampleGraph.hasElements}
                <span class="graph-size-pill">
                  {sampleGraph.size.nodes} nodes · {sampleGraph.size.edges} edges
                </span>
              {/if}
            </div>

            <div class="graph-header-controls">
              <div class="mini-legend" aria-hidden="true">
                <span class="legend-item">
                  <span class="legend-line object"></span> entity relation
                </span>
                <span class="legend-item">
                  <span class="legend-line attribute"></span> attribute value
                </span>
              </div>
              <div class="graph-zoom-btns">
                <button
                  type="button"
                  on:click={() => fitGraph("sample")}
                  title="Fit sample graph"
                >
                  ⛶ Fit
                </button>
                <button
                  type="button"
                  on:click={() => zoomGraph("sample", 1.25)}
                  title="Zoom in"
                >
                  +
                </button>
                <button
                  type="button"
                  on:click={() => zoomGraph("sample", 0.8)}
                  title="Zoom out"
                >
                  −
                </button>
              </div>
            </div>
          </header>

          <div class="cy-wrapper">
            {#if samples.length && sampleGraph.hasElements}
              <div
                class="cy-canvas"
                data-graph-id={`${idPrefix}-sample`}
                bind:this={sampleContainer}
                role="img"
                aria-label="Sample graph instance"
              ></div>
            {:else}
              <div class="graph-empty">
                <p>{emptySamplesText}</p>
              </div>
            {/if}

            <!-- Node hover tooltip for truncated labels -->
            {#if activeTooltip && activeTooltip.kind === "sample"}
              <div
                class="node-hover-tooltip"
                style="left: {activeTooltip.x}px; top: {activeTooltip.y}px;"
                role="tooltip"
              >
                <div class="tooltip-text">{activeTooltip.text}</div>
                {#if activeTooltip.rawUri}
                  <div class="tooltip-uri">{activeTooltip.rawUri}</div>
                {/if}
                {#if activeTooltip.sublabel}
                  <div class="tooltip-sub">({activeTooltip.sublabel})</div>
                {/if}
              </div>
            {/if}
          </div>
        </section>
      {/if}
    </main>
  </div>
</div>

<style>
  /* ── Backdrop ─────────────────────────────────────────── */
  .popup-backdrop {
    position: fixed;
    inset: 0;
    z-index: 99999;
    background: rgba(15, 23, 42, 0.72);
    backdrop-filter: blur(6px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }

  /* ── Modal Dialog ─────────────────────────────────────── */
  .popup-dialog {
    background: #ffffff;
    border-radius: 14px;
    box-shadow:
      0 25px 50px -12px rgba(0, 0, 0, 0.35),
      0 0 0 1px rgba(226, 232, 240, 0.9);
    width: min(1520px, 96vw);
    height: min(92vh, 920px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: modalScaleUp 0.18s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes modalScaleUp {
    from {
      opacity: 0;
      transform: scale(0.97) translateY(8px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  /* ── Header ───────────────────────────────────────────── */
  .popup-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 22px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    flex-shrink: 0;
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }

  .sg-badge-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .sg-color-dot {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    display: inline-block;
    flex-shrink: 0;
  }

  .popup-header h3 {
    margin: 0;
    font-size: 1.12rem;
    font-weight: 700;
    color: #1e293b;
    letter-spacing: -0.01em;
  }

  .header-meta {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.8rem;
    color: #64748b;
  }

  .header-types {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .meta-chip {
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 0.74rem;
    font-weight: 600;
  }

  .meta-chip.more {
    background: #f1f5f9;
    color: #475569;
    border-color: #cbd5e1;
  }

  .meta-stat {
    font-size: 0.78rem;
    color: #64748b;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    padding: 2px 8px;
    border-radius: 5px;
  }

  .meta-stat strong {
    color: #1e293b;
    font-weight: 700;
  }

  /* Subgraph Switcher in Header */
  .header-center {
    display: flex;
    align-items: center;
  }

  .sg-switcher {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 3px 6px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  }

  .sg-nav-btn {
    width: 26px;
    height: 26px;
    display: grid;
    place-items: center;
    border: 1px solid #e2e8f0;
    border-radius: 5px;
    background: #f8fafc;
    color: #334155;
    font-size: 0.75rem;
    cursor: pointer;
    transition: all 0.12s ease;
  }

  .sg-nav-btn:hover:not(:disabled) {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1d4ed8;
  }

  .sg-nav-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .sg-select {
    border: none;
    background: transparent;
    font-size: 0.84rem;
    font-weight: 600;
    color: #1e293b;
    padding: 3px 6px;
    cursor: pointer;
    outline: none;
  }

  .header-right {
    display: flex;
    align-items: center;
  }

  .popup-close-btn {
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 6px;
    background: transparent;
    font-size: 1.25rem;
    color: #64748b;
    cursor: pointer;
    line-height: 1;
    transition: all 0.12s ease;
  }

  .popup-close-btn:hover {
    background: #f1f5f9;
    color: #0f172a;
  }

  /* ── Toolbar ──────────────────────────────────────────── */
  .popup-toolbar {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 16px;
    padding: 9px 22px;
    background: #ffffff;
    border-bottom: 1px solid #eef2f7;
    flex-shrink: 0;
  }

  .toolbar-section {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .toolbar-label {
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #64748b;
  }

  .mode-tabs {
    display: inline-flex;
    background: #f1f5f9;
    border-radius: 8px;
    padding: 3px;
    gap: 2px;
  }

  .mode-btn {
    border: none;
    background: transparent;
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 0.82rem;
    font-weight: 600;
    color: #475569;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.15s ease;
  }

  .mode-btn:hover {
    color: #0f172a;
  }

  .mode-btn.active {
    background: #ffffff;
    color: #2563eb;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .sample-section {
    margin-left: 12px;
  }

  .sample-pills {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .sample-step-btn {
    width: 26px;
    height: 26px;
    display: grid;
    place-items: center;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    background: #ffffff;
    color: #374151;
    font-size: 0.72rem;
    cursor: pointer;
    transition: all 0.12s ease;
  }

  .sample-step-btn:hover:not(:disabled) {
    background: #f3f4f6;
    color: #111827;
  }

  .sample-step-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .sample-direct-list {
    display: inline-flex;
    gap: 4px;
  }

  .sample-pill-btn {
    border: 1px solid #e5e7eb;
    background: #f9fafb;
    color: #4b5563;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.12s ease;
  }

  .sample-pill-btn:hover {
    background: #f3f4f6;
    color: #1f2937;
  }

  .sample-pill-btn.active {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1d4ed8;
    font-weight: 700;
  }

  /* ── Main Graphs Workspace ────────────────────────────── */
  .graphs-workspace {
    flex: 1;
    min-height: 0;
    display: grid;
    gap: 14px;
    padding: 14px 22px;
    background: #f8fafc;
    overflow: hidden;
  }

  .graphs-workspace.mode-both {
    grid-template-columns: 1fr 1fr;
  }

  .graphs-workspace.mode-pattern,
  .graphs-workspace.mode-sample {
    grid-template-columns: 1fr;
  }

  .graph-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-height: 0;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  }

  .graph-card-header {
    padding: 10px 14px;
    border-bottom: 1px solid #edf2f7;
    background: #fbfcfe;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-shrink: 0;
  }

  .graph-title-group {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .graph-title-group h4 {
    margin: 0;
    font-size: 0.92rem;
    font-weight: 700;
    color: #1e293b;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .sample-title-badge {
    background: #eff6ff;
    border: 1px solid #dbeafe;
    color: #2563eb;
    font-size: 0.74rem;
    padding: 1px 6px;
    border-radius: 4px;
    font-weight: 600;
  }

  .graph-size-pill {
    background: #f1f5f9;
    color: #64748b;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 4px;
  }

  .graph-header-controls {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .mini-legend {
    display: flex;
    gap: 8px;
    font-size: 0.72rem;
    font-weight: 600;
    color: #64748b;
  }

  .legend-item {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .legend-line {
    width: 14px;
    height: 3px;
    border-radius: 999px;
  }

  .legend-line.object {
    background: #4361c4;
  }

  .legend-line.attribute {
    background: #d97706;
  }

  .legend-line.dashed {
    background: #94a3b8;
    border-top: 1px dashed #64748b;
    height: 0;
  }

  .graph-zoom-btns {
    display: inline-flex;
    gap: 3px;
  }

  .graph-zoom-btns button {
    border: 1px solid #e2e8f0;
    background: #ffffff;
    color: #475569;
    font-size: 0.75rem;
    font-weight: 700;
    padding: 3px 7px;
    border-radius: 4px;
    cursor: pointer;
    line-height: 1;
    transition: all 0.12s ease;
  }

  .graph-zoom-btns button:hover {
    background: #f1f5f9;
    color: #0f172a;
  }

  .cy-wrapper {
    flex: 1;
    min-height: 0;
    position: relative;
    display: flex;
    flex-direction: column;
  }

  .cy-canvas {
    flex: 1;
    width: 100%;
    min-height: 360px;
    background: #fbfcff;
  }

  .graph-empty {
    flex: 1;
    display: grid;
    place-items: center;
    padding: 24px;
    background: #fbfcff;
    color: #94a3b8;
    font-size: 0.88rem;
    text-align: center;
  }

  /* ── Node Hover Tooltip (Full text in smaller font for truncated nodes) ── */
  .node-hover-tooltip {
    position: absolute;
    transform: translate(-50%, -100%);
    background: rgba(15, 23, 42, 0.94);
    backdrop-filter: blur(4px);
    color: #f8fafc;
    padding: 5px 9px;
    border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
    pointer-events: none;
    max-width: 320px;
    word-break: break-all;
    text-align: center;
    z-index: 100;
    animation: tooltipFadeIn 0.12s ease-out;
    white-space: normal;
  }

  .node-hover-tooltip::after {
    content: "";
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border-width: 5px;
    border-style: solid;
    border-color: rgba(15, 23, 42, 0.94) transparent transparent transparent;
  }

  .tooltip-text {
    font-size: 0.72rem;
    font-weight: 600;
    color: #f1f5f9;
    line-height: 1.35;
  }

  .tooltip-uri {
    font-size: 0.65rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    color: #93c5fd;
    margin-top: 2px;
    opacity: 0.9;
  }

  .tooltip-sub {
    font-size: 0.65rem;
    color: #cbd5e1;
    margin-top: 2px;
  }

  @keyframes tooltipFadeIn {
    from {
      opacity: 0;
      transform: translate(-50%, -95%);
    }
    to {
      opacity: 1;
      transform: translate(-50%, -100%);
    }
  }

  /* ── Responsive adjustments ───────────────────────────── */
  @media (max-width: 900px) {
    .graphs-workspace.mode-both {
      grid-template-columns: 1fr;
      grid-template-rows: 1fr 1fr;
    }

    .header-left {
      flex-direction: column;
      align-items: flex-start;
      gap: 4px;
    }
  }
</style>
