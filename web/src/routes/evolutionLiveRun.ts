import type {
  EvolutionActiveRun,
  EvolutionRunCommandAccepted,
  EvolutionRunCommandStatus,
  SupervisedWorktreeRun,
} from "../api/types";

export type SupervisedRunMonitorSource =
  | { kind: "worktree"; run: SupervisedWorktreeRun }
  | { kind: "legacy"; run: EvolutionActiveRun };

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

/**
 * The worktree runner is the authority for the supervised four-stage workflow.
 * Prefer its live snapshot over the legacy active-run projection so the live
 * monitor never renders an idle state while a worktree run is progressing.
 */
export function selectSupervisedRunMonitorSource(input: {
  worktreeRun: SupervisedWorktreeRun | null | undefined;
  activeRun: EvolutionActiveRun | null | undefined;
  liveRun: EvolutionActiveRun | null | undefined;
}): SupervisedRunMonitorSource | null {
  if (input.worktreeRun && isLiveSupervisedRunStatus(input.worktreeRun.status)) {
    return { kind: "worktree", run: input.worktreeRun };
  }

  const legacyRun = selectSupervisedRunStreamTarget(input.activeRun, input.liveRun);
  return legacyRun ? { kind: "legacy", run: legacyRun } : null;
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

export function isEvolutionRunCommandAccepted(value: unknown): value is EvolutionRunCommandAccepted {
  const payload = value as Partial<EvolutionRunCommandAccepted> | null | undefined;
  return Boolean(
    payload
      && payload.accepted === true
      && String(payload.commandId || "").trim()
      && String(payload.commandType || "").trim(),
  );
}

export function isCompletedEvolutionRunCommandFailure(
  value: unknown,
): value is EvolutionRunCommandStatus & { completed: true; ok: false } {
  const payload = value as Partial<EvolutionRunCommandStatus> | null | undefined;
  return Boolean(
    payload
      && String(payload.commandId || "").trim()
      && payload.completed === true
      && payload.ok === false,
  );
}

export function isCompletedEvolutionRunCommandSuccess(
  value: unknown,
): value is EvolutionRunCommandStatus & { completed: true; ok: true } {
  const payload = value as Partial<EvolutionRunCommandStatus> | null | undefined;
  return Boolean(
    payload
      && String(payload.commandId || "").trim()
      && payload.completed === true
      && payload.ok === true,
  );
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
