import { resolve } from "node:path";
import { launcherApiBridgeTimeoutMs, LAUNCHER_API_JSON_BRIDGE_MAX_BYTES, parsePythonJsonBridgePayload, runPythonJsonBridge } from "./pythonJsonBridge.js";

/** Existing read-only native inventory API for one registered integration root.
 * It neither switches Electron's current project nor starts a project backend.
 */
export async function readNativeBranchInstanceInventory(input: {
  integrationRoot: string; pythonPath: string; operatorConfigPath: string; signal?: AbortSignal;
}): Promise<unknown> {
  const raw = await runPythonJsonBridge({ pythonPath: input.pythonPath,
    args: [resolve(input.integrationRoot, "scripts", "vibelution_desktop_entry.py"), "--action", "launcher-api",
      "--launcher-api-path", "branch-instances", "--launcher-api-method", "GET", "--output", "json",
      "--workspace", input.integrationRoot, "--config", input.operatorConfigPath, "--no-browser"],
    cwd: input.integrationRoot, failureLabel: "registered branch inventory", signal: input.signal,
    maxBytes: LAUNCHER_API_JSON_BRIDGE_MAX_BYTES, timeoutMs: launcherApiBridgeTimeoutMs("branch-instances", "GET"),
    killPolicy: "child", mutation: false });
  const result = parsePythonJsonBridgePayload<{ ok?: boolean; payload?: unknown }>(raw, "registered branch inventory");
  if (!result || result.ok !== true || !result.payload || typeof result.payload !== "object") throw new Error("BRANCH_INVENTORY_UNAVAILABLE");
  const payload = result.payload as { integrationRoot?: unknown; items?: unknown };
  const canonical = (path: string) => process.platform === "win32" ? resolve(path).toLowerCase() : resolve(path);
  if (typeof payload.integrationRoot !== "string" || canonical(payload.integrationRoot) !== canonical(input.integrationRoot)
      || !Array.isArray(payload.items)) throw new Error("BRANCH_INVENTORY_UNAVAILABLE");
  return payload;
}
