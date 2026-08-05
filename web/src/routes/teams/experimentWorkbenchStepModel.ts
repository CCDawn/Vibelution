/**
 * Product workbench steps for experiment planning.
 * One current step + one primary action — not a full protocol form dump.
 */
export type ExperimentWorkbenchStepId = "setup" | "review" | "protocol" | "execute";

export type ExperimentWorkbenchStepDef = {
  id: ExperimentWorkbenchStepId;
  zh: string;
  en: string;
};

export const EXPERIMENT_WORKBENCH_STEPS: ExperimentWorkbenchStepDef[] = [
  { id: "setup", zh: "配置实验", en: "Setup" },
  { id: "review", zh: "审查假设", en: "Review" },
  { id: "protocol", zh: "冻结协议", en: "Freeze" },
  { id: "execute", zh: "试跑放行", en: "Run" },
];

export type ExperimentWorkbenchStepInput = {
  hasActivePlan: boolean;
  hasApprovedHypothesis: boolean;
  designFrozen: boolean;
  readyForBoundedSmoke: boolean;
};

/** Default landing step from plan lifecycle (user can still switch unlocked tabs). */
export function resolveExperimentWorkbenchStep(
  input: ExperimentWorkbenchStepInput,
): ExperimentWorkbenchStepId {
  if (!input.hasActivePlan) {
    return "setup";
  }
  if (!input.hasApprovedHypothesis) {
    return "review";
  }
  if (!input.designFrozen) {
    return "protocol";
  }
  return "execute";
}

export function isExperimentWorkbenchStepUnlocked(
  step: ExperimentWorkbenchStepId,
  input: ExperimentWorkbenchStepInput,
): boolean {
  if (step === "setup") {
    return true;
  }
  if (step === "review") {
    return input.hasActivePlan;
  }
  if (step === "protocol") {
    return input.hasActivePlan && input.hasApprovedHypothesis;
  }
  return input.hasActivePlan && input.hasApprovedHypothesis && input.designFrozen;
}

/** Short human label for long protocol / adapter strings. Full value stays in title. */
export function shortProtocolLabel(raw: string, max = 42): string {
  const text = String(raw || "").trim().replace(/\s+/g, " ");
  if (!text) {
    return "";
  }
  if (text.length <= max) {
    return text;
  }
  return `${text.slice(0, Math.max(1, max - 1))}…`;
}
