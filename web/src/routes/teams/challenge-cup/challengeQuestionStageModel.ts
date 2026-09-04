/**
 * Challenge Cup question-level stage projection (display layer only).
 *
 * Derives the two-stage presentation state (假说生成 / 研究计划与实验) from
 * data the question detail payload already carries — the same authorities the
 * panel already renders (record status + selection human gate). The canonical
 * workflow proceeds into research planning once the hypothesis is settled.
 */
import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";

/** Stage one lifecycle: generating until the stage-one acceptance gate passes. */
export type ChallengeQuestionStageOneStatus = "hypothesis_generating" | "hypothesis_settled";

export type ChallengeQuestionStageProjection = {
  /** 假说生成：run 活跃/候选评审中 → generating；stage-one 收门通过 → settled。 */
  stageOne: ChallengeQuestionStageOneStatus;
  /** 研究计划与实验是否已进入可执行阶段。 */
  stageTwoActive: boolean;
  /** 研究计划产物是否存在于本 run 输出。 */
  hasResearchPlanProposal: boolean;
};

function stageOneGateApproved(
  output: ChallengeQuestionRunDetailPayload["output"],
): boolean {
  return output.selection.human_gate.decision === "approved";
}

/**
 * Single derivation used by both the header chips and the zone headings so the
 * page can never disagree with itself. `record.status === "approved"` is the
 * registered acceptance authority; the selection human gate is the in-output
 * mirror of the same stage-one acceptance.
 */
export function deriveChallengeQuestionStageProjection(
  detail: Pick<ChallengeQuestionRunDetailPayload, "record" | "output"> | undefined | null,
): ChallengeQuestionStageProjection {
  const settled = Boolean(
    detail
      && (detail.record.status === "approved" || stageOneGateApproved(detail.output)),
  );
  const plan = detail?.output.research_plan;
  const hasResearchPlanProposal = Boolean(
    plan
      && (String(plan.objective || "").trim()
        || String(plan.method || "").trim()
        || (Array.isArray(plan.work_packages) && plan.work_packages.length > 0)),
  );
  return {
    stageOne: settled ? "hypothesis_settled" : "hypothesis_generating",
    stageTwoActive: settled,
    hasResearchPlanProposal,
  };
}

/** Chinese/English copy for the stage-one status chip. */
export function stageOneStatusCopy(
  status: ChallengeQuestionStageOneStatus,
  lang: "zh" | "en",
): string {
  if (status === "hypothesis_settled") {
    return lang === "zh" ? "假说已定" : "Hypothesis settled";
  }
  return lang === "zh" ? "假说生成中" : "Generating";
}

/** Chinese/English copy for the stage-two state chip. */
export function stageTwoStatusCopy(active: boolean, lang: "zh" | "en"): string {
  if (active) return lang === "zh" ? "进行中" : "In progress";
  return lang === "zh" ? "等待假说确定" : "Awaiting hypothesis";
}

/** Zone titles — descriptive names, never ordinals. */
export function stageZoneTitle(
  zone: "hypothesis" | "plan",
  lang: "zh" | "en",
): string {
  if (zone === "hypothesis") {
    return lang === "zh" ? "假说生成" : "Hypothesis generation";
  }
  return lang === "zh" ? "研究计划与实验" : "Research plan & experiment";
}

/** One-line progression semantics for the plan and experiment zone. */
export function stageTwoProgressHint(active: boolean, lang: "zh" | "en"): string {
  if (active) {
    return lang === "zh"
      ? "假说已确定，主流程将继续推进研究计划、协议与实验。"
      : "The hypothesis is settled; the main workflow continues through planning, protocol, and experiments.";
  }
  return lang === "zh"
    ? "完成假说确定后，主流程会自动进入研究计划与实验。"
    : "The main workflow enters research planning and experiments after the hypothesis is settled.";
}
