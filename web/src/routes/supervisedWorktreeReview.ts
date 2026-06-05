import type { SupervisedWorktreeRun } from "../api/types";

export function isSelfEvolutionWorktreeRun(run: SupervisedWorktreeRun | null | undefined) {
  if (!run) {
    return false;
  }
  const sourceTrack = String(run.selfEvolutionOrigin?.sourceTrack || "").trim().toLowerCase();
  return Boolean(run.selfEvolutionOrigin)
    || sourceTrack === "self_evolution"
    || Boolean(run.reviewGate?.required)
    || Boolean(run.mergeAnalysis?.reviewGate?.required);
}
