import type { EvolutionActiveRun } from "../api/types";

export function normalizedSupervisedRunStatus(status: string) {
  return String(status || "").trim().toLowerCase();
}

export function isLiveSupervisedRunStatus(status: string) {
  return ["queued", "running", "paused", "stopping"].includes(normalizedSupervisedRunStatus(status));
}

export function isTerminalSupervisedRunStatus(status: string) {
  return ["done", "failed", "cancelled"].includes(normalizedSupervisedRunStatus(status));
}

export function sameSupervisedRun(left: EvolutionActiveRun | null | undefined, right: EvolutionActiveRun | null | undefined) {
  const leftRunId = String(left?.runId || "").trim();
  const rightRunId = String(right?.runId || "").trim();
  return Boolean(leftRunId && rightRunId && leftRunId === rightRunId);
}

export function shouldIgnoreActiveRunSnapshot(
  activeRun: EvolutionActiveRun | null | undefined,
  liveRun: EvolutionActiveRun | null | undefined,
) {
  return Boolean(
    activeRun
      && liveRun
      && sameSupervisedRun(activeRun, liveRun)
      && isTerminalSupervisedRunStatus(liveRun.status),
  );
}

export function selectSupervisedRunStreamTarget(
  activeRun: EvolutionActiveRun | null | undefined,
  liveRun: EvolutionActiveRun | null | undefined,
) {
  if (!shouldIgnoreActiveRunSnapshot(activeRun, liveRun) && activeRun && isLiveSupervisedRunStatus(activeRun.status)) {
    return activeRun;
  }
  if (liveRun && isLiveSupervisedRunStatus(liveRun.status)) {
    return liveRun;
  }
  return null;
}
