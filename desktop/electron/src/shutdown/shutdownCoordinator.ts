export type BootstrapOwnershipMode = "attached" | "started";

export type ActiveWorkStatus = {
  active: boolean;
  message: string;
};

export type ShutdownDecision =
  | { allowed: true; reason: "no_active_work"; stopPythonLauncher: boolean }
  | { allowed: false; reason: "active_work_running"; message: string };

const ACTIVE_WORK_BLOCK_MESSAGE = "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。";

export async function decideShutdown(input: {
  ownershipMode: BootstrapOwnershipMode;
  activeWorkStatus: () => Promise<ActiveWorkStatus>;
}): Promise<ShutdownDecision> {
  const activeWork = await input.activeWorkStatus();
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
    stopPythonLauncher: input.ownershipMode === "started"
  };
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
