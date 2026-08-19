import type { LauncherLifecycleLease } from "../lifecycle/launcherLifecycleSupervisor.js";

export const ISOLATED_INSTANCE_READY_WAIT_MS = 180_000;

export type IsolatedInstanceSuperviseResult = "opened" | "error" | "ignored";

export type IsolatedInstanceSuperviseInput = {
  instanceId: string;
  url: string;
  lease: LauncherLifecycleLease;
  timeoutMs?: number;
  isCurrent: (lease: LauncherLifecycleLease) => boolean;
  claimReady: (lease: LauncherLifecycleLease) => boolean;
  completeReady: (lease: LauncherLifecycleLease) => boolean;
  releaseReadyClaim: (lease: LauncherLifecycleLease) => boolean;
  waitForHttp: (url: string, timeoutMs: number, signal: AbortSignal) => Promise<void>;
  openWindow: () => Promise<void>;
  closeWindowIfSuperseded: () => Promise<void>;
  closeWindowAfterReadyFailure: () => Promise<void>;
  markReady: (generation: number) => Promise<void>;
  markError: (generation: number, message: string) => Promise<void>;
};

export async function superviseIsolatedInstanceStart(
  input: IsolatedInstanceSuperviseInput
): Promise<IsolatedInstanceSuperviseResult> {
  const timeoutMs = Math.max(1, input.timeoutMs ?? ISOLATED_INSTANCE_READY_WAIT_MS);
  try {
    await input.waitForHttp(input.url, timeoutMs, input.lease.signal);
    if (!input.isCurrent(input.lease) || !input.claimReady(input.lease)) {
      return "ignored";
    }
    await input.openWindow();
    if (!input.isCurrent(input.lease)) {
      await input.closeWindowIfSuperseded();
      return "ignored";
    }
    await input.markReady(input.lease.generation);
    if (!input.isCurrent(input.lease)) {
      await input.closeWindowIfSuperseded();
      return "ignored";
    }
    if (!input.completeReady(input.lease)) {
      await input.closeWindowAfterReadyFailure();
      throw new Error(`isolated lifecycle READY completion failed for ${input.instanceId}`);
    }
  } catch (error: unknown) {
    if (input.lease.signal.aborted || !input.isCurrent(input.lease)) {
      return "ignored";
    }
    input.releaseReadyClaim(input.lease);
    const message = error instanceof Error ? error.message : String(error);
    try {
      await input.markError(input.lease.generation, message);
    } catch (markErrorFailure: unknown) {
      if (input.lease.signal.aborted || !input.isCurrent(input.lease)) {
        return "ignored";
      }
      throw markErrorFailure;
    }
    return input.isCurrent(input.lease) ? "error" : "ignored";
  }
  return "opened";
}
