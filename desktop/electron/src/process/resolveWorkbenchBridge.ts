import { resolve } from "node:path";

import { runPythonJsonBridge, type PythonJsonBridgeSpawn } from "./pythonJsonBridge.js";

export async function resolveWorkbenchUrlFromBridge(input: {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  spawnImpl?: PythonJsonBridgeSpawn;
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
    failureLabel: "resolve workbench bridge"
  });
  const parsed = JSON.parse(raw) as { schemaVersion?: number; workbenchUrl?: string };
  const url = typeof parsed.workbenchUrl === "string" ? parsed.workbenchUrl.trim() : "";
  if (parsed.schemaVersion !== 1 || !url) {
    throw new Error("resolve-workbench did not return a workbenchUrl");
  }
  return url;
}
