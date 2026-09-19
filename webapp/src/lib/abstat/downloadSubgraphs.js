import { TarWriter } from "@gera2ld/tarjs";
import { gzipSync } from "fflate";
import { dump } from "js-yaml";

function exportPayload(entry) {
  const candidates = [
    entry?.samples?.samples,
    entry?.samples,
    entry?.sampleData,
    entry?.payload,
    entry?.subgraph,
  ];
  return candidates.find(
    (candidate) =>
      candidate && typeof candidate === "object" && !Array.isArray(candidate),
  );
}

function archiveName(value) {
  const normalized = String(value || "querybloom-subgraphs")
    .trim()
    .replace(/\.(?:tar\.gz|tgz|tar)$/i, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "querybloom-subgraphs";
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function downloadSubgraphs(
  subgraphs,
  filename = "querybloom-subgraphs",
) {
  const entries = (subgraphs || [])
    .map((entry, position) => ({
      index: Number.isFinite(Number(entry?.index))
        ? Number(entry.index)
        : position,
      payload: exportPayload(entry),
    }))
    .filter((entry) => entry.payload)
    .sort((left, right) => left.index - right.index);

  if (!entries.length) {
    throw new Error("No subgraph YAML data is available to download.");
  }

  const digits = Math.max(3, String(entries.length).length);
  const tar = new TarWriter();
  for (const entry of entries) {
    tar.addFile(
      `subgraph-${String(entry.index + 1).padStart(digits, "0")}.yaml`,
      dump(entry.payload, {
        noRefs: true,
        sortKeys: false,
        lineWidth: -1,
      }),
    );
  }

  const tarBlob = await tar.write();
  const compressed = gzipSync(new Uint8Array(await tarBlob.arrayBuffer()), {
    level: 6,
  });
  const name = archiveName(filename);
  downloadBlob(new Blob([compressed], { type: "application/gzip" }), `${name}.tar.gz`);
}