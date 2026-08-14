import { resolve } from "node:path";
import { runPythonJsonBridge, type PythonJsonBridgeSpawn } from "./pythonJsonBridge.js";

export type BranchInstanceOperation = "start" | "stop" | "force-stop" | "restart";

export type BranchInstanceBridgeResult = {
  schemaVersion: 1;
  accepted: boolean;
  operation: string;
  instanceId?: string;
  port?: number;
  controlPort?: number;
  message?: string;
  code?: string;
  activeWorkRuns?: unknown[];
};

export function parseBranchInstanceBridgeResult(raw: string): BranchInstanceBridgeResult {
  const parsed = JSON.parse(raw) as BranchInstanceBridgeResult;
  if (!parsed || parsed.schemaVersion !== 1 || typeof parsed.accepted !== "boolean") {
    throw new Error("invalid branch instance bridge result");
  }
  return {
    schemaVersion: 1,
    accepted: Boolean(parsed.accepted),
    operation: String(parsed.operation || ""),
    ...(typeof parsed.instanceId === "string" && parsed.instanceId ? { instanceId: parsed.instanceId } : {}),
    ...(Number.isFinite(parsed.port) ? { port: Number(parsed.port) } : {}),
    ...(Number.isFinite(parsed.controlPort) ? { controlPort: Number(parsed.controlPort) } : {}),
    ...(typeof parsed.message === "string" && parsed.message ? { message: parsed.message } : {}),
    ...(typeof parsed.code === "string" && parsed.code ? { code: parsed.code } : {}),
    ...(Array.isArray(parsed.activeWorkRuns) ? { activeWorkRuns: parsed.activeWorkRuns } : {})
  };
}

export async function runBranchInstanceBridge(input: {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  operation: BranchInstanceOperation;
  instanceId: string;
  spawnImpl?: PythonJsonBridgeSpawn;
}): Promise<BranchInstanceBridgeResult> {
  const raw = await runPythonJsonBridge({
    pythonPath: input.pythonPath,
    args: [
      resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "branch-instance",
      "--branch-instance-operation",
      input.operation,
      "--instance-id",
      input.instanceId,
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
    failureLabel: "branch instance bridge"
  });
  return parseBranchInstanceBridgeResult(raw);
}
