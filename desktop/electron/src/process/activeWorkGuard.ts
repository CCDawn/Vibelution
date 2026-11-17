import { randomUUID } from "node:crypto";
import { readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
import { WORK_RUN_LIFECYCLE_CONTRACT } from "./workRunActivityContract.generated.js";

export const ACTIVE_WORK_BLOCK_MESSAGE_STOP =
  "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。";
export const ACTIVE_WORK_BLOCK_MESSAGE_RESTART =
  "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。";
export const ACTIVE_WORK_STALE_SNAPSHOT_GRACE_MS = 6 * 60 * 60 * 1000;

const NON_BLOCKING_STATUSES = new Set<string>([
  ...WORK_RUN_LIFECYCLE_CONTRACT.resting,
  ...WORK_RUN_LIFECYCLE_CONTRACT.terminalStatuses
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
  return WORK_RUN_LIFECYCLE_CONTRACT.statusFields
    .map((field) => String(payload[field] ?? "").trim().toLowerCase())
    .find(Boolean) || "";
}

export function activeWorkStatusBlocks(status: string): boolean {
  const normalized = String(status || "").trim().toLowerCase();
  return !NON_BLOCKING_STATUSES.has(normalized);
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
  if ([payload.finishedAt, payload.endedAt].some((value) => String(value ?? "").trim())) {
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
  return listRunEntries(kindDir).map((entry) => entry.payload);
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

/** The runtimeStatus marker core's orphan reconciliation uses for snapshots a
 * missing writer left behind; it decodes as "stopped", never as success. */
export const WORK_RUN_STOP_RECONCILE_RUNTIME_STATUS = "orphan_reconciled";
export const WORK_RUN_STOP_RECONCILE_SOURCE = "electron_workbench_stop";

type WorkRunEntry = { file: string; payload: Record<string, unknown> };

function listRunEntries(kindDir: string): WorkRunEntry[] {
  const runsDir = join(kindDir, "runs");
  let names: string[] = [];
  try {
    names = readdirSync(runsDir);
  } catch {
    return [];
  }
  const entries: WorkRunEntry[] = [];
  for (const name of names) {
    if (!name.endsWith(".json") || name.includes(".corrupt-")) {
      continue;
    }
    const payload = readJsonRecord(join(runsDir, name));
    if (payload) {
      entries.push({ file: join(runsDir, name), payload });
    }
  }
  return entries;
}

function writeJsonAtomically(target: string, value: unknown): void {
  const temporary = `${target}.${process.pid}.${randomUUID().slice(0, 8)}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  renameSync(temporary, target);
}

export type FinalizeWorkRunsForStoppedBackendResult = {
  settledRunIds: string[];
  clearedIndexKinds: string[];
};

export type RecoverableChatTurnOwner = {
  runId: string;
  ownerPid: number;
  ownerCreateTime: number;
};

/**
 * Settle every still-active work_runs snapshot once the backend tree is
 * verifiably stopped. A verified backend stop is a deterministic terminal
 * signal for this workspace's runs: without it, an indexed activeRunId keeps
 * blocking lifecycle forever (its stale grace is intentionally disabled) and
 * a stop that raced a fresh "running" snapshot blocks every later restart.
 *
 * Mirrors core's orphan reconciliation semantics: the end timestamp proves
 * settlement without inventing success (status keeps the stopped verdict, the
 * original status is preserved for audit), the runtimeStatus marker names the
 * stop as the reconciler, and the active index claim is cleared only when it
 * pointed at a settled run — never repointed at a different one. Idempotent:
 * snapshots that already carry an end receipt or a terminal status are never
 * rewritten.
 */
export function finalizeWorkRunsForStoppedBackend(input: {
  workspaceRoot: string;
  now?: () => string;
  recoverableChatTurnOwners?: readonly RecoverableChatTurnOwner[];
}): FinalizeWorkRunsForStoppedBackendResult {
  const runtimeManagerDir = resolveRuntimeManagerDir(input.workspaceRoot);
  const nowIso = input.now ?? (() => new Date().toISOString());
  const settledRunIds: string[] = [];
  const clearedIndexKinds: string[] = [];
  const recoverableChatTurns = new Map(input.recoverableChatTurnOwners?.map(owner => [owner.runId, owner]));
  const workRunsRoot = join(runtimeManagerDir, "work_runs");
  for (const kind of WORK_RUN_KIND_DIRS) {
    const kindDir = join(workRunsRoot, kind);
    const index = readJsonRecord(join(kindDir, "index.json"));
    const activeRunId = String(index?.activeRunId || "").trim();
    const settledHere: string[] = [];
    for (const entry of listRunEntries(kindDir)) {
      const payload = entry.payload;
      // The same blocking predicate the guard reads, with the indexed run's
      // staleness exemption: what blocks a restart must settle on a stop.
      if (!activeWorkPayloadBlocks(payload, { ignoreStale: true })) {
        continue;
      }
      const runId = String(payload.runId || payload.roundId || payload.sessionId || payload.id || "").trim();
      // A cold-start recovery needs this active index and snapshot to match
      // the journal's open turn. The main Launcher verified the old owner
      // independently of the backend tree being retired here.
      const recoverableOwner = kind === "chat_turn" ? recoverableChatTurns.get(runId) : undefined;
      if (recoverableOwner && payload.ownerPid === recoverableOwner.ownerPid
        && Number(payload.ownerCreateTime) === recoverableOwner.ownerCreateTime) {
        continue;
      }
      const settled: Record<string, unknown> = {
        ...payload,
        finishedAt: nowIso(),
        runtimeStatus: WORK_RUN_STOP_RECONCILE_RUNTIME_STATUS,
        reconciliationSource: WORK_RUN_STOP_RECONCILE_SOURCE
      };
      if (activeWorkStatusBlocks(payloadStatus(payload))) {
        // A live phase alias (currentPhase/phase) must not outrank the
        // stopped verdict in consumers that read status first; keep the
        // pre-stop reading auditable beside it.
        settled.preStopStatus = payloadStatus(payload) || "";
        settled.status = "stopped";
      }
      try {
        writeJsonAtomically(entry.file, settled);
        settledHere.push(runId);
      } catch {
        // Best-effort reconciliation: a single unwritable snapshot must not
        // stop the others from settling or fail the lifecycle command.
      }
    }
    if (settledHere.length > 0) {
      settledRunIds.push(...settledHere);
      if (activeRunId && settledHere.includes(activeRunId) && index) {
        try {
          writeJsonAtomically(join(kindDir, "index.json"), { ...index, activeRunId: "" });
          clearedIndexKinds.push(kind);
        } catch {
          // The snapshot itself already carries the terminal receipt, so a
          // stuck index claim loses only its staleness exemption.
        }
      }
    }
  }
  return { settledRunIds, clearedIndexKinds };
}
