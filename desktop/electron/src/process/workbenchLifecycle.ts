import {
  getSharedMainLineCommandQueue,
  type MainLineCommandQueue
} from "../lifecycle/mainLine/commandQueue.js";
import { writeMainLineIntent } from "../lifecycle/mainLine/commandIntent.js";
import { writeMainLineQueueOwnerMarker } from "../lifecycle/mainLine/ownerMarker.js";
import { resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
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
} & Pick<
  ExecuteMainLineWorkbenchInput,
  "fileExists" | "readState" | "writeState" | "listActiveWork" | "ensureFrontend" | "connect" | "fetchHealth" | "pidAlive" | "killPid" | "captureProcessIdentity"
>;

export async function runWorkbenchLifecycle(input: RunWorkbenchLifecycleInput): Promise<WorkbenchLifecycleResult> {
  const runtimeManagerDir = resolveRuntimeManagerDir(input.workspaceRoot);
  const queue = input.queue ?? getSharedMainLineCommandQueue({
    persistIntent: (intent) => {
      void writeMainLineIntent(runtimeManagerDir, intent).catch(() => undefined);
    },
    writeOwnerMarker: () => {
      void writeMainLineQueueOwnerMarker(runtimeManagerDir).catch(() => undefined);
    },
  });
  return queue.submit({
    operation: input.operation,
    noBrowser: true,
    execute: async (command) => {
      if (input.signal?.aborted) {
        throw new PythonJsonBridgeError("aborted", "workbench lifecycle was aborted before spawn");
      }
      return executeMainLineWorkbench({
        workspaceRoot: input.workspaceRoot,
        pythonPath: input.pythonPath,
        operation: input.operation,
        command,
        signal: input.signal,
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
    },
  });
}
