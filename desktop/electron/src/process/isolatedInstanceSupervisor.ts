import {
  OWNER_LEASE_HEARTBEAT_MS,
  remainingDeadlineMs
} from "../lifecycle/instanceRegistryStore.js";
import type { LauncherLifecycleLease } from "../lifecycle/launcherLifecycleSupervisor.js";

export const ISOLATED_INSTANCE_READY_WAIT_MS = 180_000;

export type IsolatedInstanceSuperviseResult = "opened" | "error" | "ignored";

export type IsolatedInstanceSuperviseInput = {
  instanceId: string;
  url: string;
  lease: LauncherLifecycleLease;
  timeoutMs?: number;
  deadlineAt?: string;
  nowMs?: number;
  heartbeatMs?: number;
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
  renewLease?: () => Promise<void>;
};

export function resolveIsolatedReadyTimeoutMs(input: {
  timeoutMs?: number;
  deadlineAt?: string;
  nowMs?: number;
}): number {
  if (typeof input.timeoutMs === "number" && Number.isFinite(input.timeoutMs) && input.timeoutMs > 0) {
    return Math.max(1, Math.trunc(input.timeoutMs));
  }
  return Math.max(1, remainingDeadlineMs(input.deadlineAt, input.nowMs));
}

export async function superviseIsolatedInstanceStart(
  input: IsolatedInstanceSuperviseInput
): Promise<IsolatedInstanceSuperviseResult> {
  const timeoutMs = resolveIsolatedReadyTimeoutMs(input);
  const heartbeatMs = Math.max(1, input.heartbeatMs ?? OWNER_LEASE_HEARTBEAT_MS);
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  const stopHeartbeat = (): void => {
    if (heartbeat !== undefined) {
      clearInterval(heartbeat);
      heartbeat = undefined;
    }
  };
  try {
    if (input.renewLease) {
      await input.renewLease();
      heartbeat = setInterval(() => {
        void input.renewLease?.().catch(() => undefined);
      }, heartbeatMs);
    }
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
  } finally {
    stopHeartbeat();
  }
  return "opened";
}
