import type { SupervisedWorktreeRun } from "../api/types";

const RECENT_SUPERVISED_WORKTREE_RUN_ID_KEY = "vibelution.supervised-evolution.recent-worktree-run-id";

type RunIdStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
};

export type SupervisedWorktreeLedgerSummary = {
  bundleName: string;
  candidateScore: number | null;
  decision: string;
  description: string;
  reviewStatus: string;
  roleSessionCount: number;
  runId: string;
  status: string;
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
  return hasSelfEvolutionOrigin;
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

  return runs.find((run) => {
    const outcome = String(run.outcome || "").trim().toLowerCase();
    return (
      !isSelfEvolutionWorktreeRun(run)
      && String(run.status || "").trim().toLowerCase() === "done"
      && ["needs_manual_decision", "awaiting_user_approval"].includes(outcome)
    );
  }) ?? null;
}

export function buildSupervisedWorktreeLedgerSummary(
  run: SupervisedWorktreeRun | null | undefined,
): SupervisedWorktreeLedgerSummary | null {
  if (!run || isSelfEvolutionWorktreeRun(run)) {
    return null;
  }
  const reviewGate = run.reviewGate ?? run.mergeAnalysis?.reviewGate;
  const roleSessionIds = new Set([
    run.baselineConversationSessionId,
    run.rerunConversationSessionId,
    run.judgeConversationSessionId,
    run.baselineJudgment?.conversationSessionId,
    run.candidateJudgment?.conversationSessionId,
  ].map((value) => String(value || "").trim()).filter(Boolean));
  const candidateScore = run.decision?.candidateScore ?? run.candidateJudgment?.score;

  return {
    runId: run.runId,
    status: String(run.status || "").trim(),
    decision: String(run.decision?.judgeDecision || run.candidateJudgment?.decision || "").trim(),
    description: String(run.latestMessage || reviewGate?.reason || "").trim(),
    reviewStatus: String(reviewGate?.status || "").trim().toLowerCase(),
    roleSessionCount: roleSessionIds.size,
    candidateScore: typeof candidateScore === "number" && Number.isFinite(candidateScore)
      ? candidateScore
      : null,
    bundleName: String(run.bundleName || "").trim(),
  };
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
