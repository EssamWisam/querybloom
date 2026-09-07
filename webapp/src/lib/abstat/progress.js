export function numericCount(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function progressPercent(current, total) {
  const denom = numericCount(total);
  if (!denom) return null;
  const n = Number(current);
  const numer = Number.isFinite(n) ? Math.max(0, n) : 0;
  return Math.round((Math.min(numer, denom) / denom) * 100);
}

export function formatProgress(current, total, { percentOnly = false } = {}) {
  const n = Number(current);
  const numer = Number.isFinite(n) && n > 0 ? n : 0;
  const pct = progressPercent(numer, total);
  if (pct == null) return String(numer);
  if (percentOnly) return `${pct}%`;
  return `${numer} / ${numericCount(total)} (${pct}%)`;
}

export function propertyProgressTotal({
  listedCount = 0,
  filteredCount = 0,
  propertyLimit = 0,
  seedProperty = null,
} = {}) {
  const listed = numericCount(listedCount);
  const filtered = numericCount(filteredCount);
  const limit = numericCount(propertyLimit);
  const available = filtered || listed;

  if (seedProperty) return limit || available;

  if (available && limit) return Math.min(available, limit);
  return available || limit;
}
