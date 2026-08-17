export type ReadableMemoryBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "fields"; entries: Array<{ label: string; value: string }> }
  | { kind: "list"; items: string[] };

const FENCED_JSON = /^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$/i;

export function humanizeMemoryFieldLabel(key: string): string {
  const trimmed = key.trim();
  if (!trimmed) {
    return "";
  }
  if (/[\u4e00-\u9fff]/.test(trimmed)) {
    return trimmed;
  }
  return trimmed
    .replace(/[._/]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function looksLikeJson(text: string): boolean {
  const trimmed = text.trim();
  return (trimmed.startsWith("{") && trimmed.endsWith("}"))
    || (trimmed.startsWith("[") && trimmed.endsWith("]"));
}

function unwrapFencedJson(text: string): string {
  const match = text.trim().match(FENCED_JSON);
  return match?.[1]?.trim() || text.trim();
}

function stringifyReadableValue(value: unknown, depth = 0): string {
  if (value == null) {
    return "";
  }
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => stringifyReadableValue(item, depth + 1))
      .filter(Boolean)
      .join("；");
  }
  if (typeof value === "object") {
    if (depth >= 2) {
      return Object.entries(value as Record<string, unknown>)
        .map(([key, nested]) => `${humanizeMemoryFieldLabel(key)}：${stringifyReadableValue(nested, depth + 1)}`)
        .filter((part) => !part.endsWith("："))
        .join("；");
    }
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${humanizeMemoryFieldLabel(key)}：${stringifyReadableValue(nested, depth + 1)}`)
      .filter((part) => !part.endsWith("："))
      .join("\n");
  }
  return String(value);
}

function blocksFromJson(value: unknown): ReadableMemoryBlock[] {
  if (typeof value === "string") {
    const text = value.trim();
    return text ? [{ kind: "paragraph", text }] : [];
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return [{ kind: "paragraph", text: String(value) }];
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return [];
    }
    if (value.every((item) => item == null || typeof item !== "object")) {
      const items = value.map((item) => stringifyReadableValue(item)).filter(Boolean);
      return items.length ? [{ kind: "list", items }] : [];
    }
    return value.flatMap((item) => blocksFromJson(item));
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => ({
        label: humanizeMemoryFieldLabel(key),
        value: stringifyReadableValue(nested),
      }))
      .filter((entry) => entry.label && entry.value);
    return entries.length ? [{ kind: "fields", entries }] : [];
  }
  return [];
}

export function toReadableMemoryBlocks(raw: string): ReadableMemoryBlock[] {
  const text = unwrapFencedJson(raw || "");
  if (!text) {
    return [];
  }
  if (looksLikeJson(text)) {
    try {
      const parsed: unknown = JSON.parse(text);
      const blocks = blocksFromJson(parsed);
      if (blocks.length) {
        return blocks;
      }
    } catch {
      // Fall through to plain text so a broken payload is still readable.
    }
  }
  return [{ kind: "paragraph", text }];
}
