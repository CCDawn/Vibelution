export type ResearchStageWorkspaceView = "knowledge_collection" | "experiment" | "iteration";
export type ResearchLegacyWorkspaceView =
  | "source_collection"
  | "coordination"
  | "ingestion"
  | "graph"
  | "candidates"
  | "discussion"
  | "canvas";
export type ResearchWorkspaceView =
  | "overview"
  | "workflow"
  | ResearchStageWorkspaceView
  | ResearchLegacyWorkspaceView;

export const RESEARCH_WORKSPACE_NAV_ITEMS: Array<{
  view: ResearchStageWorkspaceView;
  zh: string;
  en: string;
  zhDetail: string;
  enDetail: string;
  zhModules: string;
  enModules: string;
}> = [
  {
    view: "knowledge_collection",
    zh: "知识搜集",
    en: "Knowledge collection",
    zhDetail: "搜索、提炼、审查与入库",
    enDetail: "Search, extraction, review, and ingestion",
    zhModules: "资料寻找 / 资料提炼 / 资料关系整理 / 资料入库",
    enModules: "Search / extraction / review / ingestion",
  },
  {
    view: "experiment",
    zh: "实验设计",
    en: "Experiment design",
    zhDetail: "可证伪假设、变量、控制组与冻结协议",
    enDetail: "Falsifiable hypothesis, variables, controls, and frozen protocol",
    zhModules: "研究问题 / 假设 / 控制变量 / 冻结设计",
    enModules: "Question / hypothesis / controls / frozen design",
  },
  {
    view: "iteration",
    zh: "执行迭代",
    en: "Execution & iteration",
    zhDetail: "执行、评估、消融、归因与版本晋升",
    enDetail: "Execution, evaluation, ablation, diagnosis, and promotion",
    zhModules: "执行批次 / 结果评估 / 消融归因 / 优化迭代",
    enModules: "Runs / evaluation / ablation / controlled iteration",
  },
];

export const RESEARCH_WORKSPACE_LABELS: Record<ResearchWorkspaceView, { zh: string; en: string }> = {
  overview: { zh: "科研总览", en: "Overview" },
  workflow: { zh: "科研流程", en: "Research workflow" },
  knowledge_collection: { zh: "知识搜集", en: "Knowledge collection" },
  experiment: { zh: "实验设计", en: "Experiment design" },
  iteration: { zh: "执行迭代", en: "Execution & iteration" },
  source_collection: { zh: "搜索资料", en: "Source search" },
  coordination: { zh: "团队协调", en: "Coordination" },
  ingestion: { zh: "入库审核", en: "Ingestion review" },
  graph: { zh: "入库关系", en: "Ingestion map" },
  candidates: { zh: "候选资料", en: "Candidates" },
  discussion: { zh: "团队沟通", en: "Team discussion" },
  canvas: { zh: "组织画布", en: "Canvas" },
};

export function researchWorkspaceAnchorId(view: ResearchWorkspaceView) {
  const ids: Record<ResearchWorkspaceView, string> = {
    overview: "research-workflow-overview",
    workflow: "research-process-workflow",
    knowledge_collection: "research-workflow-knowledge-collection",
    experiment: "research-workflow-experiment",
    iteration: "research-workflow-iteration",
    source_collection: "research-workflow-source-collection",
    coordination: "research-workflow-coordination",
    ingestion: "research-workflow-ingestion",
    graph: "research-workflow-graph",
    candidates: "research-workflow-candidates",
    discussion: "research-workflow-discussion",
    canvas: "research-organization-canvas",
  };
  return ids[view];
}

export function researchWorkspaceViewLabel(view: ResearchWorkspaceView, lang: "zh" | "en") {
  const item = RESEARCH_WORKSPACE_LABELS[view];
  return item ? item[lang] : view;
}

export function parseResearchWorkspaceView(value: string | null): ResearchWorkspaceView | null {
  return value === "workflow" || value === "overview" ? value : null;
}

/** Map stage workspace views onto fixed workflow node ids (ADR 0006). */
export function researchStageViewToNodeId(view: ResearchStageWorkspaceView): string {
  if (view === "experiment") return "hypothesis_design";
  if (view === "iteration") return "controlled_run";
  return "source_finding";
}

/** Canonical stage deep link: single workflow canvas + focused node. */
export function researchWorkspaceStageRoute(
  teamId: string,
  view: ResearchStageWorkspaceView,
) {
  if (!teamId.trim()) throw new Error("teamId 不能为空");
  const node = researchStageViewToNodeId(view);
  return `/teams?teamId=${encodeURIComponent(teamId)}&researchView=workflow&workflowId=challenge-cup-research&node=${encodeURIComponent(node)}`;
}

export function researchSourceCollectionRoute(teamId: string) {
  return researchWorkspaceStageRoute(teamId, "knowledge_collection");
}

export function challengeQuestionDetailRoute(
  teamId: string,
  questionId = "",
  runId = "",
) {
  if (!teamId.trim()) throw new Error("teamId 不能为空");
  // Canonical workflow-canvas params consumed by parseResearchProcessLocation;
  // the legacy challengeQuestion/challengeRun params were never parsed and
  // produced a dead link (question panel never opened).
  const params = new URLSearchParams({
    teamId,
    researchView: "workflow",
    workflowId: "challenge-cup-research",
    panel: "question",
    questionId,
  });
  if (runId) {
    params.set("runId", runId);
  }
  return `/teams?${params.toString()}`;
}

export type TeamWorkspaceRouteLocation = {
  runId?: string;
  nodeId?: string;
  panel?: string;
  questionId?: string;
};

function setOptionalRouteParam(params: URLSearchParams, key: string, value: string | undefined) {
  const normalized = value?.trim();
  if (normalized) {
    params.set(key, normalized);
  }
}

/**
 * Canonical research / team home for end users: single-canvas workflow workspace.
 * All "返回团队页面" / overview back links use this teamId-scoped URL.
 */
export function teamWorkspaceRoute(
  teamId: string,
  location: TeamWorkspaceRouteLocation = {},
) {
  if (!teamId.trim()) throw new Error("teamId 不能为空");
  const params = new URLSearchParams({
    teamId,
    researchView: "workflow",
    workflowId: "challenge-cup-research",
  });
  setOptionalRouteParam(params, "questionId", location.questionId);
  setOptionalRouteParam(params, "runId", location.runId);
  setOptionalRouteParam(params, "node", location.nodeId);
  setOptionalRouteParam(params, "panel", location.panel);
  return `/teams?${params.toString()}`;
}

/**
 * Convert legacy/overview challenge URLs into the one process-workspace URL.
 * Only process focus is carried forward; retired team aliases and workflow
 * values are deliberately removed so browser history converges on one shell.
 */
export function canonicalChallengeCupWorkspaceRoute(
  teamId: string,
  current: URLSearchParams,
) {
  return teamWorkspaceRoute(teamId, {
    questionId: current.get("questionId") || current.get("challengeQuestion") || undefined,
    runId: current.get("runId") || current.get("challengeRun") || undefined,
    nodeId: current.get("node") || current.get("nodeId") || undefined,
    panel: current.get("panel") || undefined,
  });
}

/**
 * Agents panel on the workflow shell.
 */
export function researchCanvasRoute(teamId: string) {
  return `${teamWorkspaceRoute(teamId)}&panel=agents`;
}
