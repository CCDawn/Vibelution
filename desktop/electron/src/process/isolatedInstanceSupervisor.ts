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
  retireBackend?: (message: string) => Promise<void>;
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
  let httpReady = false;
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
    httpReady = true;
    if (!input.isCurrent(input.lease)) {
      return "ignored";
    }
    if (!input.claimReady(input.lease)) {
      throw new Error(`isolated lifecycle READY claim failed for ${input.instanceId}`);
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
      throw new Error(`isolated lifecycle READY completion failed for ${input.instanceId}`);
    }
  } catch (error: unknown) {
    if (input.lease.signal.aborted || !input.isCurrent(input.lease)) {
      return "ignored";
    }
    input.releaseReadyClaim(input.lease);
    const message = error instanceof Error ? error.message : String(error);
    const compensationErrors: string[] = [];
    if (httpReady && input.isCurrent(input.lease)) {
      try {
        await input.closeWindowAfterReadyFailure();
      } catch (closeError: unknown) {
        compensationErrors.push(
          `isolated window compensation failed: ${closeError instanceof Error ? closeError.message : String(closeError)}`
        );
      }
    }
    if (input.isCurrent(input.lease) && input.retireBackend) {
      try {
        await input.retireBackend(message);
      } catch (retireError: unknown) {
        compensationErrors.push(
          `isolated backend compensation failed: ${retireError instanceof Error ? retireError.message : String(retireError)}`
        );
      }
    }
    if (input.lease.signal.aborted || !input.isCurrent(input.lease)) {
      return "ignored";
    }
    const failureMessage = [message, ...compensationErrors].filter(Boolean).join("; ");
    try {
      await input.markError(input.lease.generation, failureMessage);
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
