/**
 * Overview primary CTA + stage handoff pure model.
 * Single next action for the active research project.
 */
import type { ResearchStageWorkspaceView } from "./researchWorkspaceModel";
import type { ResearchStagePhaseStatus } from "./source-collection/stageProjection";

export type ResearchPrimaryActionKind =
  | "start_knowledge_collection"
  | "continue_knowledge_collection"
  | "start_experiment"
  | "continue_experiment"
  | "start_iteration"
  | "continue_iteration"
  | "blocked";

export type ResearchPrimaryAction = {
  kind: ResearchPrimaryActionKind;
  labelZh: string;
  labelEn: string;
  detailZh: string;
  detailEn: string;
  /** Navigate to workspace stage view */
  navigateView: ResearchStageWorkspaceView;
  /** Optionally launch stage round after navigate */
  launchStageType?: "knowledge_collection" | "experiment" | "iteration";
  launchMode?: "continue_or_start" | "new_round";
  blocked: boolean;
  blockReasonZh?: string;
  blockReasonEn?: string;
};

export type ResearchStageHandoff = {
  fromStage: ResearchStageWorkspaceView;
  toStage: ResearchStageWorkspaceView;
  titleZh: string;
  titleEn: string;
  bodyZh: string;
  bodyEn: string;
  action: ResearchPrimaryAction;
};

export type ResearchPrimaryActionInput = {
  hasActiveProject: boolean;
  sourceRunCount: number;
  /** Project-scoped source candidates (manifests); progress even without live runs. */
  sourceCandidateCount?: number;
  phases: ResearchStagePhaseStatus[];
  experimentDesignFrozen?: boolean;
};

function phaseFor(
  phases: ResearchStagePhaseStatus[],
  stageType: string,
): ResearchStagePhaseStatus | undefined {
  return phases.find((item) => String(item.stageType || "") === stageType);
}

function phaseReady(phase: ResearchStagePhaseStatus | undefined): boolean {
  if (!phase) {
    return false;
  }
  if (phase.readiness && typeof phase.readiness.ready === "boolean") {
    return Boolean(phase.readiness.ready);
  }
  return Boolean(phase.canStart || phase.canContinue);
}

function phaseHasRound(phase: ResearchStagePhaseStatus | undefined): boolean {
  return Boolean(phase?.latestRound || (phase?.roundCount ?? 0) > 0 || phase?.activeRoundId);
}

export function resolveResearchPrimaryAction(input: ResearchPrimaryActionInput): ResearchPrimaryAction {
  if (!input.hasActiveProject) {
    return {
      kind: "blocked",
      labelZh: "先选择科研项目",
      labelEn: "Select a research project",
      detailZh: "总览需要激活的科研项目后才能给出下一步。",
      detailEn: "Activate a research project before the overview can recommend a next step.",
      navigateView: "knowledge_collection",
      blocked: true,
      blockReasonZh: "无激活科研项目",
      blockReasonEn: "No active research project",
    };
  }

  const knowledge = phaseFor(input.phases, "knowledge_collection");
  const experiment = phaseFor(input.phases, "experiment");
  const iteration = phaseFor(input.phases, "iteration");

  const sourceCandidateCount = Math.max(0, Number(input.sourceCandidateCount || 0));
  const hasKnowledge =
    phaseHasRound(knowledge)
    || input.sourceRunCount > 0
    || sourceCandidateCount > 0;
  const hasExperiment = phaseHasRound(experiment);
  const hasIteration = phaseHasRound(iteration);
  const experimentReady = phaseReady(experiment);
  const iterationReady = phaseReady(iteration);

  // Prefer advancing when upstream is ready and downstream not started.
  if (hasKnowledge && experimentReady && !hasExperiment) {
    return {
      kind: "start_experiment",
      labelZh: "进入实验设计",
      labelEn: "Start experiment design",
      detailZh: "资料阶段已有轮次，可以启动实验规划并起草可证伪假设。",
      detailEn: "Knowledge collection has started; open experiment planning next.",
      navigateView: "experiment",
      launchStageType: "experiment",
      launchMode: "continue_or_start",
      blocked: false,
    };
  }

  if (hasExperiment && iterationReady && !hasIteration) {
    return {
      kind: "start_iteration",
      labelZh: "进入执行与迭代",
      labelEn: "Start execution & iteration",
      detailZh: "实验阶段已就绪，可以进入执行、评估与迭代决策。",
      detailEn: "Experiment stage is ready; open execution and iteration.",
      navigateView: "iteration",
      launchStageType: "iteration",
      launchMode: "continue_or_start",
      blocked: false,
    };
  }

  if (hasIteration || (hasExperiment && iterationReady)) {
    return {
      kind: "continue_iteration",
      labelZh: "继续执行与迭代",
      labelEn: "Continue execution & iteration",
      detailZh: "在执行迭代台查看批次、评估与晋升门禁。",
      detailEn: "Review runs, evaluation, and promotion gates in the iteration workspace.",
      navigateView: "iteration",
      blocked: false,
    };
  }

  if (hasExperiment) {
    return {
      kind: "continue_experiment",
      labelZh: "继续实验设计",
      labelEn: "Continue experiment design",
      detailZh: input.experimentDesignFrozen
        ? "设计已冻结，可补证据或进入执行迭代（若门禁允许）。"
        : "完善假设、变量与协议，并在准备好后冻结设计。",
      detailEn: input.experimentDesignFrozen
        ? "Design is frozen; add evidence or move to iteration when ready."
        : "Refine hypothesis, variables, and protocol; freeze when ready.",
      navigateView: "experiment",
      blocked: false,
    };
  }

  if (hasKnowledge) {
    return {
      kind: "continue_knowledge_collection",
      labelZh: "继续知识搜集",
      labelEn: "Continue knowledge collection",
      detailZh: "完善资料批次、提炼与入库；完成后可进入实验设计。",
      detailEn: "Finish source batches, extraction, and ingestion before experiment design.",
      navigateView: "knowledge_collection",
      blocked: false,
    };
  }

  return {
    kind: "start_knowledge_collection",
    labelZh: "开始知识搜集",
    labelEn: "Start knowledge collection",
    detailZh: "从资料搜索批次开始，建立本项目的证据基础。",
    detailEn: "Start with a source-collection batch to build project evidence.",
    navigateView: "knowledge_collection",
    launchStageType: "knowledge_collection",
    launchMode: "continue_or_start",
    blocked: false,
  };
}

export function resolveResearchStageHandoff(
  input: ResearchPrimaryActionInput,
): ResearchStageHandoff | null {
  const action = resolveResearchPrimaryAction(input);
  if (action.kind === "start_experiment") {
    return {
      fromStage: "knowledge_collection",
      toStage: "experiment",
      titleZh: "资料阶段可交接",
      titleEn: "Knowledge collection handoff",
      bodyZh: "已有知识搜集进度。建议进入实验设计，将证据收敛为可证伪假设与冻结协议。",
      bodyEn: "Knowledge collection has progress. Move to experiment design to form a falsifiable plan.",
      action,
    };
  }
  if (action.kind === "start_iteration") {
    return {
      fromStage: "experiment",
      toStage: "iteration",
      titleZh: "实验阶段可交接",
      titleEn: "Experiment handoff",
      bodyZh: "实验规划门禁已满足。建议进入执行与迭代，记录结果并做版本决策。",
      bodyEn: "Experiment readiness is met. Move to execution and iteration for runs and promotion.",
      action,
    };
  }
  return null;
}

export function researchPrimaryActionLabel(action: ResearchPrimaryAction, lang: "zh" | "en"): string {
  return lang === "zh" ? action.labelZh : action.labelEn;
}

export function researchPrimaryActionDetail(action: ResearchPrimaryAction, lang: "zh" | "en"): string {
  return lang === "zh" ? action.detailZh : action.detailEn;
}
