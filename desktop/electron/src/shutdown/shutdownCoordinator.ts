export type BootstrapOwnershipMode = "attached" | "started";

export type ActiveWorkStatus = {
  active: boolean;
  message: string;
};

export type ShutdownDecision =
  | { allowed: true; reason: "no_active_work"; stopPythonLauncher: boolean }
  | { allowed: false; reason: "active_work_running" | "active_work_status_unavailable"; message: string };

type ApprovedShutdownDecision = Extract<ShutdownDecision, { allowed: true }>;
type DeniedShutdownDecision = Extract<ShutdownDecision, { allowed: false }>;

const ACTIVE_WORK_BLOCK_MESSAGE = "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。";
const ACTIVE_WORK_STATUS_UNAVAILABLE_MESSAGE = "暂时无法确认是否有进行中的任务，已取消退出。请稍后重试。";

export async function decideShutdown(input: {
  ownershipMode: BootstrapOwnershipMode;
  activeWorkStatus: () => Promise<ActiveWorkStatus>;
}): Promise<ShutdownDecision> {
  let activeWork: ActiveWorkStatus;
  try {
    activeWork = await input.activeWorkStatus();
  } catch {
    return {
      allowed: false,
      reason: "active_work_status_unavailable",
      message: ACTIVE_WORK_STATUS_UNAVAILABLE_MESSAGE
    };
  }
  if (activeWork.active) {
    return {
      allowed: false,
      reason: "active_work_running",
      message: ACTIVE_WORK_BLOCK_MESSAGE
    };
  }
  return {
    allowed: true,
    reason: "no_active_work",
    // Leftover Python :8765 is not a second product control plane. Reap it on
    // every approved quit, including attached bootstraps that never spawned it.
    stopPythonLauncher: true
  };
}

export async function executeShutdownAuthorizationBoundary(input: {
  authorize: () => Promise<ShutdownDecision>;
  onDenied: (decision: DeniedShutdownDecision) => void | Promise<void>;
  runApproved: (decision: ApprovedShutdownDecision) => Promise<void>;
  failOpenAfterApproval: (decision: ApprovedShutdownDecision, error: unknown) => Promise<void>;
}): Promise<ShutdownDecision> {
  const decision = await input.authorize();
  if (!decision.allowed) {
    await input.onDenied(decision);
    return decision;
  }
  try {
    await input.runApproved(decision);
  } catch (error: unknown) {
    await input.failOpenAfterApproval(decision, error);
  }
  return decision;
}

export function isActiveWorkProbeAuthFailure(error: unknown): boolean {
  const detail = (error instanceof Error ? error.message : String(error)).toLowerCase();
  return (
    /(?:^|\D)(?:401|403)(?:\D|$)/.test(detail) ||
    detail.includes("unauthorized") ||
    detail.includes("forbidden")
  );
}

export function isActiveWorkProbeTransientFailure(error: unknown): boolean {
  const detail = (error instanceof Error ? error.message : String(error)).toLowerCase();
  return isActiveWorkProbeAuthFailure(error) || detail.includes("timed out");
}

export async function resolveQuitActiveWorkStatus(input: {
  probe: () => Promise<ActiveWorkStatus>;
  recoverAndRetry?: () => Promise<ActiveWorkStatus>;
}): Promise<ActiveWorkStatus> {
  try {
    return await input.probe();
  } catch (error) {
    if (!isActiveWorkProbeTransientFailure(error)) {
      throw error;
    }
    if (input.recoverAndRetry) {
      try {
        return await input.recoverAndRetry();
      } catch (retryError) {
        if (isActiveWorkProbeAuthFailure(retryError)) {
          return { active: false, message: "" };
        }
        throw retryError;
      }
    }
    if (isActiveWorkProbeAuthFailure(error)) {
      return { active: false, message: "" };
    }
    throw error;
  }
}

export async function fetchLauncherActiveWorkStatus(input: {
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
}): Promise<ActiveWorkStatus> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(`${new URL(input.launcherOrigin).origin}/api/launcher/status`, {
    headers: {
      "X-Vibelution-Control-Token": input.controlToken
    }
  });
  if (!response.ok) {
    throw new Error(`launcher active-work status request failed: ${response.status}`);
  }
  const payload = (await response.json()) as Record<string, unknown>;
  const activeWorkCount = readActiveWorkCount(payload);
  return {
    active: activeWorkCount > 0,
    message: activeWorkCount > 0 ? `${activeWorkCount} active work item(s) block lifecycle commands.` : ""
  };
}

function readActiveWorkCount(payload: Record<string, unknown>): number {
  const lifecycleProof = payload.lifecycleProof;
  if (!isRecord(lifecycleProof)) {
    return 0;
  }
  const activeWorkRuns = lifecycleProof.activeWorkRuns;
  if (!isRecord(activeWorkRuns)) {
    return 0;
  }
  const count = Number(activeWorkRuns.count ?? 0);
  return Number.isFinite(count) && count > 0 ? count : 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
