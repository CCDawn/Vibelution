import type { AssistantHost } from "./assistantHost.js";
import type { AssistantReminderPump } from "./reminderPump.js";
import type { AssistantProjectRegistryConnection } from "./projectRegistryConnection.js";
import type { ActiveWorkStatus } from "../shutdown/shutdownCoordinator.js";

export function combineAssistantActiveWork(workspace: ActiveWorkStatus, assistant: ActiveWorkStatus): ActiveWorkStatus {
  const active = [workspace, assistant].filter(row => row.state === "active");
  if (active.length) return { state: "active", message: active[0].message,
    count: active.reduce((sum, row) => sum + (row.count ?? 1), 0), items: active.flatMap(row => row.items ?? []) };
  return workspace.state === "unknown" ? workspace : assistant.state === "unknown" ? assistant : workspace;
}

export type AssistantLifecycleLease = { release(): Promise<void>; commit(): void };
type Host = Pick<AssistantHost, "snapshot" | "beginLifecycleAdmission" | "migrationBarrier">;

/** Reuse the joint native barrier only after fencing its external producers.
 * The returned lease stays held through native shutdown, never just an idle poll.
 */
export async function acquireAssistantLifecycleLease(input: {
  host: Host;
  projects: Pick<AssistantProjectRegistryConnection, "beginMigrationTransition">;
  reminders: Pick<AssistantReminderPump, "tryDrainForLifecycle" | "resumeAfterMigration">;
  drainQueues(): Promise<void>;
  current(): boolean;
  reopen(): boolean;
  releaseOwner(): void;
}): Promise<AssistantLifecycleLease> {
  let admission: ReturnType<Host["beginLifecycleAdmission"]> | undefined;
  let registry: ReturnType<typeof input.projects.beginMigrationTransition> | undefined;
  let remindersDrained = false, barrierAttempted = false;
  let releasing: Promise<void> | undefined;
  const pause = () => new Promise<void>(resolve => { const timer = setTimeout(resolve, 100); timer.unref?.(); });
  const release = (): Promise<void> => releasing ??= (async () => {
    // A lost reply does not prove native admission reopened. Retain the same
    // owner and all producer fences until release or that exact host's stop.
    if (barrierAttempted) {
      while (input.host.snapshot().state !== "stopped") {
        try { if (await input.host.migrationBarrier("release") === "idle") break; }
        catch { /* Reconcile the same barrier; never replay a business action. */ }
        await pause();
      }
    }
    if (!input.reopen()) return; // Shutdown owns the retained gates until exit.
    registry?.release(); admission?.release();
    if (remindersDrained) input.reminders.resumeAfterMigration();
    input.releaseOwner();
  })();
  try {
    if (!input.current() || input.host.snapshot().state !== "ready") throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
    const reminders = input.reminders.tryDrainForLifecycle();
    if (!reminders) throw new Error("ASSISTANT_LIFECYCLE_BUSY");
    await reminders;
    remindersDrained = true;
    admission = input.host.beginLifecycleAdmission();
    registry = input.projects.beginMigrationTransition();
    await Promise.all([admission.drained, registry.drained]);
    await input.drainQueues();
    await admission.seal();
    admission.check();
    if (!input.current()) throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
    barrierAttempted = true;
    await input.host.migrationBarrier("prepare");
    let state = await input.host.migrationBarrier("status");
    for (let attempt = 0; state === "probing" && attempt < 20 && input.current(); attempt++) {
      await pause(); state = await input.host.migrationBarrier("status");
    }
    if (state !== "ready" || !input.current()) throw new Error("ASSISTANT_LIFECYCLE_BUSY");
    admission.check();
    return { release, commit: () => {
      if (!input.current()) throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
      admission!.commit();
    } };
  } catch (error) {
    // Do not make a stalled release look like idle or start another owner.
    void release().catch(() => undefined);
    throw error;
  }
}
