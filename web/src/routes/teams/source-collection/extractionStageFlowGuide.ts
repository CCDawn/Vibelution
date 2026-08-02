/**
 * Extraction-stage progression guide: one recommended next action + micro-steps.
 * Keeps operators moving instead of choosing among equal-weight buttons.
 */

export type ExtractionFlowStepId = "repair" | "review" | "advance";

export type ExtractionFlowStepState = "done" | "current" | "upcoming";

export type ExtractionRecommendedKind =
  | "supplement"
  | "extract"
  | "import"
  | "quality_review"
  | "advance_relations"
  | "chat"
  | "wait";

export type ExtractionFlowStep = {
  id: ExtractionFlowStepId;
  label: string;
  state: ExtractionFlowStepState;
};

export type ExtractionStageFlowGuide = {
  steps: ExtractionFlowStep[];
  currentStepId: ExtractionFlowStepId;
  recommendedKind: ExtractionRecommendedKind;
  recommendedLabel: string;
  recommendedTitle: string;
  nowHint: string;
  afterHint: string;
  /** Secondary quality-review only when it is not the recommended primary. */
  showQualityReviewSecondary: boolean;
  showImportSecondary: boolean;
};

export type BuildExtractionStageFlowGuideInput = {
  lang: "zh" | "en";
  needsAgentMaterial: boolean;
  pendingScreeningCount: number;
  approvedCount: number;
  displayedCandidateCount: number;
  pendingImportCount: number;
  canProceedAfterExclusions: boolean;
  qualityReviewPending: boolean;
  qualityReviewButtonText: string;
  /** When recovery/exclusion owns the primary copy. */
  recoveryPrimaryLabel?: string | null;
  recoveryPrimaryKind?: "chat" | "continue_task" | null;
  recoveryActive?: boolean;
};

function stepState(
  stepId: ExtractionFlowStepId,
  current: ExtractionFlowStepId,
): ExtractionFlowStepState {
  const order: ExtractionFlowStepId[] = ["repair", "review", "advance"];
  const stepIndex = order.indexOf(stepId);
  const currentIndex = order.indexOf(current);
  if (stepIndex < currentIndex) {
    return "done";
  }
  if (stepIndex === currentIndex) {
    return "current";
  }
  return "upcoming";
}

export function buildExtractionStageFlowGuide(
  input: BuildExtractionStageFlowGuideInput,
): ExtractionStageFlowGuide {
  const {
    lang,
    needsAgentMaterial,
    pendingScreeningCount,
    approvedCount,
    displayedCandidateCount,
    pendingImportCount,
    canProceedAfterExclusions,
    qualityReviewPending,
    qualityReviewButtonText,
    recoveryPrimaryLabel,
    recoveryPrimaryKind,
    recoveryActive,
  } = input;

  const zh = lang === "zh";
  // Exclusion-only recovery can still advance; do not treat it as material repair.
  const needsRepair = Boolean((needsAgentMaterial || recoveryActive) && !canProceedAfterExclusions);
  const needsReview = !needsRepair && pendingScreeningCount > 0;
  const canAdvance = !needsRepair
    && pendingScreeningCount <= 0
    && (approvedCount > 0 || canProceedAfterExclusions);
  const needsExtract = !needsRepair
    && !needsReview
    && !canAdvance
    && displayedCandidateCount <= 0
    && pendingImportCount > 0;

  let currentStepId: ExtractionFlowStepId = "repair";
  if (canAdvance) {
    currentStepId = "advance";
  } else if (needsReview || (!needsRepair && displayedCandidateCount > 0)) {
    currentStepId = "review";
  } else if (needsExtract) {
    currentStepId = "repair";
  } else if (!needsRepair && pendingScreeningCount <= 0) {
    currentStepId = approvedCount > 0 ? "advance" : "review";
  }

  const steps: ExtractionFlowStep[] = [
    {
      id: "repair",
      label: zh ? "① 补材料/提炼" : "1. Repair / extract",
      state: stepState("repair", currentStepId),
    },
    {
      id: "review",
      label: zh ? "② 质量审查" : "2. Quality review",
      state: stepState("review", currentStepId),
    },
    {
      id: "advance",
      label: zh ? "③ 进关系整理" : "3. Relations",
      state: stepState("advance", currentStepId),
    },
  ];

  let recommendedKind: ExtractionRecommendedKind = "wait";
  let recommendedLabel = zh ? "等待数据" : "Waiting";
  let recommendedTitle = zh ? "当前暂无推荐操作" : "No recommended action yet";
  let nowHint = zh ? "等待本轮数据同步" : "Waiting for run data";
  let afterHint = zh ? "数据就绪后继续" : "Continue when data is ready";
  let showQualityReviewSecondary = false;
  let showImportSecondary = pendingImportCount > 0 && !needsExtract;

  if (qualityReviewPending) {
    recommendedKind = "wait";
    recommendedLabel = zh ? "质量审查中…" : "Reviewing quality…";
    recommendedTitle = zh ? "资料提炼 Agent 正在按现有材料打分" : "Source Extractor is scoring current materials";
    nowHint = zh ? "质量审查进行中，请稍候" : "Quality review is running";
    afterHint = zh ? "看通过/待补/排除摘要，再决定补材料或进入关系整理" : "Read approved / needs-revision / rejected summary, then repair or advance";
  } else if (needsRepair) {
    recommendedKind = recoveryPrimaryKind === "chat" ? "chat" : "supplement";
    recommendedLabel = recoveryPrimaryLabel
      || (zh ? "要求 Agent 补充材料" : "Request Agent material supplement");
    const verificationOnly = recoveryPrimaryKind === "chat";
    recommendedTitle = verificationOnly
      ? (zh
        ? "在私聊中补入新的可公开核验材料；不会自动重复访问已拒绝的来源链接。无法补齐时，可明确排除本轮不可核验来源。"
        : "Add a new publicly verifiable material in chat. Rejected source URLs are not automatically retried; explicitly exclude this run's unverifiable sources if repair is impossible.")
      : (zh
        ? "现在只做这一步：让 Agent 补全文/DOI/证据锚点。补完后再质量审查。"
        : "Do this now: have the Agent add full text / DOI / anchors. Review only after repair.");
    nowHint = verificationOnly
      ? (zh ? "补入新材料，或明确排除无法核验的来源" : "Add new material or explicitly exclude unverifiable sources")
      : (zh ? "只点下面大按钮，让 Agent 补材料" : "Use only the big button below to repair materials");
    afterHint = verificationOnly
      ? (zh ? "补齐后重新质量审查；排除后可进入关系整理" : "Re-run review after repair; advance to relation mapping after exclusion")
      : (zh ? "系统会把推荐切到「质量审查」" : "The recommended action switches to quality review");
    showQualityReviewSecondary = displayedCandidateCount > 0;
    showImportSecondary = pendingImportCount > 0;
  } else if (needsReview) {
    recommendedKind = "quality_review";
    recommendedLabel = qualityReviewButtonText || (zh ? "Agent 质量审查" : "Agent quality review");
    recommendedTitle = zh
      ? "材料已就绪：对未审查候选做质量打分（通过 / 待补 / 排除）"
      : "Materials ready: score pending candidates (approved / needs revision / rejected)";
    nowHint = zh
      ? `${pendingScreeningCount} 条待质量审查`
      : `${pendingScreeningCount} pending quality review`;
    afterHint = zh
      ? "通过后进入关系整理；若出现待补，回到①补材料"
      : "Advance when approved; if needs-revision appears, return to repair";
    showQualityReviewSecondary = false;
    showImportSecondary = pendingImportCount > 0;
  } else if (canProceedAfterExclusions) {
    recommendedKind = "advance_relations";
    recommendedLabel = zh ? "进入关系整理" : "Go to relations";
    recommendedTitle = zh
      ? "可用候选已保留。排除项可稍后在私聊确认；现在继续推进到关系整理。"
      : "Usable candidates are kept. Confirm exclusions later in chat; advance to relations now.";
    nowHint = zh ? "提炼阶段已可推进" : "Extraction can advance";
    afterHint = zh ? "在关系整理阶段生成关系图" : "Build the relation map next";
    showImportSecondary = false;
  } else if (canAdvance) {
    recommendedKind = "advance_relations";
    recommendedLabel = zh ? "进入关系整理" : "Go to relations";
    recommendedTitle = zh
      ? "质量审查已闭环，进入下一阶段整理资料关系"
      : "Quality review is closed; map source relations next";
    nowHint = zh ? `已通过 ${approvedCount} 条，可离开提炼阶段` : `${approvedCount} approved; leave extraction`;
    afterHint = zh ? "在关系整理阶段生成关系图" : "Build the relation map in the next stage";
  } else if (needsExtract || (displayedCandidateCount <= 0 && pendingImportCount > 0)) {
    recommendedKind = "extract";
    recommendedLabel = zh ? "Agent 提炼资料" : "Agent extract sources";
    recommendedTitle = zh
      ? "先把原始资料提炼为候选，再做质量审查"
      : "Extract raw sources into candidates, then quality-review";
    nowHint = zh ? "本轮还没有候选资料" : "No candidates in this run yet";
    afterHint = zh ? "提炼后进行质量审查" : "Run quality review after extraction";
    showImportSecondary = true;
  } else if (displayedCandidateCount > 0) {
    // Assessed but not advancing (e.g. all needs_revision after review without material flags).
    recommendedKind = needsAgentMaterial ? "supplement" : "quality_review";
    recommendedLabel = needsAgentMaterial
      ? (recoveryPrimaryLabel || (zh ? "要求 Agent 补充材料" : "Request Agent material supplement"))
      : (qualityReviewButtonText || (zh ? "重新质量审查" : "Re-run quality review"));
    recommendedTitle = zh
      ? "若刚补过材料可重新审查；若仍待补请先补材料"
      : "Re-score after material repairs; if still blocked, repair first";
    nowHint = zh ? "审查结果未全部通过" : "Not all candidates are approved";
    afterHint = zh ? "待补 → 补材料；通过 → 关系整理" : "Needs revision → repair; approved → relations";
    showQualityReviewSecondary = needsAgentMaterial && displayedCandidateCount > 0;
    showImportSecondary = pendingImportCount > 0;
  }

  // When quality review is the recommended primary, never also show it as secondary.
  if (recommendedKind === "quality_review") {
    showQualityReviewSecondary = false;
  }

  return {
    steps,
    currentStepId,
    recommendedKind,
    recommendedLabel,
    recommendedTitle,
    nowHint,
    afterHint,
    showQualityReviewSecondary,
    showImportSecondary,
  };
}
