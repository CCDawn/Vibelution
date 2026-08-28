import { existsSync } from "node:fs";
import { join } from "node:path";

import {
  getSharedMainLineCommandQueue,
  type CloseBackoffCoalescedInfo,
  type MainLineCommandQueue
} from "../lifecycle/mainLine/commandQueue.js";
import { recordMainLineCommandSettlement } from "../lifecycle/mainLine/commandEvidence.js";
import { writeMainLineIntent } from "../lifecycle/mainLine/commandIntent.js";
import { writeMainLineQueueOwnerMarker } from "../lifecycle/mainLine/ownerMarker.js";
import { resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
import { appendSupervisorEventFallback } from "../lifecycle/supervisorEventFallback.js";
import {
  invalidPythonJsonBridgePayload,
  parsePythonJsonBridgePayload,
  PythonJsonBridgeError
} from "./pythonJsonBridge.js";
import {
  executeMainLineWorkbench,
  type ExecuteMainLineWorkbenchInput,
  type WorkbenchBackendSpawn
} from "./workbenchBackend.js";

export type WorkbenchLifecycleOperation = "start" | "stop" | "force-stop" | "restart" | "rebuild-and-start" | "shutdown";

export type WorkbenchLifecycleResult = {
  schemaVersion: 1;
  accepted: boolean;
  operation: string;
  commandId?: string;
  message?: string;
  code?: string;
  activeWorkRuns?: unknown[];
};

export function parseWorkbenchLifecycleResult(raw: string): WorkbenchLifecycleResult {
  const parsed = parsePythonJsonBridgePayload<WorkbenchLifecycleResult>(raw, "workbench lifecycle bridge");
  if (!parsed || parsed.schemaVersion !== 1 || typeof parsed.accepted !== "boolean") {
    throw invalidPythonJsonBridgePayload("workbench lifecycle bridge", "returned an invalid result shape");
  }
  return {
    schemaVersion: 1,
    accepted: Boolean(parsed.accepted),
    operation: String(parsed.operation || ""),
    ...(typeof parsed.commandId === "string" && parsed.commandId ? { commandId: parsed.commandId } : {}),
    ...(typeof parsed.message === "string" && parsed.message ? { message: parsed.message } : {}),
    ...(typeof parsed.code === "string" && parsed.code ? { code: parsed.code } : {}),
    ...(Array.isArray(parsed.activeWorkRuns) ? { activeWorkRuns: parsed.activeWorkRuns } : {})
  };
}

export type RunWorkbenchLifecycleInput = {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  operation: WorkbenchLifecycleOperation;
  spawnImpl?: WorkbenchBackendSpawn;
  signal?: AbortSignal;
  queue?: MainLineCommandQueue;
  /**
   * Overall execution deadline for one queued main-line command. Every
   * primitive inside executeMainLineWorkbench is individually bounded, but
   * their sum was not; the deadline guarantees the command always settles and
   * its settlement is recorded instead of hanging in a silent in-flight state.
   */
  commandDeadlineMs?: number;
} & Pick<
  ExecuteMainLineWorkbenchInput,
  "fileExists" | "readState" | "writeState" | "listActiveWork" | "ensureFrontend" | "connect" | "fetchHealth" | "pidAlive" | "killPid" | "captureProcessIdentity"
>;

/** Slowest bounded step (frontend build bridge) is 600s; 15min covers the sum. */
export const MAIN_LINE_COMMAND_DEADLINE_MS = 900_000;

/**
 * Best-effort trace for close re-requests absorbed by the close-domain retry
 * backoff. Only writes when the runtime-manager surface already exists so unit
 * tests with synthetic workspace roots never fabricate directories.
 */
async function recordCloseBackoffCoalescedEvent(
  workspaceRoot: string,
  runtimeManagerDir: string,
  info: CloseBackoffCoalescedInfo
): Promise<void> {
  if (!existsSync(join(runtimeManagerDir, "state.json"))) {
    return;
  }
  appendSupervisorEventFallback(workspaceRoot, {
    eventCode: "electron.main_line_command.close_backoff_coalesced",
    message: "Close re-request was coalesced into the previous close result during retry backoff.",
    fields: {
      operation: info.operation,
      runs: info.runs,
      backoffMs: info.backoffMs,
      ageMs: Math.round(info.ageMs)
    }
  });
}

export async function runWorkbenchLifecycle(input: RunWorkbenchLifecycleInput): Promise<WorkbenchLifecycleResult> {
  const runtimeManagerDir = resolveRuntimeManagerDir(input.workspaceRoot);
  const queue = input.queue ?? getSharedMainLineCommandQueue({
    persistIntent: (intent) => {
      void writeMainLineIntent(runtimeManagerDir, intent).catch(() => undefined);
    },
    writeOwnerMarker: () => {
      void writeMainLineQueueOwnerMarker(runtimeManagerDir).catch(() => undefined);
    },
    onCloseBackoffCoalesced: (info) => {
      void recordCloseBackoffCoalescedEvent(input.workspaceRoot, runtimeManagerDir, info);
    },
  });
  const deadlineMs = Math.max(
    1_000,
    Math.round(input.commandDeadlineMs ?? MAIN_LINE_COMMAND_DEADLINE_MS)
  );
  return queue.submit({
    operation: input.operation,
    noBrowser: true,
    execute: async (command) => {
      if (input.signal?.aborted) {
        throw new PythonJsonBridgeError("aborted", "workbench lifecycle was aborted before spawn");
      }
      const startedAtMs = Date.now();
      // Chain the caller's lease signal with an execution deadline so a command
      // can never stay in flight forever: either the caller aborts, the deadline
      // aborts, or the bounded primitives inside settle on their own.
      const deadline = new AbortController();
      const forwardAbort = (): void => {
        deadline.abort(input.signal?.reason);
      };
      input.signal?.addEventListener("abort", forwardAbort, { once: true });
      const deadlineReason = new Error(
        `main-line ${input.operation} command ${command.commandId} exceeded its ${Math.round(deadlineMs / 1000)}s execution deadline`
      );
      const deadlineTimer = setTimeout(() => {
        deadline.abort(deadlineReason);
      }, deadlineMs);
      deadlineTimer.unref?.();
      try {
        const result = await executeMainLineWorkbench({
          workspaceRoot: input.workspaceRoot,
          pythonPath: input.pythonPath,
          operation: input.operation,
          command,
          signal: deadline.signal,
          spawnImpl: input.spawnImpl,
          fileExists: input.fileExists,
          readState: input.readState,
          writeState: input.writeState,
          listActiveWork: input.listActiveWork,
          ensureFrontend: input.ensureFrontend,
          connect: input.connect,
          fetchHealth: input.fetchHealth,
          pidAlive: input.pidAlive,
          killPid: input.killPid,
          captureProcessIdentity: input.captureProcessIdentity
        });
        void recordMainLineCommandSettlement({
          workspaceRoot: input.workspaceRoot,
          runtimeManagerDir,
          command,
          result,
          startedAtMs,
          settledAtMs: Date.now()
        });
        return result;
      } catch (error: unknown) {
        void recordMainLineCommandSettlement({
          workspaceRoot: input.workspaceRoot,
          runtimeManagerDir,
          command,
          error,
          timedOut: deadline.signal.aborted && deadline.signal.reason === deadlineReason,
          startedAtMs,
          settledAtMs: Date.now()
        });
        throw error;
      } finally {
        clearTimeout(deadlineTimer);
        input.signal?.removeEventListener("abort", forwardAbort);
      }
    },
  });
}
