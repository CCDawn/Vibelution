import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { resolveLauncherRuntimeDir } from "../lifecycle/projectStoragePaths.js";

import {
  invalidPythonJsonBridgePayload,
  parsePythonJsonBridgePayload,
  PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS,
  runPythonJsonBridge,
  PythonJsonBridgeError,
  type PythonJsonBridgeSpawn
} from "./pythonJsonBridge.js";

export type LauncherServiceStartInput = {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  spawnImpl?: PythonJsonBridgeSpawn;
  signal?: AbortSignal;
};

export type LauncherServiceStopInput = LauncherServiceStartInput & {
  launcherBackendPid?: number;
  readState?: () => unknown;
};

export type LauncherServiceStopResult = {
  schemaVersion: 1;
  status: "stopped" | "skipped";
  reason: string;
  expectedBackendPid: number;
  launcherBackendPid: number;
  terminatedPids: number[];
};

function stopLauncherBridgeArgs(input: LauncherServiceStopInput): string[] {
  const args = [
    resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
    "--action",
    "stop-launcher",
    "--output",
    "json",
    "--workspace",
    input.workspaceRoot,
    "--config",
    input.operatorConfigPath
  ];
  const ownedPid = Number(input.launcherBackendPid || 0);
  if (ownedPid > 0) {
    args.push("--owned-backend-pid", String(ownedPid));
  } else {
    args.push("--use-state-owned-backend-pid");
  }
  args.push("--no-browser");
  return args;
}

export async function stopPythonLauncherService(input: LauncherServiceStopInput): Promise<LauncherServiceStopResult> {
  if (input.signal?.aborted) {
    throw new PythonJsonBridgeError("aborted", "launcher stop bridge was aborted before spawn");
  }
  // Match the bridge's no-owner decision locally. Uncertain or positive
  // ownership still goes through Python's process identity checks.
  if (!(Number(input.launcherBackendPid || 0) > 0)) {
    try {
      const state = (input.readState ?? (() => JSON.parse(readFileSync(
        join(resolveLauncherRuntimeDir(input.workspaceRoot), "state.json"), "utf8"
      ))))();
      if (state && typeof state === "object" && !Array.isArray(state)) {
        const record = state as Record<string, unknown>;
        const statePid = Number(record.launcherBackendPid ?? 0);
        if (typeof record.runtimeProjectRoot === "string" && record.runtimeProjectRoot.trim()
          && resolve(record.runtimeProjectRoot).toLowerCase() === resolve(input.workspaceRoot).toLowerCase()
          && Number.isSafeInteger(statePid) && statePid <= 0) {
          return {
            schemaVersion: 1, status: "skipped", reason: "owned_backend_pid_required",
            expectedBackendPid: 0, launcherBackendPid: statePid, terminatedPids: []
          };
        }
      }
    } catch {
      // Missing, corrupt, or unavailable state needs the existing bridge.
    }
  }
  const raw = await runPythonJsonBridge({
    pythonPath: input.pythonPath,
    args: stopLauncherBridgeArgs(input),
    cwd: input.workspaceRoot,
    spawnImpl: input.spawnImpl,
    failureLabel: "launcher stop bridge",
    timeoutMs: PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS,
    signal: input.signal,
    killPolicy: "child",
    mutation: true
  });
  return parseLauncherStop(raw);
}

function parseLauncherStop(raw: string): LauncherServiceStopResult {
  const parsed = parsePythonJsonBridgePayload<LauncherServiceStopResult>(raw, "launcher stop bridge");
  if (!parsed || parsed.schemaVersion !== 1 || !["stopped", "skipped"].includes(parsed.status)) {
    throw invalidPythonJsonBridgePayload("launcher stop bridge", "returned an invalid result shape");
  }
  if (!Array.isArray(parsed.terminatedPids)) {
    throw invalidPythonJsonBridgePayload("launcher stop bridge", "returned an invalid result shape");
  }
  return {
    schemaVersion: 1,
    status: parsed.status,
    reason: String(parsed.reason || ""),
    expectedBackendPid: Number(parsed.expectedBackendPid || 0),
    launcherBackendPid: Number(parsed.launcherBackendPid || 0),
    terminatedPids: parsed.terminatedPids.map((pid) => Number(pid)).filter((pid) => Number.isFinite(pid) && pid > 0)
  };
}
