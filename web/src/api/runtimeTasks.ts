import { fetchJson } from "./client";

/**
 * Runtime task center API (aux conversations center).
 * Contract: GET /api/runtime-tasks (running + ended pages), task detail,
 * and POST /{taskId}/stop with `{ initiator: "user" }`.
 */

/** Task kinds surfaced in the aux conversations center. */
export type RuntimeTaskKind = "child_session" | "cli_agent" | "research_task";

export type RuntimeTaskCard = {
  taskId: string;
  kind: string;
  status: string;
  title: string;
  parentSessionId: string;
  childSessionId?: string | null;
  startedAt: string;
  endedAt?: string | null;
  summary?: string | null;
  outputPath?: string | null;
};

export type RuntimeTaskListPayload = {
  revision: string;
  running: RuntimeTaskCard[];
  ended: {
    items: RuntimeTaskCard[];
    total: number;
    nextCursor: string;
  };
};

export type RuntimeTaskStopResult = {
  accepted: boolean;
  taskId: string;
  status: string;
  stopInitiator?: string;
};

/**
 * Detail-only extras from GET /api/runtime-tasks/{taskId}: the approximate
 * timeline is synthesized from snapshot timestamps (not a raw event log), so
 * the shape is rendered tolerantly.
 */
export type RuntimeTaskTimelineItem = {
  at?: string;
  label?: string;
  status?: string;
};

export type RuntimeTaskDetailPayload = RuntimeTaskCard & {
  stopInitiator?: string;
  pendingMessageCount?: number;
  timeline?: RuntimeTaskTimelineItem[];
};

export type RuntimeTaskListOptions = {
  status?: "active" | "ended" | "all";
  kind?: string;
  parentSessionId?: string;
  cursor?: string;
  limit?: number;
};

export const RUNTIME_TASKS_ENDPOINT = "/api/runtime-tasks";
export const DEFAULT_RUNTIME_TASK_PAGE_LIMIT = 50;

export function runtimeTasksListUrl(options: RuntimeTaskListOptions = {}) {
  const params = new URLSearchParams();
  params.set("status", options.status ?? "all");
  if (options.kind) {
    params.set("kind", options.kind);
  }
  if (options.parentSessionId) {
    params.set("parent_session_id", options.parentSessionId);
  }
  if (options.cursor) {
    params.set("cursor", options.cursor);
  }
  params.set("limit", String(options.limit ?? DEFAULT_RUNTIME_TASK_PAGE_LIMIT));
  return `${RUNTIME_TASKS_ENDPOINT}?${params.toString()}`;
}

export function listRuntimeTasks(options: RuntimeTaskListOptions = {}, signal?: AbortSignal) {
  return fetchJson<RuntimeTaskListPayload>(runtimeTasksListUrl(options), { signal });
}

export function runtimeTaskDetailUrl(taskId: string) {
  return `${RUNTIME_TASKS_ENDPOINT}/${encodeURIComponent(taskId)}`;
}

export function getRuntimeTask(taskId: string) {
  return fetchJson<RuntimeTaskDetailPayload>(runtimeTaskDetailUrl(taskId));
}

export function stopRuntimeTask(taskId: string) {
  return fetchJson<RuntimeTaskStopResult>(`${runtimeTaskDetailUrl(taskId)}/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initiator: "user" }),
  });
}

/** Child sessions open read-write in the chat workbench via ?session=… */
export function childSessionHref(childSessionId: string) {
  const normalized = String(childSessionId || "").trim();
  return normalized ? `/chat?session=${encodeURIComponent(normalized)}` : "";
}

/**
 * Revision-aware list fetch: when the payload revision is unchanged the cached
 * object is returned as-is so React Query keeps referential identity and the
 * route does not re-render on every poll beat.
 */
export async function listRuntimeTasksRevisionAware(
  options: RuntimeTaskListOptions,
  previous: RuntimeTaskListPayload | undefined,
  signal?: AbortSignal,
): Promise<RuntimeTaskListPayload> {
  const next = await listRuntimeTasks(options, signal);
  if (previous && String(previous.revision) === String(next.revision)) {
    return previous;
  }
  return next;
}
