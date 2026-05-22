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

export function requireEvolutionRunSnapshot<T extends { runId?: string } | null | undefined>(
  snapshot: T,
  actionLabel: string,
): Exclude<T, null | undefined> {
  const runId = String(snapshot?.runId || "").trim();
  if (!snapshot || !runId) {
    throw new Error(`${actionLabel} response did not include a runId.`);
  }
  return snapshot as Exclude<T, null | undefined>;
}

export function selectRunSnapshotWithRunId<T extends { runId?: string } | null | undefined>(
  snapshot: T,
): Exclude<T, null | undefined> | null {
  const runId = String(snapshot?.runId || "").trim();
  if (!snapshot || !runId) {
    return null;
  }
  return snapshot as Exclude<T, null | undefined>;
}

export function parseRunStreamSnapshot<T extends { runId?: string }>(
  data: string,
  actionLabel: string,
): T | null {
  let payload: { runId?: string; snapshot?: T };
  try {
    payload = JSON.parse(data) as { runId?: string; snapshot?: T };
  } catch {
    return null;
  }
  const envelopeRunId = String(payload.runId || "").trim();
  if (!envelopeRunId) {
    return null;
  }
  const snapshot = selectRunSnapshotWithRunId(payload.snapshot);
  if (!snapshot) {
    return null;
  }
  const snapshotRunId = String(snapshot.runId || "").trim();
  if (envelopeRunId !== snapshotRunId) {
    return null;
  }
  return requireEvolutionRunSnapshot(snapshot, actionLabel);
}
