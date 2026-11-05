import type { AssistantHost } from "./assistantHost.js";
import type { AssistantReminderPump } from "./reminderPump.js";
import type { AssistantProjectRegistryConnection } from "./projectRegistryConnection.js";
import type { ActiveWorkStatus } from "../shutdown/shutdownCoordinator.js";

/** Precedence: active > producer-unknown > unobservable > idle. A pure
 * observation failure never poisons the other source's conclusion on its own;
 * only in-flight-producer "unknown" can override an idle reading. */
export function combineAssistantActiveWork(workspace: ActiveWorkStatus, assistant: ActiveWorkStatus): ActiveWorkStatus {
  const active = [workspace, assistant].filter(row => row.state === "active");
  if (active.length) return { state: "active", message: active[0].message,
    count: active.reduce((sum, row) => sum + (row.count ?? 1), 0), items: active.flatMap(row => row.items ?? []) };
  const ambiguous = [workspace, assistant].find(row => row.state === "unknown");
  if (ambiguous) return ambiguous;
  const unobservable = [workspace, assistant].find(row => row.state === "unobservable");
  if (unobservable) return unobservable;
  return workspace;
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
  signal?: AbortSignal;
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
    input.signal?.throwIfAborted();
    if (!input.current() || input.host.snapshot().state !== "ready") throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
    const reminders = input.reminders.tryDrainForLifecycle();
    if (!reminders) throw new Error("ASSISTANT_LIFECYCLE_BUSY");
    await reminders;
    remindersDrained = true;
    input.signal?.throwIfAborted();
    admission = input.host.beginLifecycleAdmission();
    registry = input.projects.beginMigrationTransition();
    await Promise.all([admission.drained, registry.drained]);
    input.signal?.throwIfAborted();
    await input.drainQueues();
    input.signal?.throwIfAborted();
    await admission.seal();
    input.signal?.throwIfAborted();
    admission.check();
    if (!input.current()) throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
    barrierAttempted = true;
    // Cancellation stops the next phase, never an RPC already owning native
    // admission. A delayed prepare must settle before its release is sent.
    await input.host.migrationBarrier("prepare");
    input.signal?.throwIfAborted();
    let state = await input.host.migrationBarrier("status");
    input.signal?.throwIfAborted();
    for (let attempt = 0; state === "probing" && attempt < 20 && input.current(); attempt++) {
      await pause();
      input.signal?.throwIfAborted();
      state = await input.host.migrationBarrier("status");
      input.signal?.throwIfAborted();
    }
    if (state !== "ready" || !input.current()) throw new Error("ASSISTANT_LIFECYCLE_BUSY");
    admission.check();
    return { release, commit: () => {
      input.signal?.throwIfAborted();
      if (releasing) throw new Error("ASSISTANT_LIFECYCLE_BUSY");
      if (!input.current()) throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
      admission!.commit();
    } };
  } catch (error) {
    // Do not make a stalled release look like idle or start another owner.
    // Cancellable callers use rejection as the handoff to ordinary stop, so
    // they must not observe it until this same barrier confirms release.
    if (input.signal) await release();
    else void release().catch(() => undefined);
    throw error;
  }
}
