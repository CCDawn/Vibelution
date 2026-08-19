import { resolve } from "node:path";

import {
  invalidPythonJsonBridgePayload,
  parsePythonJsonBridgePayload,
  PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS,
  runPythonJsonBridge,
  type PythonJsonBridgeSpawn
} from "./pythonJsonBridge.js";

export async function resolveWorkbenchUrlFromBridge(input: {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  spawnImpl?: PythonJsonBridgeSpawn;
  signal?: AbortSignal;
}): Promise<string> {
  const raw = await runPythonJsonBridge({
    pythonPath: input.pythonPath,
    args: [
      resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "resolve-workbench",
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
    failureLabel: "resolve workbench bridge",
    timeoutMs: PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS,
    signal: input.signal,
    killPolicy: "child"
  });
  const parsed = parsePythonJsonBridgePayload<{ schemaVersion?: number; workbenchUrl?: string }>(
    raw,
    "resolve workbench bridge"
  );
  const url = typeof parsed.workbenchUrl === "string" ? parsed.workbenchUrl.trim() : "";
  if (parsed.schemaVersion !== 1 || !url) {
    throw invalidPythonJsonBridgePayload("resolve workbench bridge", "did not return a workbenchUrl");
  }
  return url;
}
