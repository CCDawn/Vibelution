import { classifyLogText, type LogSeverity, type LogSeverityFilter, matchesSeverityFilter } from "./logSeverity";

export type StructuredLogCategory = "dialogue" | "thinking" | "tool" | "system" | "problem";
export type StructuredLogCategoryFilter = "all" | StructuredLogCategory;

export type StructuredLogEntry = {
  lineNumber: number;
  timestamp: string;
  level: LogSeverity;
  category: StructuredLogCategory;
  title: string;
  actor: string;
  message: string;
  fields: Array<{ key: string; value: string }>;
  raw: string;
};

export type StructuredLogPreviewModel = {
  entries: StructuredLogEntry[];
  parseableLineCount: number;
  totalLineCount: number;
  kind: "jsonl" | "prefixed-log" | "mixed";
};

const MAX_FIELD_VALUE_LENGTH = 320;
const MAX_MESSAGE_LENGTH = 900;

const FIELD_PRIORITY = [
  "turn",
  "actor",
  "role",
  "type",
  "event_code",
  "eventCode",
  "component",
  "phase",
  "outcome",
  "tool",
  "tool_name",
  "toolName",
  "method",
  "path",
  "pathTemplate",
  "statusCode",
  "durationMs",
  "exceptionType",
  "exceptionMessage",
  "content_ref",
  "contentRef",
  "payload_ref",
  "payloadRef",
  "session_id",
  "sessionId",
];

const MESSAGE_KEYS = [
  "message",
  "content_preview",
  "contentPreview",
  "summary",
  "text",
  "content",
  "output_preview",
  "outputPreview",
];

const OMIT_FIELD_KEYS = new Set([
  "schema_version",
  "schemaVersion",
  "raw",
  "raw_refs",
  "rawRefs",
  "fields",
  "message",
  "content_preview",
  "contentPreview",
  "summary",
  "text",
  "content",
  "ts",
  "timestamp",
  "created_at",
  "createdAt",
  "level",
  "severity",
]);

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function compact(value: string, maxLength: number) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
      try {
        return JSON.stringify(JSON.parse(trimmed), null, 2);
      } catch {
        return value;
      }
    }
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function textFrom(value: unknown) {
  return renderValue(value).trim();
}

function firstText(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = textFrom(record[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function collectFields(record: Record<string, unknown>, payloadFields?: Record<string, unknown>) {
  const merged = { ...record, ...(payloadFields ?? {}) };
  const keys = [
    ...FIELD_PRIORITY.filter((key) => Object.prototype.hasOwnProperty.call(merged, key)),
    ...Object.keys(merged).filter((key) => !FIELD_PRIORITY.includes(key)).sort(),
  ];
  const fields: Array<{ key: string; value: string }> = [];
  const seen = new Set<string>();
  for (const key of keys) {
    if (seen.has(key) || OMIT_FIELD_KEYS.has(key)) {
      continue;
    }
    seen.add(key);
    const value = textFrom(merged[key]);
    if (!value) {
      continue;
    }
    fields.push({ key, value: compact(value, MAX_FIELD_VALUE_LENGTH) });
  }
  return fields.slice(0, 12);
}

function classifyCategory(record: Record<string, unknown>, message: string, level: LogSeverity): StructuredLogCategory {
  if (level === "error" || level === "warning") {
    return "problem";
  }

  const role = firstText(record, ["role", "actor"]).toLowerCase();
  const type = firstText(record, ["type", "event_code", "eventCode", "event", "name"]).toLowerCase();
  const component = firstText(record, ["component", "source"]).toLowerCase();
  const phase = firstText(record, ["phase", "status"]).toLowerCase();
  const combined = [role, type, component, phase, message.toLowerCase()].join(" ");

  if (/\b(tool|function_call|tool_call|tool_result|tool_result_delta|tool_calls)\b/.test(combined)) {
    return "tool";
  }
  if (/(thinking|thought|reasoning|analysis|plan|planning|reflection|deliberation)/.test(combined)) {
    return "thinking";
  }
  if (role === "user" || role === "assistant" || role === "main" || /\b(message|conversation|chat|external_request)\b/.test(combined)) {
    return "dialogue";
  }
  return "system";
}

function classifyLevel(record: Record<string, unknown>, rawLine: string): LogSeverity {
  const level = firstText(record, ["level", "severity"]).toLowerCase();
  if (level === "error" || level === "fatal" || level === "critical") {
    return "error";
  }
  if (level === "warning" || level === "warn") {
    return "warning";
  }
  return classifyLogText(rawLine);
}

function titleFrom(record: Record<string, unknown>) {
  return (
    firstText(record, ["event_code", "eventCode", "type", "event", "name", "pathTemplate", "path"]) ||
    "log.entry"
  );
}

function entryFromRecord(
  record: Record<string, unknown>,
  rawLine: string,
  lineNumber: number,
  fallback?: { title?: string; level?: string; message?: string; timestamp?: string },
): StructuredLogEntry {
  const fieldsRecord = asRecord(record.fields);
  const level = fallback?.level ? classifyLevel({ level: fallback.level }, rawLine) : classifyLevel(record, rawLine);
  const message = compact(fallback?.message || firstText(record, MESSAGE_KEYS) || titleFrom(record), MAX_MESSAGE_LENGTH);
  const category = classifyCategory(record, message, level);
  return {
    lineNumber,
    timestamp: fallback?.timestamp || firstText(record, ["ts", "timestamp", "created_at", "createdAt"]),
    level,
    category,
    title: fallback?.title || titleFrom(record),
    actor: firstText(record, ["actor", "role", "component", "source"]),
    message,
    fields: collectFields(record, fieldsRecord ?? undefined),
    raw: rawLine,
  };
}

function tryParseJsonLine(line: string, lineNumber: number): StructuredLogEntry | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) {
    return null;
  }
  try {
    const record = asRecord(JSON.parse(trimmed));
    return record ? entryFromRecord(record, line, lineNumber) : null;
  } catch {
    return null;
  }
}

function tryParsePrefixedLog(line: string, lineNumber: number): StructuredLogEntry | null {
  const match = line.match(/^\[([^\]]+)]\s+([^\s]+)\s+\[([^\]]+)]\s+(.*?)(?:\s+::\s+(\{.*\}|\[.*\]))?\s*$/);
  if (!match) {
    return null;
  }
  const [, timestamp, title, level, message, payload] = match;
  let record: Record<string, unknown> = {
    timestamp,
    event_code: title,
    level,
    message,
  };
  if (payload) {
    try {
      const parsed = asRecord(JSON.parse(payload));
      if (parsed) {
        record = { ...record, ...parsed };
      }
    } catch {
      record.payload = payload;
    }
  }
  return entryFromRecord(record, line, lineNumber, { timestamp, title, level, message });
}

export function parseStructuredLogPreview(content: string): StructuredLogPreviewModel | null {
  const lines = content.split(/\r?\n/);
  const entries: StructuredLogEntry[] = [];
  let jsonlCount = 0;
  let prefixedCount = 0;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.trim()) {
      continue;
    }
    const jsonEntry = tryParseJsonLine(line, index + 1);
    if (jsonEntry) {
      entries.push(jsonEntry);
      jsonlCount += 1;
      continue;
    }
    const prefixedEntry = tryParsePrefixedLog(line, index + 1);
    if (prefixedEntry) {
      entries.push(prefixedEntry);
      prefixedCount += 1;
    }
  }

  if (entries.length === 0) {
    return null;
  }
  return {
    entries,
    parseableLineCount: entries.length,
    totalLineCount: lines.filter((line) => line.trim()).length,
    kind: jsonlCount > 0 && prefixedCount > 0 ? "mixed" : prefixedCount > 0 ? "prefixed-log" : "jsonl",
  };
}

export function filterStructuredLogEntries(
  entries: StructuredLogEntry[],
  categoryFilter: StructuredLogCategoryFilter,
  severityFilter: LogSeverityFilter,
) {
  return entries.filter((entry) => {
    const categoryMatches = categoryFilter === "all" || entry.category === categoryFilter;
    return categoryMatches && matchesSeverityFilter(entry.level, severityFilter);
  });
}
