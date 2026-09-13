import { resolve } from "node:path";

import {
  parsePythonJsonBridgePayload,
  PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS,
  runPythonJsonBridge,
  type PythonJsonBridgeSpawn
} from "./pythonJsonBridge.js";

export type WorkbenchPortOwnerResolution = {
  pid: number;
  kind: string;
  alive: boolean;
  trusted: boolean;
  residual: boolean;
  conflict: boolean;
};

/**
 * Resolve the loopback port owner through the Python observation classifiers.
 *
 * This is the fallback evidence path for a wedged backend that still owns the
 * port but no longer answers /api/health: the process inventory can still prove
 * that the listening pid is this project's managed workbench backend.
 */
export async function resolveWorkbenchPortOwner(input: {
  workspaceRoot: string;
  pythonPath: string;
  port: number;
  spawnImpl?: PythonJsonBridgeSpawn;
  signal?: AbortSignal;
  timeoutMs?: number;
}): Promise<WorkbenchPortOwnerResolution | null> {
  const port = Math.trunc(Number(input.port));
  if (!input.pythonPath.trim() || !input.workspaceRoot.trim() || !Number.isFinite(port) || port <= 0) {
    return null;
  }
  let raw: string;
  try {
    raw = await runPythonJsonBridge({
      pythonPath: input.pythonPath,
      args: [
        resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
        "--action",
        "resolve-workbench-port-owner",
        "--output",
        "json",
        "--workspace",
        input.workspaceRoot,
        "--port",
        String(port),
        "--no-browser"
      ],
      cwd: input.workspaceRoot,
      spawnImpl: input.spawnImpl,
      failureLabel: `resolve workbench port owner for port ${port}`,
      timeoutMs: input.timeoutMs ?? PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS,
      signal: input.signal,
      killPolicy: "child"
    });
  } catch {
    return null;
  }
  try {
    const parsed = parsePythonJsonBridgePayload<Record<string, unknown>>(
      raw,
      `resolve workbench port owner for port ${port}`
    );
    if (parsed.schemaVersion !== 1 || parsed.ok !== true) {
      return null;
    }
    const pid = Math.trunc(Number(parsed.pid || 0));
    if (!Number.isFinite(pid) || pid <= 0) {
      return null;
    }
    return {
      pid,
      kind: String(parsed.kind || "").trim(),
      alive: parsed.alive === true,
      trusted: parsed.trusted === true,
      residual: parsed.residual === true,
      conflict: parsed.conflict === true
    };
  } catch {
    return null;
  }
}
