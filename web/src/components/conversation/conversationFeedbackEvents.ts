import type { ConversationFeedbackEvent } from "../../api/types";

function positiveNumber(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function compactText(value: unknown): string {
  return String(value ?? "").trim();
}

function stableJsonSignal(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJsonSignal(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJsonSignal(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? String(value);
}

export function conversationFeedbackEventIdentityKey(event: ConversationFeedbackEvent): string {
  const sequence = positiveNumber(event.sequence);
  if (sequence > 0) {
    return `seq:${sequence}`;
  }

  const kind = compactText(event.kind);
  const name = compactText(event.name);
  const relatedThoughtSequence = positiveNumber(event.relatedThoughtSequence);
  const argumentsSignal = stableJsonSignal(event.arguments);

  if (name) {
    return [
      "named",
      kind,
      name,
      relatedThoughtSequence || "",
      argumentsSignal,
    ].join(":");
  }

  const transportStatus = compactText(event.transportStatus || event.semanticStatus);
  if (kind === "status" && transportStatus) {
    return ["status", transportStatus, relatedThoughtSequence || ""].join(":");
  }

  const tracePath = compactText(event.tracePath);
  if (tracePath) {
    return `trace:${tracePath}`;
  }

  const timestamp = compactText(event.timestamp);
  if (timestamp) {
    return ["timestamp", kind, timestamp].join(":");
  }

  return [
    "content",
    kind,
    compactText(event.summary),
    compactText(event.resultPreview),
    compactText(event.error),
  ].join(":");
}

export function mergeConversationFeedbackEvents(
  ...eventGroups: Array<ConversationFeedbackEvent[] | undefined>
): ConversationFeedbackEvent[] {
  const merged = new Map<string, ConversationFeedbackEvent>();
  for (const group of eventGroups) {
    for (const event of group ?? []) {
      const key = conversationFeedbackEventIdentityKey(event);
      const previous = merged.get(key);
      merged.set(key, previous ? { ...previous, ...event } : event);
    }
  }
  return [...merged.values()].sort((left, right) => positiveNumber(left.sequence) - positiveNumber(right.sequence));
}
