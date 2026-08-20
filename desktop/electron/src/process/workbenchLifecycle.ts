import { resolve } from "node:path";

import {
  getSharedMainLineCommandQueue,
  type MainLineCommandQueue,
} from "../lifecycle/mainLine/commandQueue.js";
import { writeMainLineIntent } from "../lifecycle/mainLine/commandIntent.js";
import { writeMainLineQueueOwnerMarker } from "../lifecycle/mainLine/ownerMarker.js";
import { resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
import {
  invalidPythonJsonBridgePayload,
  parsePythonJsonBridgePayload,
  PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS,
  runPythonJsonBridge,
  type PythonJsonBridgeSpawn
} from "./pythonJsonBridge.js";

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

async function spawnWorkbenchLifecycleBridge(input: {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  operation: WorkbenchLifecycleOperation;
  spawnImpl?: PythonJsonBridgeSpawn;
  signal?: AbortSignal;
}): Promise<WorkbenchLifecycleResult> {
  const raw = await runPythonJsonBridge({
    pythonPath: input.pythonPath,
    args: [
      resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "lifecycle",
      "--lifecycle-operation",
      input.operation,
      "--output",
      "json",
      "--workspace",
      input.workspaceRoot,
      "--config",
      input.operatorConfigPath,
      "--no-browser"
    ],
    cwd: input.workspaceRoot,
    spawnImpl: input.spawnImpl,
    failureLabel: "workbench lifecycle bridge",
    timeoutMs: PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS,
    signal: input.signal,
    killPolicy: "child",
    mutation: true
  });
  return parseWorkbenchLifecycleResult(raw);
}

export async function runWorkbenchLifecycle(input: {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  operation: WorkbenchLifecycleOperation;
  spawnImpl?: PythonJsonBridgeSpawn;
  signal?: AbortSignal;
  queue?: MainLineCommandQueue;
}): Promise<WorkbenchLifecycleResult> {
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
    execute: () => spawnWorkbenchLifecycleBridge(input),
  });
}
