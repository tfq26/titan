const SPEAKER_COLORS = [
  "#8fb7ff",
  "#7dd3fc",
  "#86efac",
  "#fbbf24",
  "#fda4af",
  "#c4b5fd",
  "#f9a8d4",
  "#fca5a5",
];

export function humanizeLabel(value: string) {
  return value
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function speakerColor(value: string) {
  const normalized = value.trim().toLowerCase();
  let hash = 0;
  for (let i = 0; i < normalized.length; i += 1) {
    hash = (hash * 31 + normalized.charCodeAt(i)) >>> 0;
  }
  return SPEAKER_COLORS[hash % SPEAKER_COLORS.length];
}
