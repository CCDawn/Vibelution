/** Optional display facts never establish task identity or execution state. */
export type AssistantTaskMetadata = {
  agentName?: string;
  teamName?: string;
  projectName?: string;
  createdAt?: string;
  updatedAt?: string;
  error?: string;
  resultSummary?: string;
  current?: string;
  stepCount?: number;
  attemptCount?: number;
  currentAgentName?: string;
  cleanupPending?: boolean;
};

export function displayText(value: unknown, limit = 600): string {
  if (typeof value !== "string") return "";
  const text = value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ").replace(/\s+/g, " ").trim();
  const chars = Array.from(text);
  return chars.length > limit ? `${chars.slice(0, limit - 1).join("")}…` : text;
}

export function displayError(value: unknown): string {
  return displayText(typeof value === "object" && value !== null ? (value as { message?: unknown }).message : value);
}

export function taskMetadata(value: unknown): AssistantTaskMetadata {
  const row = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const date = (key: string) => typeof row[key] === "string" && /^\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})$/.test(row[key] as string)
    && Number.isFinite(Date.parse(row[key] as string)) ? row[key] as string : undefined;
  const count = (key: string) => Number.isSafeInteger(row[key]) && (row[key] as number) >= 0 ? row[key] as number : undefined;
  return {
    agentName: displayText(row.agentName, 100), teamName: displayText(row.teamName, 100), projectName: displayText(row.projectName, 100),
    createdAt: date("createdAt"), updatedAt: date("updatedAt"), error: displayError(row.error), resultSummary: displayText(row.resultSummary),
    current: Number.isSafeInteger(row.current) && (row.current as number) >= 0 ? String(row.current) : displayText(row.current, 160),
    stepCount: count("stepCount"), attemptCount: count("attemptCount"),
    currentAgentName: displayText(row.currentAgentName, 100),
    cleanupPending: row.cleanupPending === true,
  };
}

export function taskDisplayTitle(title: string, _shortId: string, lang: "zh" | "en"): string {
  // Never synthesize a title from prompt, instructions, code or result bodies.
  const generic = /^(?:助理任务|团队运行|Assistant task|Team run|未命名任务(?:\s*[·#-].*)?|Untitled task(?:\s*[·#-].*)?)$/i.test(title.trim());
  const opaque = /^(?:\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(title.trim());
  const usable = title && !generic && !opaque && !/^\s*(?:```|<script\b|(?:system|user|assistant)\s*:)/i.test(title);
  return usable ? displayText(title, 60) : lang === "zh" ? "委派任务" : "Delegated task";
}
