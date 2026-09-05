/**
 * Challenge Cup question-level stage projection (display layer only).
 *
 * Derives the two-stage presentation state (假说生成 / 研究计划与实验) from
 * data the question detail payload already carries — the same authorities the
 * panel already renders (record status + selection human gate). Phase-two
 * eligibility comes only from the server's approval/knowledge boundary.
 */
import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import type { ChallengePhaseBoundaryStatus } from "../../../api/types/challengeCup";

/** Stage one lifecycle: generating until the stage-one acceptance gate passes. */
export type ChallengeQuestionStageOneStatus = "hypothesis_generating" | "hypothesis_settled";

export type ChallengeQuestionStageProjection = {
  /** 假说生成：run 活跃/候选评审中 → generating；stage-one 收门通过 → settled。 */
  stageOne: ChallengeQuestionStageOneStatus;
  /** 研究计划与实验是否已进入可执行阶段。 */
  stageTwoActive: boolean | null;
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
  boundary?: Pick<ChallengePhaseBoundaryStatus, "phase2Activated"> | null,
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
    stageTwoActive: boundary?.phase2Activated ?? null,
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
export function stageTwoStatusCopy(active: boolean | null, lang: "zh" | "en"): string {
  if (active === null) return lang === "zh" ? "状态待确认" : "Status unavailable";
  if (active) return lang === "zh" ? "已解锁" : "Unlocked";
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

/** One-line progression semantics for the plan and experiment zone. */
export function stageTwoProgressHint(active: boolean | null, lang: "zh" | "en"): string {
  if (active === null) {
    return lang === "zh"
      ? "尚未取得阶段状态；假说审批和已有计划不代表第二阶段已激活。"
      : "Phase status is unavailable; hypothesis approval and existing plans do not prove activation.";
  }
  if (active) {
    return lang === "zh"
      ? "审批与知识发布已完成，第二阶段已解锁；实际执行进度以运行记录为准。"
      : "Approval and knowledge publication are complete; phase two is unlocked. See the run for execution progress.";
  }
  return lang === "zh"
    ? "第二阶段尚未激活，需完成阶段审批与知识发布；已有计划不代表实验已开始。"
    : "Phase two requires phase approval and knowledge publication; existing plans do not mean experiments have started.";
}
