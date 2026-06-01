import type { EvolutionActiveRunIoEntry } from "../api/types";

export type SupervisedCaseTraceTone = "input" | "thought" | "tool" | "assistant" | "error";

export type SupervisedCaseTraceSection =
  | { kind: "text"; label: string; content: string }
  | { kind: "json"; label: string; content: string }
  | { kind: "state"; label: string; rows: Array<{ label: string; value: string }> };

export type SupervisedCaseTraceItem = {
  key: string;
  tone: SupervisedCaseTraceTone;
  title: string;
  preview: string;
  timestamp: string;
  status: string;
  defaultOpen: boolean;
  sections: SupervisedCaseTraceSection[];
};

const STATE_FIELD_LABELS: Record<string, string> = {
  mood: "mood",
  feeling: "feeling",
  whisper: "whisper",
  plan: "plan",
  action: "action",
  observation: "observation",
  next: "next",
  summary: "summary",
};

export function buildSupervisedCaseTraceItems(
  entries: EvolutionActiveRunIoEntry[],
  labels: {
    input: string;
    thought: string;
    tool: string;
    assistant: string;
    error: string;
    raw: string;
    state: string;
  },
): SupervisedCaseTraceItem[] {
  return entries
    .map((entry, index) => buildSupervisedCaseTraceItem(entry, index, labels))
    .filter((entry): entry is SupervisedCaseTraceItem => Boolean(entry));
}

function buildSupervisedCaseTraceItem(
  entry: EvolutionActiveRunIoEntry,
  index: number,
  labels: Parameters<typeof buildSupervisedCaseTraceItems>[1],
): SupervisedCaseTraceItem | null {
  const content = String(entry.content || "").trim();
  const kind = String(entry.kind || "").trim().toLowerCase();
  const status = String(entry.status || "").trim();
  if (!content && !kind) {
    return null;
  }
  const tone = traceTone(kind, status);
  const sections = traceSections(content, labels);
  const title = traceTitle(tone, entry.label, labels);
  const preview = compactTracePreview(sections, content || title);
  return {
    key: `${entry.timestamp || "trace"}-${kind || "entry"}-${entry.label || "item"}-${index}`,
    tone,
    title,
    preview,
    timestamp: String(entry.timestamp || "").trim(),
    status,
    defaultOpen: tone === "assistant" || tone === "error",
    sections,
  };
}

function traceTone(kind: string, status: string): SupervisedCaseTraceTone {
  if (kind === "input" || kind === "prompt") {
    return "input";
  }
  if (kind === "tool") {
    return "tool";
  }
  if (kind === "error" || status.toLowerCase() === "failed") {
    return "error";
  }
  if (kind === "assistant") {
    return "assistant";
  }
  return "thought";
}

function traceTitle(
  tone: SupervisedCaseTraceTone,
  label: string,
  labels: Parameters<typeof buildSupervisedCaseTraceItems>[1],
) {
  const normalizedLabel = String(label || "").trim();
  if (tone === "tool") {
    return normalizedLabel || labels.tool;
  }
  if (tone === "error") {
    return normalizedLabel || labels.error;
  }
  return labels[tone];
}

function traceSections(content: string, labels: Parameters<typeof buildSupervisedCaseTraceItems>[1]): SupervisedCaseTraceSection[] {
  if (!content) {
    return [];
  }
  const stateMatch = content.match(/<state>\s*([\s\S]*?)\s*<\/state>/i);
  if (stateMatch) {
    const before = content.slice(0, stateMatch.index ?? 0).trim();
    const after = content.slice((stateMatch.index ?? 0) + stateMatch[0].length).trim();
    const sections: SupervisedCaseTraceSection[] = [];
    if (before) {
      sections.push({ kind: "text", label: labels.raw, content: before });
    }
    sections.push(stateSection(stateMatch[1], labels));
    if (after) {
      sections.push({ kind: "text", label: labels.raw, content: after });
    }
    return sections;
  }
  const parsed = parseJson(content);
  if (parsed.ok) {
    return [{ kind: "json", label: labels.raw, content: JSON.stringify(parsed.value, null, 2) }];
  }
  return [{ kind: "text", label: labels.raw, content }];
}

function stateSection(rawState: string, labels: Parameters<typeof buildSupervisedCaseTraceItems>[1]): SupervisedCaseTraceSection {
  const parsed = parseJson(rawState);
  if (!parsed.ok || !isRecord(parsed.value)) {
    return { kind: "text", label: labels.state, content: rawState.trim() };
  }
  const rows = Object.entries(parsed.value)
    .map(([key, value]) => ({
      label: STATE_FIELD_LABELS[key] ?? key,
      value: stringifyTraceValue(value),
    }))
    .filter((row) => row.value.trim());
  return { kind: "state", label: labels.state, rows };
}

function parseJson(content: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(content) };
  } catch {
    return { ok: false };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringifyTraceValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

function compactTracePreview(sections: SupervisedCaseTraceSection[], fallback: string) {
  const source = sections
    .flatMap((section) => {
      if (section.kind === "state") {
        return section.rows.map((row) => row.value);
      }
      return [section.content];
    })
    .find((item) => item.trim()) ?? fallback;
  return source.replace(/\s+/g, " ").trim().slice(0, 180);
}
