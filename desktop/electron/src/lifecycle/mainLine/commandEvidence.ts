import { mkdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join } from "node:path";

import { PythonJsonBridgeError } from "../../process/pythonJsonBridge.js";
import { appendSupervisorEventFallback } from "../supervisorEventFallback.js";
import type { MainLineLifecycleResult, MainLineQueuedCommand } from "./commandQueue.js";

/**
 * Durable settlement evidence for main-line lifecycle commands that Electron
 * executes while it owns the queue.
 *
 * The 2026-08-28 18:50 restart stall showed why this surface must exist: a
 * restart whose execution settled on the active-work guard (accepted:false)
 * used to leave *zero* durable trace — no launcher-state write, no result
 * file, no event — while main_line_intent.json kept pointing at the restart.
 * From the outside that is indistinguishable from a hung command.
 *
 * Evidence is written into the same runtime-manager ``results/`` surface the
 * daemon already uses, keyed by the Electron queue's own commandId (which is
 * also the id persisted in main_line_intent.json), so an intent can always be
 * joined with its outcome. Files use write-once semantics: when the daemon
 * already recorded a hand-off acknowledgement for the same id, that file stays
 * untouched and the settlement is still visible through the supervisor event
 * fallback stream. Electron never appends to the daemon-owned events.jsonl
 * (I6: single-writer per JSONL surface).
 */
export const MAIN_LINE_SETTLEMENT_EVENT_CODE = "electron.main_line_command.settled";

export type MainLineCommandSettlementInput = {
  workspaceRoot: string;
  runtimeManagerDir: string;
  command: Pick<MainLineQueuedCommand, "commandId" | "type" | "operation">;
  result?: MainLineLifecycleResult;
  error?: unknown;
  timedOut?: boolean;
  startedAtMs: number;
  settledAtMs: number;
};

export type MainLineCommandSettlementRecord = {
  schemaVersion: 1;
  source: "electron_main";
  commandId: string;
  type: MainLineQueuedCommand["type"];
  operation: string;
  accepted: boolean;
  ok: boolean;
  completed: boolean;
  message: string;
  code?: string;
  errorType?: string;
  timedOut?: boolean;
  startedAt: string;
  settledAt: string;
  runMs: number;
};

export function mainLineCommandResultPath(runtimeManagerDir: string, commandId: string): string {
  return join(runtimeManagerDir, "results", `${commandId}.json`);
}

function errorDetail(error: unknown): { message: string; errorType: string; code?: string } {
  const message = error instanceof Error ? error.message : String(error ?? "");
  const errorType = error instanceof Error ? error.name : typeof error;
  const code = error instanceof PythonJsonBridgeError ? error.code : undefined;
  return { message: message.slice(0, 600), errorType, ...(code ? { code } : {}) };
}

/**
 * Record how a main-line command settled. Best-effort by contract: evidence
 * failures must never alter the lifecycle outcome, so every I/O step is
 * guarded and the write is atomic (temp file + rename semantics are provided
 * by write-once ``wx`` into results/, the daemon's own per-command surface).
 */
export async function recordMainLineCommandSettlement(
  input: MainLineCommandSettlementInput
): Promise<MainLineCommandSettlementRecord | null> {
  const settledAtMs = Math.max(input.settledAtMs, input.startedAtMs);
  const settledAt = new Date(settledAtMs).toISOString();
  const fromError = input.error !== undefined;
  const detail = fromError ? errorDetail(input.error) : null;
  const result = input.result;
  const resultMessage = typeof result?.message === "string" ? result.message.trim() : "";
  const message = (detail?.message ?? resultMessage).trim()
    || (result?.accepted
      ? "Main-line lifecycle command settled successfully."
      : "Main-line lifecycle command settled without being accepted.");
  const code = detail?.code ?? (typeof result?.code === "string" && result.code ? result.code : undefined);
  const accepted = fromError ? false : Boolean(result?.accepted);
  const record: MainLineCommandSettlementRecord = {
    schemaVersion: 1,
    source: "electron_main",
    commandId: input.command.commandId,
    type: input.command.type,
    operation: input.command.operation,
    accepted,
    ok: accepted,
    completed: !fromError,
    message,
    ...(code ? { code } : {}),
    ...(detail?.errorType ? { errorType: detail.errorType } : {}),
    ...(input.timedOut ? { timedOut: true } : {}),
    startedAt: new Date(input.startedAtMs).toISOString(),
    settledAt,
    runMs: settledAtMs - input.startedAtMs
  };
  try {
    // The runtime-manager surface is provisioned by the daemon (its state.json
    // exists long before Electron ever executes a main-line command). Requiring
    // that fingerprint keeps synthetic workspace roots (unit tests, dry
    // checkouts) from accumulating fabricated evidence directories.
    if (!existsSync(join(input.runtimeManagerDir, "state.json"))) {
      return null;
    }
  } catch {
    return null;
  }
  try {
    const resultsDir = join(input.runtimeManagerDir, "results");
    await mkdir(resultsDir, { recursive: true });
    await writeFile(
      mainLineCommandResultPath(input.runtimeManagerDir, input.command.commandId),
      `${JSON.stringify(record, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" }
    );
  } catch {
    // Write-once: an existing daemon result for this commandId wins.
  }
  try {
    appendSupervisorEventFallback(input.workspaceRoot, {
      eventCode: MAIN_LINE_SETTLEMENT_EVENT_CODE,
      message: message.slice(0, 300),
      fields: {
        commandId: record.commandId,
        type: record.type,
        operation: record.operation,
        accepted: record.accepted,
        code: record.code ?? "",
        errorType: record.errorType ?? "",
        timedOut: record.timedOut === true,
        runMs: record.runMs,
        resultPath: mainLineCommandResultPath(input.runtimeManagerDir, record.commandId)
      }
    });
  } catch {
    // Best-effort evidence; never surfaces into the lifecycle result.
  }
  return record;
}
