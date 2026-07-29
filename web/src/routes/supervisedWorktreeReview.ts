import type { SupervisedWorktreeRun } from "../api/types";

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
