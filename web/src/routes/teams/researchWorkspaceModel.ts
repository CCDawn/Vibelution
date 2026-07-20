import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";

export type ResearchStageWorkspaceView = "knowledge_collection" | "experiment" | "iteration";
export type ResearchLegacyWorkspaceView =
  | "source_collection"
  | "coordination"
  | "ingestion"
  | "graph"
  | "candidates"
  | "discussion"
  | "canvas";
export type ResearchWorkspaceView = "overview" | ResearchStageWorkspaceView | ResearchLegacyWorkspaceView;

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
  if (!value) {
    return null;
  }
  if (value === "source_collection") {
    return "knowledge_collection";
  }
  return value in RESEARCH_WORKSPACE_LABELS ? (value as ResearchWorkspaceView) : null;
}

export function researchWorkspaceStageRoute(
  teamId = RESEARCH_TEAM_ID,
  view: ResearchStageWorkspaceView = "knowledge_collection",
) {
  return `/teams?team=${encodeURIComponent(teamId)}&researchView=${encodeURIComponent(view)}`;
}

export function researchSourceCollectionRoute(teamId = RESEARCH_TEAM_ID) {
  return researchWorkspaceStageRoute(teamId, "knowledge_collection");
}

export function teamWorkspaceRoute(teamId = RESEARCH_TEAM_ID) {
  return `/teams?team=${encodeURIComponent(teamId)}`;
}

export function researchCanvasRoute(teamId = RESEARCH_TEAM_ID) {
  return `/teams?team=${encodeURIComponent(teamId)}&researchView=canvas`;
}
