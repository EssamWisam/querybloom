import { shortName, uriFallbackLabel } from "./graph.js";

export function isV5Subgraph(obj) {
  const types = obj?.types;
  return Boolean(
    obj &&
    obj.prefixes != null &&
    Array.isArray(obj.relationships) &&
    types &&
    typeof types === "object" &&
    !Array.isArray(types) &&
    Object.values(types).some((value) => typeof value === "string"),
  );
}

export function samplePayload(entry) {
  if (!entry) return null;
  const candidates = [
    entry.samples?.samples,
    entry.samples,
    entry.sampleData,
    entry.subgraph,
    entry,
  ];
  for (const candidate of candidates) {
    if (isV5Subgraph(candidate)) return candidate;
  }
  for (const candidate of candidates) {
    const types = candidate?.types;
    if (!types || Array.isArray(types) || typeof types !== "object") continue;
    if (
      Object.values(types).some((typeEntry) =>
        Array.isArray(typeEntry?.sample_entities),
      )
    ) {
      return candidate;
    }
  }
  return entry.samples || entry.sampleData || null;
}

export function parseRelationshipLine(line) {
  if (typeof line !== "string") return null;
  const text = line.trim();
  let optional = false;
  let left;
  let right;
  if (text.includes("-->*")) {
    const index = text.indexOf("-->*");
    left = text.slice(0, index);
    right = text.slice(index + 4);
    optional = true;
  } else if (text.includes("-->")) {
    const index = text.indexOf("-->");
    left = text.slice(0, index);
    right = text.slice(index + 3);
  } else {
    return null;
  }

  let source = "";
  let predicate = "";
  const separator = left.lastIndexOf(" --");
  if (separator >= 0) {
    source = left.slice(0, separator).trim();
    predicate = left.slice(separator + 3).replace(/^-+/, "").trim();
  } else {
    const parts = left.trim().split(/\s+/);
    source = parts[0] || "";
    predicate = parts.slice(1).join(" ").replace(/^-+\s*/, "").trim();
  }
  const target = right.trim();
  if (!source || !predicate || !target) return null;
  return {
    source,
    predicate,
    label: predicate,
    optional,
    target,
    readable: text,
  };
}

export function parseAttrs(str) {
  if (!str) return [];
  const inner = String(str).replace(/^\(|\)$/g, "");
  const re = /([^,=]+?)(?::([^=,]+?))?=('(?:[^']|'')*'|[^,]+)/g;
  const entries = [];
  let match;
  while ((match = re.exec(inner)) !== null) {
    const label = match[1].trim().replace(/\*$/, "");
    const datatype = match[2]
      ? shortName(match[2].trim()) || "literal"
      : "literal";
    let value = match[3].trim();
    if (value.startsWith("'") && value.endsWith("'")) {
      value = value.slice(1, -1).replace(/''/g, "'");
    }
    entries.push({
      label,
      datatype,
      value: shortName(value) || value,
    });
  }
  return entries;
}

export function parseSchemaAttributeLine(line) {
  if (typeof line !== "string") return null;
  const match = line
    .trim()
    .match(/^--(.+?)\s+\(([^)]+)\)-->(\*)?\s+(.+)$/);
  if (!match) return null;
  return {
    label: match[1].trim(),
    uri: match[2].trim(),
    optional: Boolean(match[3]),
    datatype: match[4].trim(),
  };
}

export function relationshipLines(payload) {
  if (Array.isArray(payload?.relationships) && payload.relationships.length) {
    return payload.relationships;
  }
  if (Array.isArray(payload?.edges)) {
    return payload.edges.filter((edge) => typeof edge === "string");
  }
  return [];
}

export function displayRelNode(value) {
  return String(value || "")
    .replace(/\s+\([^)]+\)\s*$/, "")
    .trim();
}

export function v5Properties(payload) {
  return relationshipLines(payload)
    .map((line) => parseRelationshipLine(line))
    .filter(Boolean)
    .map((parsed) => ({
      uri: parsed.predicate,
      label: parsed.predicate,
      sourceUri: null,
      targetUri: null,
      source: parsed.source,
      target: parsed.target,
      support: null,
      optional: parsed.optional,
      readable: parsed.readable,
    }));
}

export function v5Attributes(payload) {
  const rows = [];
  const attrs = payload?.attributes;
  if (!attrs || typeof attrs !== "object" || Array.isArray(attrs)) return rows;
  for (const [typeName, value] of Object.entries(attrs)) {
    if (typeof value !== "string") continue;
    for (const part of value.split("|")) {
      const parsed = parseSchemaAttributeLine(part.trim());
      if (!parsed) continue;
      rows.push({
        typeUri: payload.types?.[typeName] || null,
        typeLabel: typeName,
        uri: parsed.uri,
        label: parsed.label,
        datatype: parsed.datatype || "literal",
        optional: parsed.optional,
      });
    }
  }
  return rows;
}

export function v5Samples(payload, limit = 3) {
  const instances = payload?.instances;
  if (!instances || typeof instances !== "object" || Array.isArray(instances)) {
    return [];
  }
  const keys = Object.keys(instances)
    .sort((a, b) => Number(a) - Number(b))
    .slice(0, limit);
  return keys.map((key) => {
    const instance = instances[key] || {};
    const triples = (instance.relationships || [])
      .map((line) => parseRelationshipLine(line))
      .filter(Boolean)
      .map((parsed) => ({
        src: displayRelNode(parsed.source),
        prop: parsed.predicate,
        tgt: displayRelNode(parsed.target),
        optional: parsed.optional,
        kind: "triple",
      }));
    const attrLines = [];
    for (const [src, attrStr] of Object.entries(instance.attributes || {})) {
      for (const attr of parseAttrs(attrStr)) {
        attrLines.push({
          src,
          prop: attr.label,
          tgt: attr.value,
          kind: "attr-triple",
        });
      }
    }
    return { triples: [...triples, ...attrLines] };
  });
}

export function typeCount(entry) {
  const payload = samplePayload(entry);
  const payloadTypes = payload?.types;
  if (
    payloadTypes &&
    typeof payloadTypes === "object" &&
    !Array.isArray(payloadTypes)
  ) {
    return Object.keys(payloadTypes).length;
  }
  const types = entry?.subgraph?.types;
  if (Array.isArray(types)) return types.length;
  if (types && typeof types === "object") return Object.keys(types).length;
  return entry?.subgraph?.num_types || entry?.numTypes || entry?.num_types || "?";
}

export function supportValue(entry) {
  const payload = samplePayload(entry);
  return (
    payload?.support ??
    payload?.min_support ??
    entry?.subgraph?.support ??
    entry?.support ??
    "?"
  );
}

const LLM_V5_KEYS = [
  "subgraph_id",
  "support",
  "prefixes",
  "types",
  "attributes",
  "relationships",
  "instances",
];

const LLM_INSTANCE_KEYS = ["relationships", "attributes"];

export function orderLikeLlmYaml(payload) {
  if (!isV5Subgraph(payload)) return payload;

  const ordered = {};
  for (const key of LLM_V5_KEYS) {
    if (payload[key] === undefined) continue;
    ordered[key] =
      key === "instances" ? orderInstancesLikeLlm(payload.instances) : payload[key];
  }
  for (const key of Object.keys(payload)) {
    if (ordered[key] === undefined && payload[key] !== undefined) {
      ordered[key] = payload[key];
    }
  }
  return ordered;
}

function orderInstancesLikeLlm(instances) {
  if (!instances || typeof instances !== "object" || Array.isArray(instances)) {
    return instances;
  }

  const ordered = {};
  const keys = Object.keys(instances).sort((a, b) => Number(a) - Number(b));
  for (const key of keys) {
    const instance = instances[key] || {};
    const next = {};
    for (const field of LLM_INSTANCE_KEYS) {
      if (instance[field] !== undefined) next[field] = instance[field];
    }
    for (const field of Object.keys(instance)) {
      if (next[field] === undefined && instance[field] !== undefined) {
        next[field] = instance[field];
      }
    }
    ordered[key] = next;
  }
  return ordered;
}

export function officialYamlPayload(entry, subgraphId) {
  const payload = samplePayload(entry);
  if (isV5Subgraph(payload)) return orderLikeLlmYaml(payload);
  if (
    payload &&
    typeof payload === "object" &&
    (payload.subgraph_id != null ||
      payload.edges ||
      payload.instances ||
      payload.types)
  ) {
    return {
      subgraph_id: payload.subgraph_id ?? subgraphId,
      num_types:
        payload.num_types ??
        entry?.subgraph?.num_types ??
        (payload.types ? Object.keys(payload.types).length : undefined),
      min_support:
        payload.min_support ??
        payload.support ??
        entry?.subgraph?.support ??
        entry?.support,
      edges: payload.edges ?? [],
      predicate_uris: payload.predicate_uris ?? [],
      attribute_uris: payload.attribute_uris ?? [],
      ...(payload.sample_mode ? { sample_mode: payload.sample_mode } : {}),
      ...(payload.sample_query ? { sample_query: payload.sample_query } : {}),
      ...(payload.sample_query_success != null
        ? { sample_query_success: payload.sample_query_success }
        : {}),
      instances: payload.instances ?? [],
      types: payload.types ?? {},
    };
  }
  if (entry?.subgraph) {
    return {
      subgraph_id: subgraphId,
      num_types: entry.subgraph.num_types,
      min_support: entry.subgraph.support,
      edges: entry.subgraph.edges ?? [],
      predicate_uris: [],
      attribute_uris: [],
      instances: [],
      types: entry.subgraph.types ?? [],
      ...(entry.subgraph.type_attributes
        ? { type_attributes: entry.subgraph.type_attributes }
        : {}),
    };
  }
  return null;
}

export function yamlStats(payload) {
  if (!payload) return "";
  if (isV5Subgraph(payload)) {
    const instanceCount = payload.instances
      ? Object.keys(payload.instances).length
      : 0;
    const relCount = (payload.relationships || []).length;
    const attrCount = payload.attributes
      ? Object.values(payload.attributes).reduce((sum, value) => {
        if (typeof value !== "string") return sum;
        return sum + value.split("|").filter(Boolean).length;
      }, 0)
      : 0;
    return `${instanceCount} instances · ${relCount} patterns · ${attrCount} attributes`;
  }
  const instanceCount = Array.isArray(payload.instances)
    ? payload.instances.length
    : payload.instances
      ? Object.keys(payload.instances).length
      : 0;
  return `${instanceCount} instances · ${(payload.edges || []).length} patterns · ${(payload.attribute_uris || []).length} attributes`;
}

export function displayEntity(entity, fallback = "?") {
  return (
    entity?.label || uriFallbackLabel(entity?.uri) || entity?.uri || fallback
  );
}
