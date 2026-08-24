<script>
    import { onDestroy, onMount, tick } from "svelte";
    import { isUri, uriFallbackLabel } from "../graph.js";

    export let properties = [];
    export let attributes = [];
    export let samples = [];
    export let emptyPatternText = "No pattern details yet.";
    export let emptySamplesText =
        "No samples could be formed for this subgraph.";
    export let idPrefix = "mini-subgraph";

    let currentSample = 0;
    let patternContainer;
    let sampleContainer;
    let cytoscapeLib = null;
    let patternCy = null;
    let sampleCy = null;
    let patternRenderToken = 0;
    let sampleRenderToken = 0;

    const GRAPH_HEIGHT = 260;
    const NODE_W = 118;
    const NODE_H = 42;
    const ATTR_W = 106;
    const ATTR_H = 34;

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
            // already registered by another graph component
        }
        cytoscapeLib = cytoscape;
    });

    onDestroy(() => {
        destroyGraph("pattern");
        destroyGraph("sample");
    });

    $: if (currentSample >= samples.length) {
        currentSample = Math.max(0, samples.length - 1);
    }

    $: patternGraph = buildPatternGraph(properties, attributes);
    $: sampleGraph = buildSampleGraph(samples[currentSample]);
    $: patternHasHiddenUris = patternContainsUri(properties, attributes);
    $: sampleHasHiddenUris = sampleContainsUri(samples[currentSample]);

    $: if (cytoscapeLib && patternContainer && patternGraph) {
        renderMiniGraph("pattern", patternContainer, patternGraph);
    }

    $: if (cytoscapeLib && sampleContainer && sampleGraph) {
        renderMiniGraph("sample", sampleContainer, sampleGraph);
    }

    function nextSample(offset) {
        if (!samples.length) return;
        currentSample =
            (currentSample + offset + samples.length) % samples.length;
    }

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

    function valueHasUri(value) {
        const text = String(value || "").trim();
        return isUri(text) || text.startsWith("uri:");
    }

    function anyValueHasUri(values) {
        return values.some(valueHasUri);
    }

    function patternContainsUri(objectEdges, attrEdges) {
        return (
            (objectEdges || []).some((edge) =>
                anyValueHasUri([
                    edge.sourceUri,
                    edge.targetUri,
                    edge.uri,
                    edge.source,
                    edge.target,
                    edge.label,
                ]),
            ) ||
            (attrEdges || []).some((attr) =>
                anyValueHasUri([
                    attr.typeUri,
                    attr.uri,
                    attr.typeLabel,
                    attr.label,
                    attr.datatype,
                ]),
            )
        );
    }

    function sampleContainsUri(sample) {
        return (sample?.triples || []).some((triple) =>
            anyValueHasUri([triple.src, triple.prop, triple.tgt]),
        );
    }

    function addNode(nodes, id, label, kind = "entity", sublabel = "") {
        const key = String(id || label || `node-${nodes.size}`);
        if (!nodes.has(key)) {
            nodes.set(key, {
                data: {
                    id: key,
                    label: displayLabel(label, kind === "attr-value" ? 22 : 26),
                    fullLabel: String(uriFallbackLabel(label) || label || key),
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
                    ? visualKey(
                          "attr",
                          `${triple.src}-${triple.prop}-${triple.tgt}`,
                      )
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

    function getCyStyle(compactPanel = false) {
        const nodeFontSize = compactPanel ? 14 : 11;
        const attrFontSize = compactPanel ? 12 : 10;
        const edgeFontSize = compactPanel ? 13 : 10;
        const edgeLabelWidth = compactPanel ? 120 : 92;
        return [
            {
                selector: "node",
                style: {
                    shape: "round-rectangle",
                    width: "data(width)",
                    height: "data(height)",
                    "background-color": "#eef3ff",
                    "border-color": "#b8c7ef",
                    "border-width": 1.4,
                    label: "data(label)",
                    color: "#1f2a4a",
                    "font-size": nodeFontSize,
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
                    "background-color": "#fff7ed",
                    "border-color": "#edc08a",
                    color: "#9a5318",
                    "font-size": attrFontSize,
                    "text-max-width": 94,
                },
            },
            {
                selector: "edge",
                style: {
                    width: compactPanel ? 3 : 2.3,
                    "curve-style": "bezier",
                    "line-color": "#4968c7",
                    "target-arrow-color": "#4968c7",
                    "target-arrow-shape": "triangle",
                    "arrow-scale": compactPanel ? 0.95 : 0.82,
                    label: "data(label)",
                    color: "#284aa8",
                    "font-size": edgeFontSize,
                    "font-weight": 700,
                    "text-wrap": "ellipsis",
                    "text-max-width": edgeLabelWidth,
                    "text-background-color": "rgba(251, 252, 255, 0.96)",
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
                    "line-color": "#d4812f",
                    "target-arrow-color": "#d4812f",
                    color: "#9a5318",
                    "text-border-color": "#f0cc9f",
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

    async function renderMiniGraph(kind, container, graph) {
        const localToken =
            kind === "pattern" ? ++patternRenderToken : ++sampleRenderToken;
        await tick();
        const activeToken =
            kind === "pattern" ? patternRenderToken : sampleRenderToken;
        if (localToken !== activeToken || !cytoscapeLib || !container) return;

        destroyGraph(kind);
        if (!graph?.hasElements) return;
        const rect = container.getBoundingClientRect();
        const compactPanel = rect.width < 520;

        const cy = cytoscapeLib({
            container,
            elements: graph.elements,
            style: getCyStyle(compactPanel),
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

        cy.resize();
        requestAnimationFrame(() => {
            if (!cy || cy.destroyed()) return;
            const useCola = graph.size.nodes <= 14 && graph.size.edges <= 18;
            const fitGraph = () => {
                if (!cy || cy.destroyed()) return;
                const padding = compactPanel ? 8 : 28;
                cy.fit(cy.elements(), padding);
                cy.center(cy.elements());
            };
            const layout = useCola
                ? cy.layout({
                      name: "cola",
                      animate: false,
                      fit: true,
                      padding: compactPanel ? 8 : 28,
                      avoidOverlap: true,
                      handleDisconnected: true,
                      nodeDimensionsIncludeLabels: true,
                      nodeSpacing: () => (compactPanel ? 18 : 28),
                      edgeLength: compactPanel ? 96 : 118,
                      maxSimulationTime: 650,
                      convergenceThreshold: 0.02,
                      stop: fitGraph,
                  })
                : cy.layout({
                      name: "grid",
                      fit: true,
                      padding: compactPanel ? 8 : 28,
                      avoidOverlap: true,
                      spacingFactor: compactPanel ? 0.82 : 0.95,
                      stop: fitGraph,
                  });
            layout.run();
            if (!useCola) fitGraph();
        });

        if (kind === "pattern") patternCy = cy;
        else sampleCy = cy;
    }

    function destroyGraph(kind) {
        const target = kind === "pattern" ? patternCy : sampleCy;
        if (target) target.destroy();
        if (kind === "pattern") patternCy = null;
        else sampleCy = null;
    }
</script>

<div class="mini-graphs">
    <section class="mini-panel">
        <div class="mini-head">
            <h5>Pattern</h5>
            <div class="mini-legend" aria-hidden="true">
                <span class="legend-item"
                    ><span class="legend-line object"></span> object</span
                >
                <span class="legend-item"
                    ><span class="legend-line attribute"></span> attribute</span
                >
            </div>
        </div>

        {#if patternGraph.hasElements}
            <div
                class="mini-cy"
                data-graph-id={`${idPrefix}-pattern`}
                bind:this={patternContainer}
                role="img"
                aria-label="Pattern graph"
            ></div>
            {#if patternHasHiddenUris}
                <p class="uri-note">Full URIs are hidden for clarity.</p>
            {/if}
        {:else}
            <p class="mini-empty">{emptyPatternText}</p>
        {/if}
    </section>

    <section class="mini-panel">
        <div class="mini-head">
            <h5>Samples</h5>
            {#if samples.length > 1}
                <div class="sample-nav">
                    <button
                        type="button"
                        on:click={() => nextSample(-1)}
                        aria-label="Previous sample">&lt;</button
                    >
                    <span>{currentSample + 1} / {samples.length}</span>
                    <button
                        type="button"
                        on:click={() => nextSample(1)}
                        aria-label="Next sample">&gt;</button
                    >
                </div>
            {:else if samples.length === 1}
                <span class="sample-count">1 / 1</span>
            {/if}
        </div>

        {#if samples.length && sampleGraph.hasElements}
            <div
                class="mini-cy"
                data-graph-id={`${idPrefix}-sample`}
                bind:this={sampleContainer}
                role="img"
                aria-label="Sample instance graph"
            ></div>
            {#if sampleHasHiddenUris}
                <p class="uri-note">Full URIs are hidden for clarity.</p>
            {/if}
        {:else}
            <p class="mini-empty">{emptySamplesText}</p>
        {/if}
    </section>
</div>

<style>
    .mini-graphs {
        container-type: inline-size;
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(min(390px, 100%), 1fr));
        gap: 12px;
    }

    .mini-panel {
        border: 1px solid #e4e8f4;
        border-radius: 8px;
        background: #fff;
        min-width: 0;
        overflow: hidden;
    }

    .mini-head {
        min-height: 38px;
        padding: 8px 10px;
        border-bottom: 1px solid #e8ecf6;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
    }

    h5 {
        margin: 0;
        color: #24335f;
        font-size: 0.8rem;
    }

    .mini-legend {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
        color: #66708a;
        font-size: 0.68rem;
        font-weight: 700;
    }

    .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }

    .legend-line {
        width: 16px;
        height: 2px;
        display: inline-block;
        border-radius: 999px;
    }

    .legend-line.object {
        background: #4968c7;
    }

    .legend-line.attribute {
        background: #d4812f;
    }

    .sample-nav,
    .sample-count {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        color: #66708a;
        font-size: 0.72rem;
        font-weight: 800;
    }

    .sample-nav button {
        width: 24px;
        height: 24px;
        border: 1px solid #d8deed;
        border-radius: 6px;
        background: #fff;
        color: #2e3d72;
        cursor: pointer;
        font-weight: 800;
    }

    .sample-nav button:hover {
        background: #f4f6fb;
    }

    .mini-cy {
        width: 100%;
        height: 260px;
        background: #fbfcff;
    }

    .uri-note {
        margin: 0;
        border-top: 1px solid #eef1f7;
        padding: 5px 10px 6px;
        background: #fbfcff;
        color: #7c86a0;
        font-size: 0.68rem;
        font-weight: 700;
        line-height: 1.25;
    }

    @container (max-width: 520px) {
        .mini-cy {
            height: 360px;
        }

        .mini-empty {
            min-height: 360px;
        }
    }

    .mini-empty {
        margin: 0;
        min-height: 260px;
        display: grid;
        place-items: center;
        padding: 16px;
        color: #7c86a0;
        font-size: 0.8rem;
        text-align: center;
        background: #fbfcff;
    }

    @media (max-width: 920px) {
        .mini-graphs {
            grid-template-columns: 1fr;
        }
    }
</style>
