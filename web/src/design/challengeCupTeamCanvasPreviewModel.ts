/**
 * Mock data for the Challenge Cup team-canvas IA preview.
 * Isolated design acceptance only — not wired to TeamsRoute.
 */

export type LayoutMode = "current" | "proposed";
export type SceneId = "idle" | "selected" | "blocked" | "narrow";
export type TeamId = "challenge" | "search" | "knowledge";
export type StageTone = "done" | "active" | "idle" | "blocked";
export type RoleTone = "lead" | "research" | "advisor" | "open";
export type StatusTone = "success" | "warning" | "danger" | "neutral";

export type PreviewStage = {
  id: string;
  title: string;
  status: string;
  tone: StageTone;
};

export type PreviewNode = {
  id: string;
  label: string;
  role: string;
  roleTone: RoleTone;
  agent: string;
  purpose: string;
  status: string;
  statusTone: StatusTone;
  x: number;
  y: number;
};

export type PreviewEdge = {
  id: string;
  from: string;
  to: string;
};

export type PreviewTeam = {
  id: TeamId;
  name: string;
  purpose: string;
  kind: string;
  nextTitle: string;
  nextBody: string;
  cta: string;
  metrics: Array<{ label: string; value: string }>;
  stages: PreviewStage[];
  nodes: PreviewNode[];
  edges: PreviewEdge[];
};

export const SCENE_ORDER: SceneId[] = ["idle", "selected", "blocked", "narrow"];

export const SCENE_LABEL: Record<SceneId, string> = {
  idle: "未选节点",
  selected: "选中资料寻找",
  blocked: "节点阻塞",
  narrow: "窄屏",
};

export const TEAMS: PreviewTeam[] = [
  {
    id: "challenge",
    name: "挑战杯ai科研团队",
    purpose: "组织关系图 · 科研主页",
    kind: "科研工作流",
    nextTitle: "继续知识搜集",
    nextBody: "资料寻找还差 2 篇核心文献。点节点看执行者，不要在左栏切团队。",
    cta: "继续知识搜集",
    metrics: [
      { label: "节点", value: "4" },
      { label: "已绑定", value: "3" },
      { label: "阻塞", value: "0" },
    ],
    stages: [
      { id: "collect", title: "资料寻找", status: "进行中", tone: "active" },
      { id: "experiment", title: "实验设计", status: "未开始", tone: "idle" },
      { id: "iterate", title: "执行迭代", status: "未开始", tone: "idle" },
    ],
    nodes: [
      {
        id: "node-lead",
        label: "队长",
        role: "lead",
        roleTone: "lead",
        agent: "白书遥",
        purpose: "拆题、派工、收口",
        status: "在线",
        statusTone: "success",
        x: 0.02,
        y: 0.1,
      },
      {
        id: "node-finder",
        label: "资料寻找",
        role: "source_finder",
        roleTone: "research",
        agent: "白望舒",
        purpose: "按题目检索并入库候选文献",
        status: "等待任务",
        statusTone: "warning",
        x: 0.34,
        y: 0.1,
      },
      {
        id: "node-extractor",
        label: "资料提炼",
        role: "source_extractor",
        roleTone: "advisor",
        agent: "顾言初",
        purpose: "抽取证据与可检验命题",
        status: "可用",
        statusTone: "success",
        x: 0.34,
        y: 0.55,
      },
      {
        id: "node-graph",
        label: "关系整理",
        role: "relation_steward",
        roleTone: "open",
        agent: "未绑定",
        purpose: "把证据连成可答辩结构",
        status: "空缺",
        statusTone: "danger",
        x: 0.66,
        y: 0.32,
      },
    ],
    edges: [
      { id: "e-lead-finder", from: "node-lead", to: "node-finder" },
      { id: "e-lead-extractor", from: "node-lead", to: "node-extractor" },
      { id: "e-finder-extractor", from: "node-finder", to: "node-extractor" },
      { id: "e-extractor-graph", from: "node-extractor", to: "node-graph" },
    ],
  },
  {
    id: "search",
    name: "AI 搜索范围团队",
    purpose: "资料范围 · 只读组织",
    kind: "资料范围",
    nextTitle: "核对搜索范围",
    nextBody: "范围团队不承担科研阶段推进，只确认可检索边界。",
    cta: "打开范围配置",
    metrics: [
      { label: "节点", value: "2" },
      { label: "已绑定", value: "2" },
      { label: "阻塞", value: "0" },
    ],
    stages: [
      { id: "scope", title: "范围核对", status: "就绪", tone: "done" },
    ],
    nodes: [
      {
        id: "node-scope-lead",
        label: "范围主持",
        role: "lead",
        roleTone: "lead",
        agent: "白书遥",
        purpose: "圈定可检索语料",
        status: "在线",
        statusTone: "success",
        x: 0.12,
        y: 0.28,
      },
      {
        id: "node-scope-run",
        label: "检索执行",
        role: "search_runner",
        roleTone: "research",
        agent: "白望舒",
        purpose: "按范围跑检索",
        status: "待命",
        statusTone: "neutral",
        x: 0.55,
        y: 0.28,
      },
    ],
    edges: [{ id: "e-scope", from: "node-scope-lead", to: "node-scope-run" }],
  },
  {
    id: "knowledge",
    name: "知识扩充团队",
    purpose: "知识入库 · 组织画布",
    kind: "知识扩充",
    nextTitle: "继续入库",
    nextBody: "入库节点已绑定，扩写节点仍空缺。",
    cta: "继续入库",
    metrics: [
      { label: "节点", value: "2" },
      { label: "已绑定", value: "1" },
      { label: "阻塞", value: "1" },
    ],
    stages: [
      { id: "ingest", title: "知识入库", status: "进行中", tone: "active" },
      { id: "expand", title: "知识扩写", status: "空缺", tone: "blocked" },
    ],
    nodes: [
      {
        id: "node-ingest",
        label: "知识入库",
        role: "source_ingestor",
        roleTone: "research",
        agent: "资料入库",
        purpose: "把通过审核的资料写入知识库",
        status: "运行中",
        statusTone: "success",
        x: 0.12,
        y: 0.3,
      },
      {
        id: "node-expand",
        label: "知识扩写",
        role: "knowledge_expander",
        roleTone: "open",
        agent: "未绑定",
        purpose: "补全缺口命题",
        status: "空缺",
        statusTone: "danger",
        x: 0.55,
        y: 0.3,
      },
    ],
    edges: [{ id: "e-knowledge", from: "node-ingest", to: "node-expand" }],
  },
];

export const DEFAULT_SELECTED_NODE: Record<SceneId, string | null> = {
  idle: null,
  selected: "node-finder",
  blocked: "node-graph",
  narrow: "node-finder",
};

export const BLOCKED_ISSUE = {
  code: "NODE_UNBOUND",
  message: "关系整理未绑定执行 Agent，无法进入下一阶段。",
  nodeId: "node-graph",
};

export function teamById(id: TeamId): PreviewTeam {
  return TEAMS.find((team) => team.id === id) ?? TEAMS[0];
}

export function nodeById(team: PreviewTeam, nodeId: string | null): PreviewNode | null {
  if (!nodeId) {
    return null;
  }
  return team.nodes.find((node) => node.id === nodeId) ?? null;
}
