/**
 * Challenge Cup question-level stage projection (display layer only).
 *
 * Derives the two-stage presentation state (假说生成 / 研究计划与实验) from
 * data the question detail payload already carries — the same authorities the
 * panel already renders (record status + selection human gate). Stage two is
 * never auto-activated server-side (allowPhaseTwoAdvance=false), so the stage
 * projection treats "未激活" as the constant default, not a fetched state.
 */
import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";

/** Stage one lifecycle: generating until the stage-one acceptance gate passes. */
export type ChallengeQuestionStageOneStatus = "hypothesis_generating" | "hypothesis_settled";

export type ChallengeQuestionStageProjection = {
  /** 假说生成：run 活跃/候选评审中 → generating；stage-one 收门通过 → settled。 */
  stageOne: ChallengeQuestionStageOneStatus;
  /** 研究计划与实验：恒为未激活（二阶段只能按题显式开启，永不自动激活）。 */
  stageTwoActive: false;
  /** 历史/预投影研究计划产物是否存在于本 run 输出（SCI-091 类历史题）。 */
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
    stageTwoActive: false,
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

/** Chinese/English copy for the constant stage-two state chip. */
export function stageTwoStatusCopy(lang: "zh" | "en"): string {
  return lang === "zh" ? "未激活" : "Inactive";
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

/** One-line stage-two activation semantics shown with the inactive zone. */
export function stageTwoInactiveHint(lang: "zh" | "en"): string {
  return lang === "zh"
    ? "第二阶段未激活，需按题显式开启；以下内容为历史/预投影（proposal only）产物，仅供参考。"
    : "Stage two is inactive and must be enabled explicitly per question; content below is historical / proposal-only.";
}
