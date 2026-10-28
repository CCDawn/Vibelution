import type { ProjectAdmissionSeal } from "../lifecycle/projectAdmission.js";
import type { WorkbenchNaturalJobRetirement } from "../process/workbenchJob.js";
import type { CapturedWorkbenchWindowRetirement, ElectronWindowProvider } from "../windows/electronWindowProvider.js";

export type ManagedLegacyRetirementResult = {
  state: "pending" | "managed_drained";
  /** Only captured main-process windows and captured Job objects are covered. */
  unmanagedSenders: "unknown";
  readyForCutover: false;
};
export type ManagedLegacyRetirement = {
  readonly state: "pending" | "managed_drained";
  readonly waitingFor: "window" | "close_transaction" | "drain" | "unknown" | null;
  readonly completion: Promise<ManagedLegacyRetirementResult>;
  /** Stop retries on owner shutdown; does not certify a drain. */
  dispose(): void;
};

/** Values and functions must come exclusively from trusted main-owned source,
 * window, admission and Job bindings. Never pass renderer/model input here. */
export type ManagedLegacyRetirementInput = {
  provider: ElectronWindowProvider;
  /** Only exact instances already proven to belong to the selected source. */
  instanceIds: readonly string[];
  /** Captured before starting, from identity-checked tracked Job handles. */
  jobs: readonly WorkbenchNaturalJobRetirement[];
  /** Already held synchronously before this operation starts; caller retains it. */
  admission: ProjectAdmissionSeal;
  /** Must synchronously revalidate physical source, instance/Job binding and the held seal. */
  verifyBinding(): void;
  /** Synchronously prove no original window close transaction/ACK is in flight. */
  verifyWindowCloseSettled(): void;
  /** Called only after admission and target windows have closed. */
  drainIngress(): Promise<void>;
  retryMs?: number;
};

function proof(check: () => void): void {
  if ((check as () => unknown)() !== undefined) throw new Error("LEGACY_RETIREMENT_BINDING_INVALID");
}

/** Observes user-driven window closure and retires only naturally exited Jobs
 * after admission and main-process ingress drain. A failure stays observable as
 * pending and is retried without discovering or killing replacement PIDs.
 * A returned managed_drained result is not a source/global quiescence proof. */
export function startManagedLegacyReminderRetirement(input: ManagedLegacyRetirementInput): ManagedLegacyRetirement {
  if (!input || !input.provider || typeof input.provider.hasPendingUserWorkbenchClose !== "function"
      || !Array.isArray(input.instanceIds) || !input.instanceIds.length
      || input.instanceIds.length > 128 || input.instanceIds.some(id => typeof id !== "string" || !id.trim() || id !== id.trim())
      || new Set(input.instanceIds).size !== input.instanceIds.length || !Array.isArray(input.jobs) || !input.jobs.length
      || input.jobs.length > 128 || input.jobs.some(job => typeof job !== "function" || typeof job.isCurrent !== "function"
        || typeof job.release !== "function" || !Number.isSafeInteger(job.pid) || job.pid <= 0)
      || !input.admission || typeof input.admission.drain !== "function" || typeof input.verifyBinding !== "function"
      || typeof input.verifyWindowCloseSettled !== "function"
      || typeof input.drainIngress !== "function") throw new Error("LEGACY_RETIREMENT_INVALID");
  const interval = input.retryMs ?? 250;
  if (!Number.isFinite(interval) || interval < 25 || interval > 10000) throw new Error("LEGACY_RETIREMENT_INVALID");
  const targets = new Set(input.instanceIds), jobs = [...input.jobs], retired = new Set<WorkbenchNaturalJobRetirement>();
  const captured = new Map<number, { row: string; handle: CapturedWorkbenchWindowRetirement }>();
  let initialCaptureAttempted = false;
  let initialCaptureComplete = false;
  let state: ManagedLegacyRetirement["state"] = "pending";
  let waitingFor: ManagedLegacyRetirement["waitingFor"] = "unknown";
  let stopped = false;
  let wake: (() => void) | undefined;
  let finish!: (value: ManagedLegacyRetirementResult) => void;
  const completion = new Promise<ManagedLegacyRetirementResult>(resolve => { finish = resolve; });
  const owner = Object.freeze({ get state() { return state; }, get waitingFor() { return waitingFor; }, completion, dispose: () => {
    if (stopped || state === "managed_drained") return;
    stopped = true;
    wake?.();
    finish({ state: "pending", unmanagedSenders: "unknown", readyForCutover: false });
  } });
  const check = () => { if (stopped) throw new Error("LEGACY_RETIREMENT_DISPOSED"); proof(input.verifyBinding); };

  const windowsClosed = (): boolean => {
    // Only the first synchronous inventory is eligible for capture. A later
    // same-instance window may be a replacement, even after admission drain.
    const mayCapture = !initialCaptureAttempted;
    initialCaptureAttempted = true;
    check();
    if (!mayCapture && !initialCaptureComplete) throw new Error("LEGACY_RETIREMENT_INITIAL_CAPTURE_UNAVAILABLE");
    const inventory = input.provider.completeWorkbenchWindowInventory();
    const rows = inventory.filter(row => row.instanceId && targets.has(row.instanceId));
    const windows: CapturedWorkbenchWindowRetirement[] = [];
    // An unattributed live window cannot be excluded from the target source.
    // It is never closed by this owner, and its presence prevents a drain claim.
    let unknown = inventory.some(row => row.kind === "unattributed");
    for (const row of rows) {
      const previous = captured.get(row.windowId), fingerprint = JSON.stringify(row);
      if (previous) {
        // Do not recapture a different document/window after an inspection or
        // close failure, even when it reuses an instance or window ID.
        if (previous.row !== fingerprint || previous.handle.isClosed()) { unknown = true; continue; }
        windows.push(previous.handle);
      } else {
        if (!mayCapture) { unknown = true; continue; }
        const handle = input.provider.captureWorkbenchWindowRetirement(row, { naturalOnly: true });
        if (!handle) { unknown = true; continue; }
        captured.set(row.windowId, { row: fingerprint, handle });
        windows.push(handle);
      }
    }
    if (mayCapture) initialCaptureComplete = !unknown;
    if (unknown) { waitingFor = "unknown"; return false; }
    if (windows.length || [...captured.values()].some(item => !item.handle.isClosed())) {
      waitingFor = "window";
      return false;
    }
    if (input.provider.completeWorkbenchWindowInventory().some(row => row.kind === "unattributed"
      || row.instanceId && targets.has(row.instanceId))) { waitingFor = "unknown"; return false; }
    return true;
  };

  const ready = (): boolean => {
    if (!windowsClosed()) return false;
    if (input.instanceIds.some(id => input.provider.hasPendingUserWorkbenchClose(id))) {
      waitingFor = "close_transaction";
      return false;
    }
    try { proof(input.verifyWindowCloseSettled); }
    catch { waitingFor = "close_transaction"; return false; }
    waitingFor = "drain";
    return true;
  };
  const retry = Symbol("retry");

  const run = async (): Promise<void> => {
    while (!stopped) {
      try {
        if (ready()) {
          await input.admission.drain();
          check();
          // A later window cannot be attributed solely by instance ID. It
          // remains untouched and makes this retirement pending.
          if (ready()) {
            await input.drainIngress();
            check();
            if (!ready()) throw retry;
            let complete = true;
            for (const job of jobs) {
              if (retired.has(job)) continue;
              if (!ready()) { complete = false; break; }
              // The captured closure itself rejects a replacement Job; it can
              // still confirm an already-released original after the reaper.
              if (!await job()) { complete = false; continue; }
              retired.add(job);
            }
            check();
            if (complete && retired.size === jobs.length && ready()) {
              await input.drainIngress();
              check();
              if (!ready()) throw retry;
              state = "managed_drained";
              waitingFor = null;
              finish({ state, unmanagedSenders: "unknown", readyForCutover: false });
              return;
            }
          }
        }
      } catch (error) { if (error !== retry) waitingFor = "unknown"; }
      if (stopped) return;
      await new Promise<void>(resolve => {
        const timer = setTimeout(() => { wake = undefined; resolve(); }, interval);
        timer.unref?.();
        wake = () => { clearTimeout(timer); wake = undefined; resolve(); };
      });
    }
  };
  void run();
  return owner;
}
