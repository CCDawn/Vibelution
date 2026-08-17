import { resolve } from "node:path";
import { runPythonJsonBridge, type PythonJsonBridgeSpawn } from "./pythonJsonBridge.js";

export type BranchInstanceOperation =
  | "start"
  | "stop"
  | "force-stop"
  | "restart"
  | "observe-error"
  | "observe-ready";

export type BranchInstanceBridgeResult = {
  schemaVersion: 1;
  accepted: boolean;
  operation: string;
  instanceId?: string;
  port?: number;
  controlPort?: number;
  generation?: number;
  commandId?: string;
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
    ...(Number.isFinite(parsed.generation) ? { generation: Number(parsed.generation) } : {}),
    ...(typeof parsed.commandId === "string" && parsed.commandId ? { commandId: parsed.commandId } : {}),
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
  generation?: number;
  message?: string;
  spawnImpl?: PythonJsonBridgeSpawn;
}): Promise<BranchInstanceBridgeResult> {
  const args = [
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
  ];
  if (typeof input.generation === "number" && Number.isFinite(input.generation) && input.generation > 0) {
    args.push("--branch-instance-generation", String(Math.trunc(input.generation)));
  }
  if (typeof input.message === "string" && input.message.trim()) {
    args.push("--branch-instance-message", input.message.trim());
  }
  const raw = await runPythonJsonBridge({
    pythonPath: input.pythonPath,
    args,
    cwd: input.workspaceRoot,
    spawnImpl: input.spawnImpl,
    failureLabel: "branch instance bridge"
  });
  return parseBranchInstanceBridgeResult(raw);
}
