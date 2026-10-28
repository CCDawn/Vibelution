import { mkdirSync, mkdtempSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { loadWorkbenchJobNative, type WorkbenchJobHandle, type WorkbenchJobNative } from "../process/workbenchJob.js";
import { resolveNoConsolePython } from "../process/workbenchBackend.js";
import type { PreHostSourceLease } from "./projectRegistryConnection.js";
import type { ProjectAdmissionSeal } from "../lifecycle/projectAdmission.js";
import { openReminderOfflineBridge, type ReminderOfflineBinding } from "./reminderOfflineBridge.js";

/** Main persists syncId and its authorization before calling this once. */
export async function runReminderOfflineJob(input: { sourceRoot: string; pythonPath: string; pythonArguments: string[];
  runtimeRoot: string; env: NodeJS.ProcessEnv; lease: PreHostSourceLease; projectSeal: ProjectAdmissionSeal; binding: ReminderOfflineBinding;
  native?: WorkbenchJobNative; signal?: AbortSignal }): Promise<Record<string, unknown>> {
  const unknown = { schemaVersion: 1, state: "unknown", syncId: input.binding.syncId, readyForCutover: false };
  if (![input.sourceRoot, input.pythonPath, input.runtimeRoot].every(isAbsolute)) throw new Error("REMINDER_JOB_INVALID");
  const native = input.native ?? loadWorkbenchJobNative();
  if (typeof native.exitCode !== "function" || typeof native.drainStatus !== "function") throw new Error("REMINDER_JOB_UNAVAILABLE");
  await input.projectSeal.drain();
  const bridge = await openReminderOfflineBridge(input.lease, input.projectSeal, input.binding);
  let job: WorkbenchJobHandle | undefined, drained = false;
  const revoke = () => bridge.revoke();
  input.signal?.addEventListener("abort", revoke, { once: true });
  try {
    input.signal?.throwIfAborted();
    mkdirSync(input.runtimeRoot, { recursive: true });
    const directory = mkdtempSync(join(input.runtimeRoot, "reminder-"));
    const stdout = join(directory, "stdout.log"), stderr = join(directory, "stderr.log");
    const allowed = new Set(["SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "SYSTEMDRIVE", "TEMP", "TMP"]);
    const env = Object.fromEntries(Object.entries(input.env).filter(([key]) => allowed.has(key.toUpperCase())));
    Object.assign(env, bridge.environment, { PYTHONDONTWRITEBYTECODE: "1", PYTHONIOENCODING: "utf-8" });
    input.lease.check();
    const spawned = native.spawn({ executable: resolveNoConsolePython(input.pythonPath),
      arguments: [...input.pythonArguments, join(input.sourceRoot, "scripts", "assistant_reminder_offline_worker.py")],
      cwd: input.sourceRoot, env, stdoutPath: stdout, stderrPath: stderr, containDescendants: true, maxLogBytes: 65536 });
    job = spawned.job;
    let exit: number | null = null;
    let status: ReturnType<NonNullable<WorkbenchJobNative["drainStatus"]>> | undefined;
    while (!drained) {
      try {
        status = native.drainStatus(job); exit = native.exitCode(job);
        drained = native.activeCount(job) === 0 && status.complete && exit !== null;
      } catch { /* No inspection means no drain proof. */ }
      if (!drained) await new Promise<void>(resolve => setTimeout(resolve, 250));
    }
    if (input.signal?.aborted || !Number.isSafeInteger(spawned.pid) || spawned.pid <= 0 || exit !== 0
        || !bridge.wasGranted() || status?.channels.length !== 2
        || new Set(status.channels.map(channel => channel.stream)).size !== 2
        || status.channels.some(channel => !channel.complete || channel.errorCode !== 0 || channel.droppedBytes !== 0 || channel.rotations !== 0)) return unknown;
    try {
      if (statSync(stdout).size > 65536) return unknown;
      const value: unknown = JSON.parse(readFileSync(stdout, "utf8"));
      if (!value || typeof value !== "object" || Array.isArray(value)) return unknown;
      const row = value as Record<string, unknown>;
      if (row.schemaVersion !== 1 || row.state !== "pending" || row.syncId !== input.binding.syncId
          || row.readyForCutover !== false) return unknown;
      if (row.code === "sender_proof_unavailable" && Object.keys(row).sort().join(",") ===
          "code,preparationId,readyForCutover,schemaVersion,state,syncId,uncertainCount"
          && typeof row.preparationId === "string" && /^rprep-[a-f0-9]{40}$/.test(row.preparationId)
          && Number.isSafeInteger(row.uncertainCount) && (row.uncertainCount as number) >= 0 && (row.uncertainCount as number) <= 2048) return row;
      if (row.code === "affairs_conflicts" && Object.keys(row).sort().join(",") ===
          "code,conflictCount,readyForCutover,schemaVersion,state,syncId"
          && Number.isSafeInteger(row.conflictCount) && (row.conflictCount as number) > 0 && (row.conflictCount as number) <= 4096) return row;
      return unknown;
    } catch { return unknown; }
  } catch { return unknown; }
  finally {
    input.signal?.removeEventListener("abort", revoke);
    let closeFailed = false;
    if (job && drained) {
      try { native.close(job); } catch { closeFailed = true; }
    }
    // Never release the permit while a spawned Job is still unconfirmed.
    // Even a failed native handle close must not strand a drained capability.
    if (!job || drained) await bridge.closeAfterDrain();
    if (closeFailed) throw new Error("REMINDER_JOB_CLOSE_UNKNOWN");
  }
}
