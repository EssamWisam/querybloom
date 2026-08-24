<script>
  import { onDestroy, onMount, tick } from "svelte";
  import {
    edgeKey,
    normalizeGraph,
    subgraphEdgeKeys,
    subgraphNodeIds,
    SUBGRAPH_PALETTE,
  } from "../graph.js";

  export let graph = null;
  export let subgraphs = [];
  export let selectedIndex = null;
  export let onNodeClick = null;
  export let preferGridLayout = false;
  export let useCyanNodeFocus = false;

  let containerEl;
  let cy = null;
  let cytoscapeLib = null;
  let mounted = false;
  let savedPositions = new Map();
  let savedPan = null;
  let savedZoom = null;
  let resizeObserver = null;
  let layoutName = "cola";
  let selectedNodeId = null;
  let renderInProgress = false;
  let renderAgain = false;
  let renderedGraphRef = null;
  let lastContainerWidth = 0;
  let lastContainerHeight = 0;

  const MAX_NODE_LABEL_LENGTH = 28;
  const MAX_EDGE_LABEL_LENGTH = 20;
  const CYAN_FOCUS_COLOR = "#06b6d4";

  onMount(async () => {
    const [cytoscapeMod, colaMod] = await Promise.all([
      import("cytoscape"),
      import("cytoscape-cola"),
    ]);
    const cytoscape = cytoscapeMod.default ?? cytoscapeMod;
    const cola = colaMod.default ?? colaMod;
    try {
      cytoscape.use(cola);
      layoutName = "cola";
    } catch (_) {
      layoutName = "cola"; // already registered
    }
    cytoscapeLib = cytoscape;
    mounted = true;
  });

  function selectedSubgraph() {
    return subgraphs.find((item) => item.index === selectedIndex) || null;
  }

  function selectedMembership() {
    const entry = selectedSubgraph();
    if (!entry) return { nodeIds: null, edgeKeys: null };
    return {
      nodeIds: subgraphNodeIds(entry),
      edgeKeys: subgraphEdgeKeys(entry),
    };
  }

  function truncateLabel(label, maxLength = MAX_NODE_LABEL_LENGTH) {
    const value = String(label || "").trim();
    if (!value) return "";
    if (value.length <= maxLength) return value;
    return `${value.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
  }

  function nodeWidth(label) {
    return Math.max(80, Math.min(220, 28 + truncateLabel(label).length * 7));
  }

  function supportSize(support) {
    const value = Number(support || 1);
    return Math.max(1, Math.min(3.2, 1 + Math.log10(value + 1) * 0.7));
  }

  function saveCyPositions() {
    if (!cy) return;
    cy.nodes().forEach((node) => {
      const pos = node.position();
      savedPositions.set(node.id(), { x: pos.x, y: pos.y });
    });
    savedPan = cy.pan();
    savedZoom = cy.zoom();
  }

  function buildElements() {
    const elements = normalizeGraph(graph);
    const total = elements.nodes.length;

    const nodes = elements.nodes.map((node, index) => {
      const data = node.data || {};
      const id = String(data.id);
      const label = truncateLabel(data.label || id, MAX_NODE_LABEL_LENGTH);
      const w = nodeWidth(label);
      const saved = savedPositions.get(id);
      const angle = (Math.PI * 2 * index) / Math.max(1, total);
      const radius = 80 * (2 + Math.sqrt(total) * 0.7);
      const position = saved || {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      };

      return {
        group: "nodes",
        data: { id, label, width: w, rawData: data },
        position,
      };
    });

    const edges = elements.edges.map((edge, index) => {
      const data = edge.data || {};
      const source = String(data.source || "");
      const target = String(data.target || "");
      const predicate = data.predicate || data.uri;
      const id = String(
        data.id || edgeKey(source, predicate, target) || `edge-${index}`,
      );
      const label = truncateLabel(
        data.label || predicate || "",
        MAX_EDGE_LABEL_LENGTH,
      );
      const weight = supportSize(data.support);

      return {
        group: "edges",
        data: { id, source, target, label, weight, rawData: data },
      };
    });

    return [...nodes, ...edges];
  }

  function applyNodeHighlight() {
    if (!cy) return;
    cy.elements().removeClass("pinned adj-edge adj-node");

    if (!selectedNodeId) {
      if (selectedIndex === null) cy.nodes().forEach((n) => n.removeStyle());
      return;
    }

    cy.nodes().forEach((n) => n.removeStyle());
    const node = cy.getElementById(selectedNodeId);
    if (!node || !node.length) return;
    node.addClass("pinned");

    if (useCyanNodeFocus) {
      const neighborhood = node.closedNeighborhood();
      const neighborNodeIds = new Set(
        neighborhood.nodes().map((neighbor) => neighbor.id()),
      );
      const connectedEdgeIds = new Set(
        neighborhood.edges().map((edge) => edge.id()),
      );

      cy.nodes().forEach((currentNode) => {
        if (neighborNodeIds.has(currentNode.id())) {
          currentNode.style({
            "background-color": CYAN_FOCUS_COLOR,
            color: "white",
            "font-weight": 700,
            "border-color": CYAN_FOCUS_COLOR,
            "border-width": currentNode.id() === selectedNodeId ? 3 : 2,
            opacity: 1,
          });
        } else {
          currentNode.style({ opacity: 0.22 });
        }
      });

      cy.edges().forEach((edge) => {
        if (connectedEdgeIds.has(edge.id())) {
          edge.style({
            "line-color": CYAN_FOCUS_COLOR,
            "target-arrow-color": CYAN_FOCUS_COLOR,
            color: "white",
            "text-background-color": CYAN_FOCUS_COLOR,
            "text-background-opacity": 1,
            "text-border-color": CYAN_FOCUS_COLOR,
            "text-border-opacity": 1,
            "text-border-width": 1,
            "font-weight": 700,
            width: 2.8,
            opacity: 1,
          });
        } else {
          edge.style({ opacity: 0.14 });
        }
      });
      return;
    }

    const relevant = subgraphs.filter((entry) =>
      subgraphNodeIds(entry).has(selectedNodeId),
    );
    if (!relevant.length) return;

    cy.nodes().forEach((n) => {
      const nid = n.id();
      const memberEntries = relevant.filter((entry) =>
        subgraphNodeIds(entry).has(nid),
      );

      if (!memberEntries.length) {
        n.style({ opacity: 0.25 });
        return;
      }

      const colors = memberEntries
        .slice(0, 8)
        .map(
          (entry) => SUBGRAPH_PALETTE[entry.index % SUBGRAPH_PALETTE.length],
        );
      const count = colors.length;

      const baseStyle = { color: "white", "font-weight": 700, opacity: 1 };

      if (count === 1) {
        n.style({ ...baseStyle, "background-color": colors[0] });
      } else {
        const sliceSize = 100 / count;
        const stopColors = [];
        const stopPositions = [];
        colors.forEach((color, i) => {
          stopColors.push(color, color);
          stopPositions.push(i * sliceSize, (i + 1) * sliceSize);
        });
        n.style({
          ...baseStyle,
          "background-fill": "linear-gradient",
          "background-gradient-stop-colors": stopColors.join(" "),
          "background-gradient-stop-positions": stopPositions.join(" "),
          "background-gradient-direction": "to-right",
        });
      }
    });
  }

  function allSubgraphMembership() {
    const allNodeIds = new Set();
    const allEdgeKeys = new Set();
    for (const entry of subgraphs) {
      for (const id of subgraphNodeIds(entry)) allNodeIds.add(id);
      for (const key of subgraphEdgeKeys(entry)) allEdgeKeys.add(key);
    }
    return { allNodeIds, allEdgeKeys };
  }

  function applyAllSubgraphsHighlight() {
    if (!cy) return;
    cy.elements().removeClass("subgraphed");
    if (!subgraphs.length) return;
    const { allNodeIds, allEdgeKeys } = allSubgraphMembership();
    cy.nodes().forEach((node) => {
      if (allNodeIds.has(node.id())) node.addClass("subgraphed");
    });
    cy.edges().forEach((edge) => {
      const pred = edge.data("rawData")?.predicate || edge.data("rawData")?.uri;
      const key = edgeKey(edge.source().id(), pred, edge.target().id());
      if (allEdgeKeys.has(key)) edge.addClass("subgraphed");
    });
  }

  function applySubgraphHighlight() {
    if (!cy) return;
    cy.elements().forEach((el) => el.removeStyle());
    cy.elements().removeClass("selected inactive");

    const entry = selectedSubgraph();
    if (!entry) return;

    const { nodeIds, edgeKeys: eKeys } = selectedMembership();
    if (!nodeIds) return;

    const color = SUBGRAPH_PALETTE[entry.index % SUBGRAPH_PALETTE.length];

    cy.nodes().forEach((node) => {
      if (nodeIds.has(node.id())) {
        node.addClass("selected");
        node.style({
          "background-color": color,
          color: "white",
          "font-weight": 700,
          "border-color": color,
          "border-width": 2,
          opacity: 1,
        });
      } else {
        node.addClass("inactive");
        node.style({ opacity: 0.2 });
      }
    });

    cy.edges().forEach((edge) => {
      const src = edge.source().id();
      const tgt = edge.target().id();
      const pred = edge.data("rawData")?.predicate || edge.data("rawData")?.uri;
      const key = edgeKey(src, pred, tgt);
      if (eKeys && eKeys.has(key)) {
        edge.addClass("selected");
        edge.style({
          "line-color": color,
          "target-arrow-color": color,
          color: "white",
          "text-background-color": color,
          "text-background-opacity": 1,
          "text-border-color": color,
          "text-border-opacity": 1,
          "text-border-width": 1,
          "font-weight": 700,
          width: 2.6,
          opacity: 1,
        });
      } else {
        edge.addClass("inactive");
        edge.style({ opacity: 0.12 });
      }
    });
  }

  function applyFreshHighlight() {
    if (!cy) return;
    cy.elements().removeClass("fresh");
    if (selectedIndex !== null) return;
    const freshNodeIds = new Set((graph?.freshNodeIds || []).map(String));
    const freshEdgeKeys = new Set((graph?.freshEdgeKeys || []).map(String));

    if (freshNodeIds.size || freshEdgeKeys.size) {
      cy.nodes().forEach((node) => {
        if (freshNodeIds.has(node.id())) node.addClass("fresh");
      });
      cy.edges().forEach((edge) => {
        const pred =
          edge.data("rawData")?.predicate || edge.data("rawData")?.uri;
        const key = edgeKey(edge.source().id(), pred, edge.target().id());
        if (freshEdgeKeys.has(key)) edge.addClass("fresh");
      });
      return;
    }

    if (!graph?.latestProperty) return;
    const latestProp = graph.latestProperty;
    cy.edges().forEach((edge) => {
      const pred = edge.data("rawData")?.predicate || edge.data("rawData")?.uri;
      if (pred === latestProp) {
        edge.addClass("fresh");
        edge.source().addClass("fresh");
        edge.target().addClass("fresh");
      }
    });
  }

  function getCyStyle() {
    return [
      {
        selector: "node",
        style: {
          shape: "round-rectangle",
          width: "data(width)",
          height: 34,
          "background-color": "#fbfcff",
          "border-color": "rgba(111, 127, 166, 0.55)",
          "border-width": 1,
          label: "data(label)",
          "text-valign": "center",
          "text-halign": "center",
          "font-size": 12,
          "font-weight": 600,
          color: "#17244d",
          "text-max-width": "data(width)",
          "text-wrap": "ellipsis",
        },
      },
      {
        selector: "node.subgraphed",
        style: {
          "border-color": "rgba(79, 95, 140, 0.9)",
          "border-width": 1.8,
          "background-color": "rgba(31, 41, 71, 0.55)",
          "font-weight": 700,
          color: "white",
        },
      },
      {
        selector: "edge.subgraphed",
        style: {
          "line-color": "#4a5a7a",
          "target-arrow-color": "#4a5a7a",
          color: "#2a3650",
          "font-weight": 600,
        },
      },
      {
        selector: "node.selected",
        style: {
          "border-width": 2,
          "font-weight": 700,
        },
      },
      {
        selector: "node.inactive",
        style: {
          "border-color": "rgba(216, 221, 234, 0.85)",
          "background-color": "rgba(251, 252, 255, 0.72)",
          opacity: 0.52,
        },
      },
      {
        selector: "node.subgraphed.inactive",
        style: {
          "border-color": "rgba(79, 95, 140, 0.7)",
          "background-color": "rgba(31, 41, 71, 0.38)",
          opacity: 0.82,
          color: "rgba(255,255,255,0.85)",
        },
      },
      {
        selector: "edge",
        style: {
          width: "data(weight)",
          "line-color": "#8b9baf",
          "target-arrow-color": "#8b9baf",
          "target-arrow-shape": "vee",
          "arrow-scale": 1,
          "curve-style": "bezier",
          label: "data(label)",
          "font-size": 10,
          color: "#44516f",
          "text-rotation": "autorotate",
          "text-background-color": "rgba(251, 252, 255, 0.94)",
          "text-background-opacity": 1,
          "text-background-padding": "3px",
          "text-background-shape": "roundrectangle",
          "text-max-width": "80px",
          "text-wrap": "ellipsis",
        },
      },
      {
        selector: "edge.selected",
        style: {
          "font-weight": 700,
        },
      },
      {
        selector: "edge.inactive",
        style: {
          "line-color": "rgba(216, 221, 234, 0.9)",
          "target-arrow-color": "rgba(216, 221, 234, 0.9)",
          opacity: 0.42,
        },
      },
      {
        selector: "edge.subgraphed.inactive",
        style: {
          "line-color": "#6a7a9a",
          "target-arrow-color": "#6a7a9a",
          color: "#3a4a6a",
          opacity: 0.75,
        },
      },
      {
        selector: "node.fresh",
        style: {
          "border-color": "#00c07a",
          "border-width": 2,
          "background-color": "rgba(0, 192, 122, 0.09)",
        },
      },
      {
        selector: "edge.fresh",
        style: {
          "line-color": "#00c07a",
          "target-arrow-color": "#00c07a",
          color: "#007a4d",
        },
      },
      {
        selector: "node.pinned",
        style: {
          "border-color": "#1a202c",
          "border-width": 3.5,
          "font-weight": 700,
        },
      },
    ];
  }

  function observeResize() {
    if (resizeObserver || !containerEl) return;
    resizeObserver = new ResizeObserver(() => {
      if (!cy) return;
      const rect = containerEl.getBoundingClientRect();
      const previousHeight = lastContainerHeight;
      const previousWidth = lastContainerWidth;
      lastContainerWidth = rect.width;
      lastContainerHeight = rect.height;
      const grewFromCollapsed =
        previousHeight > 0 &&
        previousHeight < 180 &&
        rect.height >= 240 &&
        rect.width >= 240;
      const firstMeaningfulSize =
        (!previousHeight || !previousWidth) && rect.height >= 240 && rect.width >= 240;
      requestAnimationFrame(() => {
        if (!cy) return;
        cy.resize();
        if (grewFromCollapsed || firstMeaningfulSize) {
          cy.fit(cy.elements(), 40);
          saveCyPositions();
        }
      });
    });
    resizeObserver.observe(containerEl);
  }

  function graphSize(elements) {
    const nodes = elements.filter((el) => el.group === "nodes").length;
    const edges = elements.length - nodes;
    return { nodes, edges };
  }

  async function renderGraph() {
    if (!mounted || !containerEl || !graph) return;
    if (renderInProgress) {
      renderAgain = true;
      return;
    }
    if (graph === renderedGraphRef && cy) return;

    renderInProgress = true;
    await tick();

    try {
      const cytoscape = cytoscapeLib;
      if (!cytoscape) return;

      const isFirstRender = savedPositions.size === 0;
      saveCyPositions();
      if (cy) {
        cy.destroy();
        cy = null;
      }

      const elements = buildElements();
      if (!elements.length) return;
      const size = graphSize(elements);

      const hasNewNodes = elements.some(
        (el) => el.group === "nodes" && !savedPositions.has(el.data.id),
      );

      cy = cytoscape({
        container: containerEl,
        elements,
        style: getCyStyle(),
        userZoomingEnabled: true,
        userPanningEnabled: true,
        boxSelectionEnabled: false,
      });

      cy.resize();

      if (!isFirstRender && !hasNewNodes && savedPan && savedZoom) {
        cy.viewport({ zoom: savedZoom, pan: { x: savedPan.x, y: savedPan.y } });
      }

      cy.on("tap", "node", (e) => {
        const nodeId = e.target.id();
        if (selectedNodeId === nodeId) {
          selectedNodeId = null;
          onNodeClick?.(null);
          applyAllSubgraphsHighlight();
          applySubgraphHighlight();
          applyFreshHighlight();
        } else {
          selectedNodeId = nodeId;
          const rawData = e.target.data("rawData") || {};
          const connected = e.target.connectedEdges();
          const outEdges = connected
            .filter((ed) => ed.source().id() === nodeId)
            .map((ed) => ({
              direction: "out",
              predicate: ed.data("label"),
              predicateUri: ed.data("rawData")?.predicate,
              neighbor: ed.target().data("label"),
              neighborUri: ed.target().data("rawData")?.uri,
              support: ed.data("rawData")?.support,
            }));
          const inEdges = connected
            .filter((ed) => ed.target().id() === nodeId)
            .map((ed) => ({
              direction: "in",
              predicate: ed.data("label"),
              predicateUri: ed.data("rawData")?.predicate,
              neighbor: ed.source().data("label"),
              neighborUri: ed.source().data("rawData")?.uri,
              support: ed.data("rawData")?.support,
            }));
          onNodeClick?.({
            id: nodeId,
            label: e.target.data("label"),
            uri: rawData.uri || nodeId,
            outEdges,
            inEdges,
          });
        }
        applyNodeHighlight();
      });

      cy.on("tap", (e) => {
        if (e.target === cy) {
          selectedNodeId = null;
          onNodeClick?.(null);
          applyAllSubgraphsHighlight();
          applySubgraphHighlight();
          applyFreshHighlight();
          applyNodeHighlight();
        }
      });

      const runLayout = () => {
        if (!cy) return;
        const shouldFit = isFirstRender || hasNewNodes;
        const isLargeGraph = size.nodes > 80 || size.edges > 180;
        const useGridLayout = preferGridLayout || isLargeGraph || subgraphs.length > 0;
        if (useGridLayout) {
          cy.layout({
            name: "grid",
            fit: shouldFit,
            padding: 40,
            avoidOverlap: true,
            spacingFactor: 1.15,
          }).run();
          saveCyPositions();
          applyFreshHighlight();
          applyNodeHighlight();
          return;
        }
        try {
          cy.layout({
            name: layoutName,
            animate: false,
            nodeSpacing: 28,
            edgeLength: 220,
            randomize: isFirstRender,
            fit: shouldFit,
            padding: 40,
            maxSimulationTime: 650,
            convergenceThreshold: 0.02,
            ungrabifyWhileSimulating: false,
            stop: () => {
              saveCyPositions();
              applyFreshHighlight();
              applyNodeHighlight();
            },
          }).run();
        } catch (e) {
          if (!cy) return;
          cy.layout({
            name: "cose",
            animate: false,
            fit: shouldFit,
            padding: 40,
          }).run();
        }
      };
      requestAnimationFrame(runLayout);

      applyAllSubgraphsHighlight();
      applySubgraphHighlight();
      applyFreshHighlight();
      applyNodeHighlight();
      observeResize();
      renderedGraphRef = graph;
    } finally {
      renderInProgress = false;
      if (renderAgain) {
        renderAgain = false;
        renderGraph();
      }
    }
  }

  $: if (mounted && graph) renderGraph();
  $: if (cy && (subgraphs || selectedIndex !== undefined)) {
    applyAllSubgraphsHighlight();
    applySubgraphHighlight();
    applyFreshHighlight();
    applyNodeHighlight();
  }

  onDestroy(() => {
    if (resizeObserver) resizeObserver.disconnect();
    if (cy) cy.destroy();
  });
</script>

<div class="graph-shell">
  <div class="graph-canvas" bind:this={containerEl}></div>
  {#if graph?.latestProperty}
    <p class="graph-note">● Green = most recently added property</p>
  {/if}
</div>

<style>
  .graph-shell {
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: grid;
    grid-template-rows: minmax(0, 1fr) auto;
    background: #fbfcff;
  }

  .graph-canvas {
    width: 100%;
    height: 100%;
    min-height: 0;
    background: #fbfcff;
  }

  .graph-note {
    margin: 4px 8px 2px;
    font-size: 11px;
    color: #00a06a;
    font-weight: 600;
  }
</style>
