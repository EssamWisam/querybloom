// One stable color per subgraph slot — shared by graph and sidebar
export const SUBGRAPH_PALETTE = [
  "#e05c5c", // red
  "#3cb87a", // green
  "#e0a430", // amber
  "#a45ce0", // purple
  "#e05c9a", // pink
  "#4ab8c8", // teal
  "#c8864a", // orange
  "#5c7de0", // indigo
];

export function shortName(uri) {
  if (!uri) return "";
  const value = String(uri).replace(/[/>]+$/, "");
  if (value.includes("#")) return value.split("#").pop();
  return value.split("/").pop();
}

export function isUri(value) {
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(String(value || "").trim());
}

export function uriFallbackLabel(value) {
  if (!isUri(value)) return "";
  const name = shortName(value);
  return name ? `uri:${name}` : String(value || "");
}

export function normalizeGraph(graph) {
  const nodes = graph?.elements?.nodes || graph?.nodes || [];
  const edges = graph?.elements?.edges || graph?.edges || [];
  return {
    nodes: nodes.map((node, index) => ({
      data: {
        id: node?.data?.id || node?.id || `node-${index}`,
        label: node?.data?.label || uriFallbackLabel(node?.data?.uri || node?.data?.id || node?.id) || shortName(node?.data?.uri || node?.data?.id || node?.id),
        uri: node?.data?.uri || node?.data?.id || node?.id,
        kind: node?.data?.kind || "type",
        ...node?.data,
      },
    })),
    edges: edges.map((edge, index) => ({
      data: {
        id: edge?.data?.id || edge?.id || `edge-${index}`,
        source: edge?.data?.source || edge?.source,
        target: edge?.data?.target || edge?.target,
        predicate: edge?.data?.predicate || edge?.data?.uri || edge?.predicate,
        label: edge?.data?.label || uriFallbackLabel(edge?.data?.predicate || edge?.data?.uri || edge?.predicate) || shortName(edge?.data?.predicate || edge?.data?.uri || edge?.predicate),
        uri: edge?.data?.uri || edge?.data?.predicate || edge?.predicate,
        support: edge?.data?.support ?? edge?.support,
        ...edge?.data,
      },
    })),
  };
}

export function edgeKey(subject, predicate, object) {
  return `${subject || ""}|${predicate || ""}|${object || ""}`;
}

export function subgraphNodeIds(entry) {
  const ids = new Set();
  const graphNodes = entry?.graph?.elements?.nodes || entry?.graph?.nodes || [];
  for (const node of graphNodes) ids.add(node?.data?.id || node?.id);
  const types = entry?.subgraph?.types;
  if (Array.isArray(types)) {
    for (const typeUri of types) ids.add(typeUri);
  } else if (types && typeof types === "object") {
    for (const typeUri of Object.keys(types)) ids.add(typeUri);
  }
  return ids;
}

export function subgraphEdgeKeys(entry) {
  const keys = new Set();
  const graphEdges = entry?.graph?.elements?.edges || entry?.graph?.edges || [];
  for (const edge of graphEdges) {
    const data = edge?.data || edge || {};
    keys.add(edgeKey(data.source, data.predicate || data.uri, data.target));
  }
  for (const edge of entry?.subgraph?.edges || []) {
    keys.add(edgeKey(edge.s, edge.p, edge.o));
  }
  return keys;
}

export function upsertSubgraph(list, next) {
  if (!next) return list;
  const rawIdx = next.index ?? next.subgraph_index;
  const index = Number.isFinite(Number(rawIdx)) ? Number(rawIdx) : list.length;
  const existingIdx = list.findIndex((item) => Number(item.index) === index);
  if (existingIdx === -1) {
    return [...list, { ...next, index }].sort((a, b) => Number(a.index) - Number(b.index));
  }
  const copy = [...list];
  copy[existingIdx] = { ...copy[existingIdx], ...next, index };
  return copy;
}
