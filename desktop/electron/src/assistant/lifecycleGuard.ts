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

/** Upper bound on waiting for one host's own convergence during release. A
 * dead host with an exhausted respawn budget never reaches "stopped", so an
 * unbounded wait would keep the lease owner and every producer fence (and in
 * main, the migrationRunning latch) captured forever. After the budget the
 * fences are handed back with a warning instead of deadlocking the shell. */
export const ASSISTANT_LIFECYCLE_RELEASE_WAIT_BUDGET_MS = 30_000;

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
  /** Retrying callers need proof that the failed lease released native admission. */
  waitForFailedRelease?: boolean;
  /** Test seam; production uses ASSISTANT_LIFECYCLE_RELEASE_WAIT_BUDGET_MS. */
  releaseWaitBudgetMs?: number;
}): Promise<AssistantLifecycleLease> {
  let admission: ReturnType<Host["beginLifecycleAdmission"]> | undefined;
  let registry: ReturnType<typeof input.projects.beginMigrationTransition> | undefined;
  let remindersDrained = false, barrierAttempted = false;
  let nativeReleaseConfirmed = false;
  let localReleaseConfirmed = false;
  let stage = "reminder_drain";
  let releasing: Promise<void> | undefined;
  const pause = () => new Promise<void>(resolve => { const timer = setTimeout(resolve, 100); timer.unref?.(); });
  const release = (): Promise<void> => releasing ??= (async () => {
    try {
      // A lost reply does not prove native admission reopened. Retain the same
      // owner and all producer fences until release, that exact host's stop,
      // or the bounded convergence budget below.
      if (barrierAttempted) {
        const budget = input.releaseWaitBudgetMs ?? ASSISTANT_LIFECYCLE_RELEASE_WAIT_BUDGET_MS;
        const deadline = Date.now() + budget;
        while (input.host.snapshot().state !== "stopped") {
          try {
            if (await input.host.migrationBarrier("release") === "idle") {
              nativeReleaseConfirmed = true;
              break;
            }
          }
          catch { /* Reconcile the same barrier; never replay a business action. */ }
          if (Date.now() >= deadline) {
            console.warn(`ASSISTANT_LIFECYCLE_RELEASE_WAIT_TIMEOUT `
              + `state=${input.host.snapshot().state} budgetMs=${budget}`);
            break;
          }
          await pause();
        }
        nativeReleaseConfirmed ||= input.host.snapshot().state === "stopped";
      }
      if (!input.reopen()) return; // Shutdown owns the retained gates until exit.
      registry?.release(); admission?.release();
      if (remindersDrained) input.reminders.resumeAfterMigration();
      localReleaseConfirmed = true;
    } finally {
      // The owner latch must reset on every releasable path, including a
      // fencing failure inside the handoff above; otherwise the shell refuses
      // every later lifecycle command forever.
      if (input.reopen()) input.releaseOwner();
      else localReleaseConfirmed = false;
    }
  })();
  try {
    input.signal?.throwIfAborted();
    if (!input.current() || input.host.snapshot().state !== "ready") throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
    const reminders = input.reminders.tryDrainForLifecycle();
    if (!reminders) throw new Error("ASSISTANT_LIFECYCLE_BUSY");
    await reminders;
    remindersDrained = true;
    input.signal?.throwIfAborted();
    stage = "host_admission";
    admission = input.host.beginLifecycleAdmission();
    registry = input.projects.beginMigrationTransition();
    await Promise.all([admission.drained, registry.drained]);
    input.signal?.throwIfAborted();
    stage = "queue_drain";
    await input.drainQueues();
    input.signal?.throwIfAborted();
    stage = "host_admission";
    await admission.seal();
    input.signal?.throwIfAborted();
    admission.check();
    if (!input.current()) throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
    stage = "native_barrier";
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
    stage = "host_admission";
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
    if (input.waitForFailedRelease && error instanceof Error && error.message === "ASSISTANT_LIFECYCLE_BUSY") {
      console.warn(`ASSISTANT_LIFECYCLE_BUSY stage=${stage}`);
    }
    if (input.waitForFailedRelease) {
      try { await release(); }
      catch (cause) { throw new Error("ASSISTANT_LIFECYCLE_RELEASE_UNCONFIRMED", { cause }); }
      if (!localReleaseConfirmed || (barrierAttempted && !nativeReleaseConfirmed)) {
        throw new Error("ASSISTANT_LIFECYCLE_RELEASE_UNCONFIRMED", { cause: error });
      }
    } else if (input.signal) await release();
    else void release().catch(() => undefined);
    throw error;
  }
}
