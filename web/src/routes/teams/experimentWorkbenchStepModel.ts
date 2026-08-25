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

/**
 * Hypothesis-level checkpoint steps (backend hypothesisProgress) mapped to the
 * product workbench steps above, so "resume" lands on the next unfinished step.
 */
export const HYPOTHESIS_PROGRESS_STEP_IDS = ["design", "smoke", "full_run", "evaluation", "promotion"] as const;

export type HypothesisProgressStepId = (typeof HYPOTHESIS_PROGRESS_STEP_IDS)[number];

const HYPOTHESIS_PROGRESS_STEP_LABELS: Record<string, { zh: string; en: string }> = {
  design: { zh: "实验设计", en: "Design" },
  smoke: { zh: "试跑", en: "Trial run" },
  full_run: { zh: "正式运行", en: "Full run" },
  evaluation: { zh: "结果评估", en: "Evaluation" },
  promotion: { zh: "成果入库", en: "Promotion" },
};

export function hypothesisProgressStepLabel(step: string, lang: "zh" | "en"): string {
  const label = HYPOTHESIS_PROGRESS_STEP_LABELS[step];
  if (!label) {
    return step;
  }
  return lang === "zh" ? label.zh : label.en;
}

/** Workbench step that owns the given hypothesis checkpoint step. */
export function workbenchStepForHypothesisProgress(nextStep: string): ExperimentWorkbenchStepId {
  if (nextStep === "design") {
    return "protocol";
  }
  if (nextStep === "smoke" || nextStep === "full_run" || nextStep === "evaluation" || nextStep === "promotion") {
    return "execute";
  }
  return "review";
}
