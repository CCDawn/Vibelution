import type { SupervisedWorktreeRun } from "../api/types";

const RECENT_SUPERVISED_WORKTREE_RUN_ID_KEY = "vibelution.supervised-evolution.recent-worktree-run-id";

type RunIdStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
};

export function supervisedRunSessionStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function isSelfEvolutionWorktreeRun(run: SupervisedWorktreeRun | null | undefined) {
  if (!run) {
    return false;
  }
  const origin = run.selfEvolutionOrigin;
  const sourceTrack = String(origin?.sourceTrack || "").trim().toLowerCase();
  const hasSelfEvolutionOrigin = Boolean(
    sourceTrack === "self_evolution"
    || String(origin?.sourceSelfRunId || "").trim()
    || String(origin?.sourceCandidateId || "").trim()
    || String(origin?.goal || "").trim()
    || String(origin?.riskReason || "").trim()
    || origin?.requiresSupervisedReview,
  );
  return hasSelfEvolutionOrigin
    || Boolean(run.reviewGate?.required)
    || Boolean(run.mergeAnalysis?.reviewGate?.required);
}

export function selectRecentSupervisedWorktreeRun(
  runs: SupervisedWorktreeRun[],
  runId: string | null | undefined,
) {
  const normalizedRunId = String(runId || "").trim();
  if (normalizedRunId) {
    const rememberedRun = runs.find((run) => (
      run.runId === normalizedRunId
      && !isSelfEvolutionWorktreeRun(run)
    ));
    if (rememberedRun) {
      return rememberedRun;
    }
  }

  return runs.find((run) => (
    !isSelfEvolutionWorktreeRun(run)
    && String(run.status || "").trim().toLowerCase() === "done"
    && String(run.outcome || "").trim().toLowerCase() === "needs_manual_decision"
  )) ?? null;
}

export function readRecentSupervisedWorktreeRunId(storage: RunIdStorage | null | undefined) {
  if (!storage) {
    return null;
  }
  try {
    return String(storage.getItem(RECENT_SUPERVISED_WORKTREE_RUN_ID_KEY) || "").trim() || null;
  } catch {
    return null;
  }
}

export function rememberRecentSupervisedWorktreeRunId(
  storage: RunIdStorage | null | undefined,
  runId: string | null | undefined,
) {
  const normalizedRunId = String(runId || "").trim();
  if (!storage || !normalizedRunId) {
    return;
  }
  try {
    storage.setItem(RECENT_SUPERVISED_WORKTREE_RUN_ID_KEY, normalizedRunId);
  } catch {
    // Storage can be unavailable in hardened browser contexts; live state still works.
  }
}
