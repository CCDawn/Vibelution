/**
 * Overview CTA model: continue (primary) vs advance (secondary).
 * Primary always resumes the active stage; advance is explicit cross-stage.
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
  /**
   * Optional URL/workspace stage. When set, continue targets this stage so
   * refresh and in-stage navigation stay predictable.
   */
  currentView?: ResearchStageWorkspaceView | null;
};

export type ResearchStageUnlock = {
  knowledge_collection: boolean;
  experiment: boolean;
  iteration: boolean;
};

export type ResearchOverviewActions = {
  activeStage: ResearchStageWorkspaceView;
  continueAction: ResearchPrimaryAction;
  advanceAction: ResearchPrimaryAction | null;
  handoff: ResearchStageHandoff | null;
  unlock: ResearchStageUnlock;
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

function projectProgressFlags(input: ResearchPrimaryActionInput) {
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
  return {
    knowledge,
    experiment,
    iteration,
    hasKnowledge,
    hasExperiment,
    hasIteration,
    experimentReady,
    iterationReady,
  };
}

/** Infer which stage the user should "continue" in (not the global "smart advance"). */
export function resolveResearchActiveStage(
  input: ResearchPrimaryActionInput,
): ResearchStageWorkspaceView {
  const view = input.currentView;
  if (view === "knowledge_collection" || view === "experiment" || view === "iteration") {
    return view;
  }
  const { hasKnowledge, hasExperiment, hasIteration } = projectProgressFlags(input);
  if (hasIteration) {
    return "iteration";
  }
  if (hasExperiment) {
    return "experiment";
  }
  if (hasKnowledge) {
    return "knowledge_collection";
  }
  return "knowledge_collection";
}

export function resolveResearchStageUnlock(input: ResearchPrimaryActionInput): ResearchStageUnlock {
  if (!input.hasActiveProject) {
    return {
      knowledge_collection: false,
      experiment: false,
      iteration: false,
    };
  }
  const { hasKnowledge, hasExperiment, hasIteration, experimentReady, iterationReady } =
    projectProgressFlags(input);
  return {
    knowledge_collection: true,
    experiment: hasKnowledge || hasExperiment || experimentReady,
    iteration: hasExperiment || hasIteration || iterationReady,
  };
}

function blockedNoProject(): ResearchPrimaryAction {
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

function continueKnowledge(hasKnowledge: boolean): ResearchPrimaryAction {
  if (!hasKnowledge) {
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
  return {
    kind: "continue_knowledge_collection",
    labelZh: "继续知识搜集",
    labelEn: "Continue knowledge collection",
    detailZh: "完善资料批次、提炼与入库；需要换阶段时请用「进入下一阶段」。",
    detailEn: "Finish source batches, extraction, and ingestion. Use advance to change stage.",
    navigateView: "knowledge_collection",
    blocked: false,
  };
}

function continueExperiment(experimentDesignFrozen?: boolean): ResearchPrimaryAction {
  return {
    kind: "continue_experiment",
    labelZh: "继续实验设计",
    labelEn: "Continue experiment design",
    detailZh: experimentDesignFrozen
      ? "设计已冻结，可补证据或从次按钮进入执行迭代。"
      : "完善假设、变量与协议；准备好后可冻结设计或进入执行迭代。",
    detailEn: experimentDesignFrozen
      ? "Design is frozen; add evidence or advance to iteration when ready."
      : "Refine hypothesis, variables, and protocol; freeze or advance when ready.",
    navigateView: "experiment",
    blocked: false,
  };
}

function continueIteration(): ResearchPrimaryAction {
  return {
    kind: "continue_iteration",
    labelZh: "继续执行迭代",
    labelEn: "Continue execution & iteration",
    detailZh: "在执行迭代台查看批次、评估与晋升门禁。",
    detailEn: "Review runs, evaluation, and promotion gates in the iteration workspace.",
    navigateView: "iteration",
    blocked: false,
  };
}

function advanceToExperiment(): ResearchPrimaryAction {
  return {
    kind: "start_experiment",
    labelZh: "进入实验设计（离开知识搜集）",
    labelEn: "Enter experiment (leave collection)",
    detailZh: "将离开知识搜集工作台，进入实验规划；可随时从顶栏阶段条返回。",
    detailEn: "Leave knowledge collection and open experiment planning. Use the stage rail to return.",
    navigateView: "experiment",
    launchStageType: "experiment",
    launchMode: "continue_or_start",
    blocked: false,
  };
}

function advanceToIteration(): ResearchPrimaryAction {
  return {
    kind: "start_iteration",
    labelZh: "进入执行迭代（离开实验设计）",
    labelEn: "Enter iteration (leave experiment)",
    detailZh: "将离开实验设计工作台，进入执行与迭代；可随时从顶栏阶段条返回。",
    detailEn: "Leave experiment design and open execution & iteration. Use the stage rail to return.",
    navigateView: "iteration",
    launchStageType: "iteration",
    launchMode: "continue_or_start",
    blocked: false,
  };
}

/**
 * Primary overview CTA: always resume the active stage (easy, predictable).
 */
export function resolveResearchPrimaryAction(input: ResearchPrimaryActionInput): ResearchPrimaryAction {
  if (!input.hasActiveProject) {
    return blockedNoProject();
  }
  const { hasKnowledge, hasExperiment, hasIteration } = projectProgressFlags(input);
  const activeStage = resolveResearchActiveStage(input);

  if (activeStage === "iteration" || hasIteration) {
    if (activeStage === "iteration") {
      return continueIteration();
    }
  }
  if (activeStage === "experiment") {
    return hasExperiment
      ? continueExperiment(input.experimentDesignFrozen)
      : continueExperiment(input.experimentDesignFrozen);
  }
  if (activeStage === "knowledge_collection") {
    return continueKnowledge(hasKnowledge);
  }

  // Fallback by progress when view is unknown
  if (hasIteration) {
    return continueIteration();
  }
  if (hasExperiment) {
    return continueExperiment(input.experimentDesignFrozen);
  }
  return continueKnowledge(hasKnowledge);
}

/**
 * Secondary overview CTA: explicit cross-stage advance (never hijacks primary).
 */
export function resolveResearchAdvanceAction(
  input: ResearchPrimaryActionInput,
): ResearchPrimaryAction | null {
  if (!input.hasActiveProject) {
    return null;
  }
  const {
    hasKnowledge,
    hasExperiment,
    hasIteration,
    experimentReady,
    iterationReady,
  } = projectProgressFlags(input);
  const activeStage = resolveResearchActiveStage(input);

  if (activeStage === "knowledge_collection") {
    if (hasKnowledge && experimentReady) {
      return advanceToExperiment();
    }
    return null;
  }

  if (activeStage === "experiment") {
    if ((hasExperiment || experimentReady) && iterationReady && !hasIteration) {
      return advanceToIteration();
    }
    if (hasExperiment && iterationReady) {
      return advanceToIteration();
    }
    return null;
  }

  // iteration: no further stage
  return null;
}

export function resolveResearchStageHandoff(
  input: ResearchPrimaryActionInput,
): ResearchStageHandoff | null {
  const advance = resolveResearchAdvanceAction(input);
  if (!advance) {
    return null;
  }
  if (advance.kind === "start_experiment") {
    return {
      fromStage: "knowledge_collection",
      toStage: "experiment",
      titleZh: "可进入下一阶段",
      titleEn: "Ready for next stage",
      bodyZh: "资料阶段已有进度。需要时点次按钮进入实验设计（会离开知识搜集）。",
      bodyEn: "Knowledge collection has progress. Use the secondary button to enter experiment design.",
      action: advance,
    };
  }
  if (advance.kind === "start_iteration") {
    return {
      fromStage: "experiment",
      toStage: "iteration",
      titleZh: "可进入下一阶段",
      titleEn: "Ready for next stage",
      bodyZh: "实验门禁已满足。需要时点次按钮进入执行迭代（会离开实验设计）。",
      bodyEn: "Experiment readiness is met. Use the secondary button to enter execution & iteration.",
      action: advance,
    };
  }
  return null;
}

export function resolveResearchOverviewActions(
  input: ResearchPrimaryActionInput,
): ResearchOverviewActions {
  return {
    activeStage: resolveResearchActiveStage(input),
    continueAction: resolveResearchPrimaryAction(input),
    advanceAction: resolveResearchAdvanceAction(input),
    handoff: resolveResearchStageHandoff(input),
    unlock: resolveResearchStageUnlock(input),
  };
}

export function researchPrimaryActionLabel(action: ResearchPrimaryAction, lang: "zh" | "en"): string {
  return lang === "zh" ? action.labelZh : action.labelEn;
}

export function researchPrimaryActionDetail(action: ResearchPrimaryAction, lang: "zh" | "en"): string {
  return lang === "zh" ? action.detailZh : action.detailEn;
}

/** Toast / live-region copy after a successful stage advance. */
export function researchAdvanceSuccessMessage(
  action: ResearchPrimaryAction,
  lang: "zh" | "en",
): string {
  if (action.navigateView === "experiment") {
    return lang === "zh"
      ? "已进入实验设计 · 顶栏阶段条可返回知识搜集"
      : "Entered experiment design · use the stage rail to return";
  }
  if (action.navigateView === "iteration") {
    return lang === "zh"
      ? "已进入执行迭代 · 顶栏阶段条可返回实验设计"
      : "Entered execution & iteration · use the stage rail to return";
  }
  return lang === "zh" ? "已切换阶段" : "Stage switched";
}
