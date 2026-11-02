import { randomBytes } from "node:crypto";
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, realpathSync, writeFileSync } from "node:fs";
import { dirname, join, parse, resolve } from "node:path";
import type { LauncherLifecycleSupervisor } from "./launcherLifecycleSupervisor.js";
import { resolveRuntimeManagerDir } from "./projectStoragePaths.js";

export type BranchLifecycleOperation = "start" | "stop" | "restart";
export type BranchLifecycleCommand = { commandId: string; type: "open" | "close" | "restart";
  operation: BranchLifecycleOperation; owner: "branch"; instanceId: string };
export type BranchLifecycleTarget = { instanceId: string; workspaceRoot: string;
  branchInstances?: unknown; runtimeContext?: { pythonPath: string; operatorConfigPath: string };
  state: "stopped" | "starting" | "running" | "stopping" | "failed" | "unknown" };
export type BranchLifecycleResult = { schemaVersion: 1; accepted: boolean; operation: string; instanceId?: string; commandId?: string; code?: string };
export type BranchLifecycleExecution = {
  command: BranchLifecycleCommand;
  workspaceRoot: string;
  branchInstances?: unknown;
  runtimeContext?: { pythonPath: string; operatorConfigPath: string };
  check(): void;
  onCommand(): Promise<void>;
};
const canonical = (root: string) => process.platform === "win32" ? resolve(root).toLowerCase() : resolve(root);
export const branchCommandResultPath = (runtimeManagerDir: string, commandId: string) => join(runtimeManagerDir, "branch-results", `${commandId}.json`);

/** Metadata from the existing complete Launcher inventory, never a renderer ID. */
export function resolveBranchLifecycleTarget(payload: unknown, root: string): BranchLifecycleTarget | null {
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { items?: unknown }).items)) return null;
  const matches: Array<Record<string, unknown>> = [];
  for (const item of (payload as { items: unknown[] }).items) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const path = typeof row.path === "string" ? row.path : typeof row.projectRoot === "string" ? row.projectRoot : "";
    if (!path || canonical(path) !== canonical(root)) continue;
    if (row.id === "main" || typeof row.id !== "string" || !row.id.trim() || row.id.length > 512 || row.id.includes("\0")) return null;
    try { if (canonical(realpathSync.native(path)) !== canonical(root)) return null; } catch { return null; }
    matches.push(row);
  }
  if (matches.length !== 1) return null;
  const row = matches[0], phase = String(row.phase || row.status || "").toLowerCase();
  let state: BranchLifecycleTarget["state"] = "unknown";
  if (["failed", "error"].includes(phase)) state = "failed";
  else if (["stopping", "closing"].includes(phase)) state = "stopping";
  else if (["starting", "restarting", "building", "booting"].includes(phase)) state = "starting";
  else if (row.alive === true) state = "running";
  else if (row.alive === false && !["steady", "running"].includes(phase)) state = "stopped";
  return { instanceId: row.id as string, workspaceRoot: root, branchInstances: payload, state };
}

/** Refuse an occupied native lane; an assistant must not supersede its owner. */
export function assertBranchLifecycleIdle(supervisor: LauncherLifecycleSupervisor, instanceId: string): void {
  const active = supervisor.snapshot(instanceId);
  if (active && (active.phase === "intent" || active.phase === "uncertain"
      || active.phase === "observing" && ["start", "restart", "rebuild-and-start"].includes(active.operation))) {
    throw new Error("BRANCH_LIFECYCLE_BUSY");
  }
}

function writeNativeResult(input: { runtimeManagerDir: string; workspaceRoot: string; command: BranchLifecycleCommand;
  startedAt: number; result?: BranchLifecycleResult }): void {
  const file = branchCommandResultPath(input.runtimeManagerDir, input.command.commandId), directory = dirname(file);
  mkdirSync(directory, { recursive: true });
  // Native metadata is private, but a substituted storage path is still not a
  // valid owner. The assistant receipt reader independently checks all of this.
  for (let path = directory; ; path = dirname(path)) {
    const stat = lstatSync(path);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error("BRANCH_RESULT_STORAGE_CHANGED");
    if (path === parse(path).root) break;
  }
  const result = input.result, settledAt = Date.now();
  const confirmed = !!result && result.schemaVersion === 1 && typeof result.accepted === "boolean"
    && result.instanceId === input.command.instanceId && result.operation === input.command.operation;
  const completed = confirmed && !["backend_retire_incomplete", "lifecycle_intent_superseded"].includes(result?.code || "");
  const record = { schemaVersion: 1, source: "electron_branch", ...input.command, workspaceRoot: input.workspaceRoot,
    accepted: confirmed && result!.accepted, ok: confirmed && result!.accepted, completed,
    code: confirmed ? result!.code || (result!.accepted ? "accepted" : "rejected") : "outcome_unknown",
    startedAt: new Date(input.startedAt).toISOString(), settledAt: new Date(settledAt).toISOString(), runMs: Math.max(0, settledAt - input.startedAt) };
  if (existsSync(file)) throw new Error("BRANCH_RESULT_ALREADY_EXISTS");
  const fd = openSync(file, "wx", 0o600);
  try { writeFileSync(fd, `${JSON.stringify(record)}\n`, "utf8"); fsyncSync(fd); } finally { closeSync(fd); }
}

/** Native command/evidence owner over the existing instance supervisor path.
 * No assistant request IDs, application prompts, process spawn or new queue.
 */
export function createBranchLifecycleCommandOwner(options: {
  resolveTarget(root: string, integrationRoot?: string): BranchLifecycleTarget | null | Promise<BranchLifecycleTarget | null>;
  run(input: { target: BranchLifecycleTarget; operation: BranchLifecycleOperation; signal?: AbortSignal; execution: BranchLifecycleExecution }): Promise<BranchLifecycleResult>;
  resolveRuntimeManagerDir?: (root: string) => string;
}) {
  const storage = options.resolveRuntimeManagerDir ?? resolveRuntimeManagerDir;
  return {
    resolveTarget: options.resolveTarget,
    async execute(input: { target: BranchLifecycleTarget; operation: BranchLifecycleOperation; signal?: AbortSignal;
      check(): void; onCommand(command: BranchLifecycleCommand): Promise<void> }): Promise<BranchLifecycleResult> {
      const target = input.target, nativeDirectory = storage(target.workspaceRoot);
      const command: BranchLifecycleCommand = { commandId: `cmd_branch_${randomBytes(16).toString("hex")}`,
        type: input.operation === "start" ? "open" : input.operation === "stop" ? "close" : "restart",
        operation: input.operation, owner: "branch", instanceId: target.instanceId };
      const check = () => {
        input.signal?.throwIfAborted(); input.check();
        if (canonical(realpathSync.native(target.workspaceRoot)) !== canonical(target.workspaceRoot)
            || storage(target.workspaceRoot) !== nativeDirectory) throw new Error("BRANCH_REGISTRATION_CHANGED");
        if (target.branchInstances && resolveBranchLifecycleTarget(target.branchInstances, target.workspaceRoot)?.instanceId !== target.instanceId)
          throw new Error("BRANCH_REGISTRATION_CHANGED");
      };
      let bound = false;
      const startedAt = Date.now();
      try {
        check();
        const result = await options.run({ target, operation: input.operation, signal: input.signal,
          execution: { command, workspaceRoot: target.workspaceRoot, branchInstances: target.branchInstances,
            runtimeContext: target.runtimeContext, check, onCommand: async () => {
            check(); await input.onCommand(command); bound = true; check();
          } } });
        // Unbound/busy operations had no native command admission. Do not turn
        // a facade result into proof for an unrelated command.
        if (bound) writeNativeResult({ runtimeManagerDir: nativeDirectory, workspaceRoot: target.workspaceRoot, command, startedAt, result });
        return result;
      } catch (error) {
        if (bound) { try { writeNativeResult({ runtimeManagerDir: nativeDirectory, workspaceRoot: target.workspaceRoot, command, startedAt }); } catch { /* Existing/uncertain native proof stays untouched. */ } }
        throw error;
      }
    },
  };
}
export type BranchLifecycleCommandOwner = ReturnType<typeof createBranchLifecycleCommandOwner>;
