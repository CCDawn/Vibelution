import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";

export const ACTIVE_WORK_BLOCK_MESSAGE_STOP =
  "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。";
export const ACTIVE_WORK_BLOCK_MESSAGE_RESTART =
  "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。";
export const ACTIVE_WORK_STALE_SNAPSHOT_GRACE_MS = 6 * 60 * 60 * 1000;

const BLOCKING_STATUSES = new Set([
  "",
  "active",
  "queued",
  "running",
  "stopping",
  "started",
  "in_progress",
  "pausing",
  "resuming",
  "force_stopping"
]);

const NON_BLOCKING_STATUSES = new Set([
  "cancelled",
  "closed",
  "completed",
  "done",
  "failed",
  "failed_provider",
  "failed_runtime",
  "idle",
  "needs_continue",
  "partial",
  "paused_limit",
  "ready",
  "routed",
  "stopped",
  "stopped_by_user",
  "stop_failed",
  "superseded"
]);

const WORK_RUN_KIND_DIRS = [
  "chat_turn",
  "chat_room_round",
  "supervised_worktree_evolution_run"
] as const;

const EVOLUTION_KIND_DIRS = ["self", "supervised"] as const;

export type ActiveWorkRun = {
  kind: string;
  runId: string;
  status: string;
  sessionId: string;
};

type ActiveWorkPayloadOptions = {
  ignoreStale?: boolean;
  nowMs?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readJsonRecord(path: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function payloadStatus(payload: Record<string, unknown>): string {
  return String(payload.status || payload.currentPhase || payload.phase || payload.runtimeStatus || "")
    .trim()
    .toLowerCase();
}

export function activeWorkStatusBlocks(status: string): boolean {
  const normalized = String(status || "").trim().toLowerCase();
  if (NON_BLOCKING_STATUSES.has(normalized)) {
    return false;
  }
  if (BLOCKING_STATUSES.has(normalized)) {
    return true;
  }
  return Boolean(normalized);
}

function snapshotTimestampMs(payload: Record<string, unknown>): number | null {
  const raw = String(payload.updatedAt || payload.startedAt || "").trim();
  if (!raw) {
    return null;
  }
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function snapshotIsStale(payload: Record<string, unknown>, nowMs = Date.now()): boolean {
  const timestampMs = snapshotTimestampMs(payload);
  return timestampMs !== null && nowMs - timestampMs > ACTIVE_WORK_STALE_SNAPSHOT_GRACE_MS;
}

export function activeWorkPayloadBlocks(
  payload: Record<string, unknown>,
  options: ActiveWorkPayloadOptions = {}
): boolean {
  if (String(payload.finishedAt || payload.endedAt || "").trim()) {
    return false;
  }
  if (!options.ignoreStale && snapshotIsStale(payload, options.nowMs)) {
    return false;
  }
  return activeWorkStatusBlocks(payloadStatus(payload));
}

function snapshotItem(kind: string, payload: Record<string, unknown>): ActiveWorkRun {
  return {
    kind: String(payload.runKind || kind || "").trim(),
    runId: String(payload.runId || payload.roundId || payload.sessionId || payload.id || "").trim(),
    status: payloadStatus(payload),
    sessionId: String(payload.sessionId || payload.conversationId || "").trim()
  };
}

function listRunPayloads(kindDir: string): Record<string, unknown>[] {
  const runsDir = join(kindDir, "runs");
  let names: string[] = [];
  try {
    names = readdirSync(runsDir);
  } catch {
    return [];
  }
  const payloads: Record<string, unknown>[] = [];
  for (const name of names) {
    if (!name.endsWith(".json") || name.includes(".corrupt-")) {
      continue;
    }
    const payload = readJsonRecord(join(runsDir, name));
    if (payload) {
      payloads.push(payload);
    }
  }
  return payloads;
}

function loadActiveSnapshot(kindDir: string): Record<string, unknown> | null {
  const index = readJsonRecord(join(kindDir, "index.json"));
  const activeRunId = String(index?.activeRunId || "").trim();
  if (!activeRunId) {
    return null;
  }
  return readJsonRecord(join(kindDir, "runs", `${activeRunId}.json`));
}

export function listActiveWorkRuns(workspaceRoot: string): ActiveWorkRun[] {
  const runtimeManagerDir = resolveRuntimeManagerDir(workspaceRoot);
  const items: ActiveWorkRun[] = [];
  const seen = new Set<string>();
  const append = (
    kind: string,
    payload: Record<string, unknown> | null,
    options: ActiveWorkPayloadOptions = {}
  ): void => {
    if (!payload || !activeWorkPayloadBlocks(payload, options)) {
      return;
    }
    const item = snapshotItem(kind, payload);
    if (!item.kind) {
      return;
    }
    const key = `${item.kind}:${item.runId || item.sessionId}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    items.push(item);
  };

  const workRunsRoot = join(runtimeManagerDir, "work_runs");
  for (const kind of WORK_RUN_KIND_DIRS) {
    const kindDir = join(workRunsRoot, kind);
    const index = readJsonRecord(join(kindDir, "index.json"));
    const activeRunId = String(index?.activeRunId || "").trim();
    for (const payload of listRunPayloads(kindDir)) {
      const runId = String(payload.runId || payload.roundId || payload.sessionId || payload.id || "").trim();
      if (activeRunId && runId === activeRunId) {
        append(kind, payload, { ignoreStale: true });
        continue;
      }
      append(kind, payload);
    }
  }

  const evolutionRoot = join(runtimeManagerDir, "evolution");
  for (const storageKind of EVOLUTION_KIND_DIRS) {
    const kind = storageKind === "self" ? "self_evolution_run" : "supervised_evolution_run";
    append(kind, loadActiveSnapshot(join(evolutionRoot, storageKind)));
  }
  return items;
}

export function blockLifecycleIfActiveWork(
  operation: "stop" | "restart",
  runs: ActiveWorkRun[]
): { code: "active_work_blocked"; message: string; activeWorkRuns: ActiveWorkRun[] } | null {
  if (runs.length === 0) {
    return null;
  }
  return {
    code: "active_work_blocked",
    message: operation === "restart" ? ACTIVE_WORK_BLOCK_MESSAGE_RESTART : ACTIVE_WORK_BLOCK_MESSAGE_STOP,
    activeWorkRuns: runs.slice(0, 8)
  };
}
