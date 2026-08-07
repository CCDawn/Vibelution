/**
 * Process-flow single-page workspace preview for research teams.
 * Open: /research-process-flow-preview.html
 * Design acceptance only — not wired into production TeamsRoute.
 *
 * Contract (P0 single-page process workspace):
 * 1. Primary surface is the process flow graph (not multi-page stage routes)
 * 2. Selecting a flow node / sub-node switches the in-page ops panel only
 * 3. Former "pages" (知识搜集/实验/迭代/子模块) are node-bound panels on one page
 * 4. Current runtime stage stays highlighted on the graph regardless of selection
 * 5. Deep links may still set selectedNode; they must not leave the workspace shell
 */
import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import "./research-process-flow-preview.css";

type ScenarioId = "collecting" | "handoff" | "experiment" | "iteration" | "blocked";
type NodeState = "idle" | "ready" | "active" | "done" | "blocked";
type EdgeState = "idle" | "active" | "done" | "blocked";
type MacroId = "knowledge_collection" | "experiment" | "iteration";
type PanelKey =
  | MacroId
  | "finding"
  | "extract"
  | "relation"
  | "ingest"
  | "hypothesis"
  | "protocol"
  | "smoke"
  | "run"
  | "eval"
  | "promote"
  | "bindings";

type AgentBinding = {
  name: string;
  role: string;
  initial: string;
  online: boolean;
};

type SubStage = {
  id: PanelKey;
  label: string;
  state: NodeState;
  agent?: string;
  summary: string;
};

type StageNode = {
  id: MacroId;
  index: string;
  title: string;
  detail: string;
  state: NodeState;
  badge: string;
  metrics: string[];
  agents: AgentBinding[];
  substages: SubStage[];
};

type FlowEdge = {
  id: string;
  from: MacroId;
  to: MacroId;
  label: string;
  state: EdgeState;
};

type OpsAction = {
  id: string;
  label: string;
  primary?: boolean;
  danger?: boolean;
};

type OpsBlock = {
  title: string;
  body: string;
  rows: Array<{ label: string; value: string }>;
  actions: OpsAction[];
  feed: string[];
};

type Scenario = {
  id: ScenarioId;
  label: string;
  project: string;
  currentStageId: MacroId;
  currentSubId?: PanelKey;
  currentLabel: string;
  progress: string;
  runStatus: string;
  nextAction: string;
  stages: StageNode[];
  edges: FlowEdge[];
};

function agents(rows: Array<[string, string, string, boolean?]>): AgentBinding[] {
  return rows.map(([name, role, initial, online = true]) => ({
    name,
    role,
    initial,
    online,
  }));
}

function baseStages(partial: Partial<Record<MacroId, Partial<StageNode>>>): StageNode[] {
  const defaults: StageNode[] = [
    {
      id: "knowledge_collection",
      index: "01",
      title: "知识搜集",
      detail: "资料 · 证据 · 入库",
      state: "idle",
      badge: "未开始",
      metrics: ["资料 0", "证据 0"],
      agents: agents([
        ["白书遥", "科研协调", "白"],
        ["白望舒", "资料寻找", "白"],
        ["顾言初", "资料提炼", "顾", false],
        ["林知序", "关系整理", "林"],
      ]),
      substages: [
        { id: "finding", label: "寻找", state: "idle", agent: "白望舒", summary: "搜索与登记候选资料" },
        { id: "extract", label: "提炼", state: "idle", agent: "顾言初", summary: "证据卡与价值判断" },
        { id: "relation", label: "关系", state: "idle", agent: "林知序", summary: "主题与证据关系" },
        { id: "ingest", label: "入库", state: "idle", agent: "白书遥", summary: "终审与正式入库" },
      ],
    },
    {
      id: "experiment",
      index: "02",
      title: "实验设计",
      detail: "假设 · 协议 · 门禁",
      state: "idle",
      badge: "等待前置",
      metrics: ["假设 0", "协议未冻结"],
      agents: agents([
        ["林知序", "实验规划", "林"],
        ["沈观止", "实验证据", "沈"],
      ]),
      substages: [
        { id: "hypothesis", label: "假设", state: "idle", agent: "林知序", summary: "可证伪假设与变量" },
        { id: "protocol", label: "协议", state: "idle", agent: "沈观止", summary: "冻结实验协议" },
        { id: "smoke", label: "Smoke", state: "idle", agent: "沈观止", summary: "冒烟门禁" },
      ],
    },
    {
      id: "iteration",
      index: "03",
      title: "执行与迭代",
      detail: "运行 · 评估 · 晋升",
      state: "idle",
      badge: "等待前置",
      metrics: ["轮次 0", "结论 —"],
      agents: agents([
        ["周衡", "执行调度", "周"],
        ["沈观止", "评估门禁", "沈"],
        ["林知序", "晋升决策", "林", false],
      ]),
      substages: [
        { id: "run", label: "执行", state: "idle", agent: "周衡", summary: "批次运行与日志" },
        { id: "eval", label: "评估", state: "idle", agent: "沈观止", summary: "指标与门禁判定" },
        { id: "promote", label: "晋升", state: "idle", agent: "林知序", summary: "晋升或归档回退" },
      ],
    },
  ];

  return defaults.map((stage) => ({
    ...stage,
    ...partial[stage.id],
    agents: partial[stage.id]?.agents ?? stage.agents,
    substages: partial[stage.id]?.substages ?? stage.substages,
    metrics: partial[stage.id]?.metrics ?? stage.metrics,
  }));
}

const SCENARIOS: Scenario[] = [
  {
    id: "collecting",
    label: "知识搜集中",
    project: "稀疏预测误差门控假说",
    currentStageId: "knowledge_collection",
    currentSubId: "extract",
    currentLabel: "知识搜集 · 资料提炼",
    progress: "阶段 1/3 · 子步 2/4",
    runStatus: "running",
    nextAction: "完成证据卡后进入关系整理",
    stages: baseStages({
      knowledge_collection: {
        state: "active",
        badge: "进行中",
        metrics: ["资料 18", "证据 6", "待审 3"],
        substages: [
          { id: "finding", label: "寻找", state: "done", agent: "白望舒", summary: "本轮候选已登记" },
          { id: "extract", label: "提炼", state: "active", agent: "顾言初", summary: "3 条证据卡待确认" },
          { id: "relation", label: "关系", state: "idle", agent: "林知序", summary: "等待提炼输出" },
          { id: "ingest", label: "入库", state: "idle", agent: "白书遥", summary: "等待关系闭环" },
        ],
      },
      experiment: { state: "idle", badge: "等待交接" },
      iteration: { state: "idle", badge: "锁定" },
    }),
    edges: [
      { id: "kc-ex", from: "knowledge_collection", to: "experiment", label: "证据交接", state: "idle" },
      { id: "ex-it", from: "experiment", to: "iteration", label: "协议放行", state: "idle" },
    ],
  },
  {
    id: "handoff",
    label: "阶段交接",
    project: "稀疏预测误差门控假说",
    currentStageId: "knowledge_collection",
    currentSubId: "ingest",
    currentLabel: "知识搜集 → 实验设计",
    progress: "交接中 · 门禁检查",
    runStatus: "handing_off",
    nextAction: "确认证据包后进入实验设计",
    stages: baseStages({
      knowledge_collection: {
        state: "done",
        badge: "已完成",
        metrics: ["资料 24", "证据 12", "入库 12"],
        substages: [
          { id: "finding", label: "寻找", state: "done", agent: "白望舒", summary: "闭环完成" },
          { id: "extract", label: "提炼", state: "done", agent: "顾言初", summary: "闭环完成" },
          { id: "relation", label: "关系", state: "done", agent: "林知序", summary: "闭环完成" },
          { id: "ingest", label: "入库", state: "done", agent: "白书遥", summary: "证据包待交接" },
        ],
      },
      experiment: {
        state: "ready",
        badge: "可进入",
        metrics: ["假设草稿 1", "协议未冻结"],
      },
      iteration: { state: "idle", badge: "锁定" },
    }),
    edges: [
      { id: "kc-ex", from: "knowledge_collection", to: "experiment", label: "证据交接", state: "active" },
      { id: "ex-it", from: "experiment", to: "iteration", label: "协议放行", state: "idle" },
    ],
  },
  {
    id: "experiment",
    label: "实验设计中",
    project: "稀疏预测误差门控假说",
    currentStageId: "experiment",
    currentSubId: "protocol",
    currentLabel: "实验设计 · 协议冻结",
    progress: "阶段 2/3 · 子步 2/3",
    runStatus: "running",
    nextAction: "冻结协议并跑 smoke",
    stages: baseStages({
      knowledge_collection: {
        state: "done",
        badge: "已完成",
        metrics: ["资料 24", "证据 12"],
        substages: [
          { id: "finding", label: "寻找", state: "done", agent: "白望舒", summary: "已归档" },
          { id: "extract", label: "提炼", state: "done", agent: "顾言初", summary: "已归档" },
          { id: "relation", label: "关系", state: "done", agent: "林知序", summary: "已归档" },
          { id: "ingest", label: "入库", state: "done", agent: "白书遥", summary: "已归档" },
        ],
      },
      experiment: {
        state: "active",
        badge: "进行中",
        metrics: ["假设 2", "协议草稿", "smoke 待跑"],
        substages: [
          { id: "hypothesis", label: "假设", state: "done", agent: "林知序", summary: "2 条可证伪假设" },
          { id: "protocol", label: "协议", state: "active", agent: "沈观止", summary: "seed/数据已填，待冻结" },
          { id: "smoke", label: "Smoke", state: "idle", agent: "沈观止", summary: "等待协议冻结" },
        ],
      },
      iteration: { state: "idle", badge: "等待前置" },
    }),
    edges: [
      { id: "kc-ex", from: "knowledge_collection", to: "experiment", label: "证据交接", state: "done" },
      { id: "ex-it", from: "experiment", to: "iteration", label: "协议放行", state: "idle" },
    ],
  },
  {
    id: "iteration",
    label: "执行迭代中",
    project: "稀疏预测误差门控假说",
    currentStageId: "iteration",
    currentSubId: "eval",
    currentLabel: "执行与迭代 · 评估",
    progress: "阶段 3/3 · 轮次 2",
    runStatus: "running",
    nextAction: "评估后门禁决定晋升或回退",
    stages: baseStages({
      knowledge_collection: { state: "done", badge: "已完成", metrics: ["资料 24", "证据 12"] },
      experiment: {
        state: "done",
        badge: "已放行",
        metrics: ["假设 2", "协议冻结", "smoke 通过"],
        substages: [
          { id: "hypothesis", label: "假设", state: "done", agent: "林知序", summary: "已冻结" },
          { id: "protocol", label: "协议", state: "done", agent: "沈观止", summary: "已冻结" },
          { id: "smoke", label: "Smoke", state: "done", agent: "沈观止", summary: "通过" },
        ],
      },
      iteration: {
        state: "active",
        badge: "进行中",
        metrics: ["轮次 2", "MSE 0.084", "门禁待判"],
        substages: [
          { id: "run", label: "执行", state: "done", agent: "周衡", summary: "run#2 完成" },
          { id: "eval", label: "评估", state: "active", agent: "沈观止", summary: "对比 baseline 中" },
          { id: "promote", label: "晋升", state: "idle", agent: "林知序", summary: "等待评估" },
        ],
      },
    }),
    edges: [
      { id: "kc-ex", from: "knowledge_collection", to: "experiment", label: "证据交接", state: "done" },
      { id: "ex-it", from: "experiment", to: "iteration", label: "协议放行", state: "done" },
    ],
  },
  {
    id: "blocked",
    label: "阻塞 / 失败",
    project: "稀疏预测误差门控假说",
    currentStageId: "experiment",
    currentSubId: "smoke",
    currentLabel: "实验设计 · Smoke 失败",
    progress: "阶段 2/3 · 阻塞",
    runStatus: "failed",
    nextAction: "修复 smoke 后重试或回退协议",
    stages: baseStages({
      knowledge_collection: { state: "done", badge: "已完成", metrics: ["资料 24", "证据 12"] },
      experiment: {
        state: "blocked",
        badge: "Smoke 失败",
        metrics: ["假设 2", "协议冻结", "smoke ✕"],
        substages: [
          { id: "hypothesis", label: "假设", state: "done", agent: "林知序", summary: "已冻结" },
          { id: "protocol", label: "协议", state: "done", agent: "沈观止", summary: "已冻结" },
          { id: "smoke", label: "Smoke", state: "blocked", agent: "沈观止", summary: "exit 1 · 缺数据列" },
        ],
      },
      iteration: { state: "idle", badge: "锁定" },
    }),
    edges: [
      { id: "kc-ex", from: "knowledge_collection", to: "experiment", label: "证据交接", state: "done" },
      { id: "ex-it", from: "experiment", to: "iteration", label: "协议放行", state: "blocked" },
    ],
  },
];

const PANEL_COPY: Record<
  PanelKey,
  { title: string; legacyPage: string; opsTitle: string }
> = {
  knowledge_collection: {
    title: "知识搜集",
    legacyPage: "原「知识搜集页 / source_collection」",
    opsTitle: "阶段总控 · 资料闭环",
  },
  experiment: {
    title: "实验设计",
    legacyPage: "原「实验设计页」",
    opsTitle: "阶段总控 · 假设与协议",
  },
  iteration: {
    title: "执行与迭代",
    legacyPage: "原「执行迭代页」",
    opsTitle: "阶段总控 · 运行与晋升",
  },
  finding: {
    title: "资料寻找",
    legacyPage: "原寻找/搜索子页",
    opsTitle: "搜索 · 登记 · 候选队列",
  },
  extract: {
    title: "资料提炼",
    legacyPage: "原提炼子页",
    opsTitle: "证据卡 · 价值判断",
  },
  relation: {
    title: "关系整理",
    legacyPage: "原关系/graph 子页",
    opsTitle: "主题 · 证据关系",
  },
  ingest: {
    title: "资料入库",
    legacyPage: "原入库审核子页",
    opsTitle: "终审 · 正式入库",
  },
  hypothesis: {
    title: "假设起草",
    legacyPage: "原假设模块页",
    opsTitle: "可证伪假设 · 变量",
  },
  protocol: {
    title: "协议冻结",
    legacyPage: "原协议模块页",
    opsTitle: "seed · 数据 · 冻结",
  },
  smoke: {
    title: "Smoke 门禁",
    legacyPage: "原 smoke 检查页",
    opsTitle: "冒烟运行 · 放行",
  },
  run: {
    title: "执行批次",
    legacyPage: "原执行页",
    opsTitle: "运行日志 · 产物",
  },
  eval: {
    title: "结果评估",
    legacyPage: "原评估页",
    opsTitle: "指标 · 对比 baseline",
  },
  promote: {
    title: "晋升 / 归档",
    legacyPage: "原迭代决策页",
    opsTitle: "晋升 · 回退 · 版本",
  },
  bindings: {
    title: "角色绑定",
    legacyPage: "原组织画布配置",
    opsTitle: "阶段角色 → Agent",
  },
};

function stateLabel(state: NodeState): string {
  switch (state) {
    case "active":
      return "当前";
    case "done":
      return "完成";
    case "ready":
      return "可进入";
    case "blocked":
      return "阻塞";
    default:
      return "等待";
  }
}

function macroOf(panel: PanelKey): MacroId | "bindings" {
  if (panel === "bindings") return "bindings";
  if (
    panel === "knowledge_collection"
    || panel === "finding"
    || panel === "extract"
    || panel === "relation"
    || panel === "ingest"
  ) {
    return "knowledge_collection";
  }
  if (panel === "experiment" || panel === "hypothesis" || panel === "protocol" || panel === "smoke") {
    return "experiment";
  }
  return "iteration";
}

function buildOps(
  scenario: Scenario,
  panel: PanelKey,
  stage: StageNode | undefined,
  sub: SubStage | undefined,
): OpsBlock {
  const copy = PANEL_COPY[panel];
  const isCurrentMacro = stage?.id === scenario.currentStageId;
  const isCurrentSub = sub?.id === scenario.currentSubId;

  if (panel === "bindings") {
    return {
      title: copy.opsTitle,
      body: "组织拓扑不再作为主页面；在此同页配置阶段角色绑定。保存后流程图节点上的 Agent 胶囊即时更新。",
      rows: [
        { label: "模式", value: "配置次级面板（非独立页）" },
        { label: "数据源", value: "canvas nodes / members / fallback" },
        { label: "影响面", value: "全部阶段节点 Agent 展示" },
      ],
      actions: [
        { id: "save-bind", label: "保存绑定", primary: true },
        { id: "auto-layout", label: "按角色建议填充" },
      ],
      feed: [
        "科研协调 → 白书遥",
        "资料寻找 → 白望舒",
        "实验规划 → 林知序",
      ],
    };
  }

  if (sub) {
    const actions: OpsAction[] =
      sub.state === "blocked"
        ? [
            { id: "retry", label: "重试本步", primary: true },
            { id: "chat", label: "Agent 私聊" },
            { id: "back", label: "回退上一步", danger: true },
          ]
        : sub.state === "active" || isCurrentSub
          ? [
              { id: "run", label: "继续本步", primary: true },
              { id: "chat", label: "Agent 私聊" },
              { id: "approve", label: "确认输出" },
            ]
          : sub.state === "done"
            ? [
                { id: "review", label: "查看产出", primary: true },
                { id: "chat", label: "Agent 私聊" },
                { id: "rerun", label: "重跑本步" },
              ]
            : [
                { id: "open", label: "准备本步", primary: true },
                { id: "chat", label: "Agent 私聊" },
              ];

    return {
      title: copy.opsTitle,
      body: `${sub.summary}。本面板对应节点「${stage?.title ?? ""} / ${sub.label}」，切换节点只换本区内容，不离开工作台。`,
      rows: [
        { label: "原页面", value: copy.legacyPage },
        { label: "绑定 Agent", value: sub.agent ?? "未绑定" },
        { label: "节点状态", value: `${stateLabel(sub.state)}${isCurrentSub ? " · runtime 当前" : ""}` },
        { label: "导航方式", value: "流程图节点选中（同页）" },
      ],
      actions,
      feed: [
        isCurrentSub ? "runtime 当前子步：操作优先落在这里" : "非 runtime 当前：可回看与准备，默认不抢跑",
        "列表 / 表单 / Agent 对话 / 门禁均在此区完成",
        "顶栏流程图始终可见，用于定位与跳转",
      ],
    };
  }

  // Macro stage panel
  const activeSub = stage?.substages.find((s) => s.state === "active" || s.state === "blocked");
  return {
    title: copy.opsTitle,
    body: `阶段总控面板：聚合 ${stage?.title ?? copy.title} 的指标、子步与主操作。点左侧/上方子节点进入具体作业区，无需打开新路由页。`,
    rows: [
      { label: "原页面", value: copy.legacyPage },
      { label: "阶段状态", value: `${stage?.badge ?? "—"}${isCurrentMacro ? " · runtime 当前" : ""}` },
      { label: "指标", value: stage?.metrics.join(" · ") ?? "—" },
      { label: "聚焦子步", value: activeSub ? activeSub.label : "无进行中子步" },
    ],
    actions: isCurrentMacro
      ? [
          { id: "continue", label: scenario.nextAction.slice(0, 14) || "继续当前", primary: true },
          { id: "agents", label: "管理绑定" },
          { id: "handoff", label: "检查交接" },
        ]
      : stage?.state === "ready"
        ? [
            { id: "enter", label: "进入本阶段", primary: true },
            { id: "agents", label: "管理绑定" },
          ]
        : [
            { id: "review", label: "回看本阶段", primary: true },
            { id: "agents", label: "管理绑定" },
          ],
    feed: [
      ...(stage?.substages.map((s) => `${s.label}：${stateLabel(s.state)}${s.agent ? ` · ${s.agent}` : ""}`) ?? []),
    ],
  };
}

function ResearchProcessFlowPreviewApp() {
  const [scenarioId, setScenarioId] = useState<ScenarioId>("collecting");
  const [selectedPanel, setSelectedPanel] = useState<PanelKey>("extract");
  const [toast, setToast] = useState<string | null>(null);

  const scenario = useMemo(
    () => SCENARIOS.find((item) => item.id === scenarioId) ?? SCENARIOS[0],
    [scenarioId],
  );

  useEffect(() => {
    setSelectedPanel(scenario.currentSubId ?? scenario.currentStageId);
  }, [scenario.currentStageId, scenario.currentSubId, scenarioId]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const selectedMacroId = macroOf(selectedPanel);
  const selectedStage =
    selectedMacroId === "bindings"
      ? undefined
      : scenario.stages.find((s) => s.id === selectedMacroId);
  const selectedSub = selectedStage?.substages.find((s) => s.id === selectedPanel);
  const ops = buildOps(scenario, selectedPanel, selectedStage, selectedSub);
  const panelMeta = PANEL_COPY[selectedPanel];

  const selectPanel = (panel: PanelKey, label: string) => {
    setSelectedPanel(panel);
    setToast(`同页切换 → ${label}（不离开工作台）`);
  };

  return (
    <div className="preview-app">
      <header className="topbar">
        <div className="topbar-brand">
          <strong>科研单页工作台 · 流程节点驱动</strong>
          <span>流程图为主表面；原多页面操作全部挂到对应节点，同页切换</span>
        </div>
        <div className="topbar-controls">
          <div className="scenario-pills" role="tablist" aria-label="运行场景">
            {SCENARIOS.map((item) => (
              <button
                key={item.id}
                type="button"
                className="scenario-pill"
                data-active={item.id === scenarioId ? "true" : "false"}
                onClick={() => setScenarioId(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="ghost-btn"
            data-active={selectedPanel === "bindings" ? "true" : "false"}
            onClick={() => selectPanel("bindings", "角色绑定")}
          >
            角色绑定
          </button>
        </div>
      </header>

      <div className="workspace">
        {/* —— Always-visible process graph (primary) —— */}
        <section className="flow-shell" aria-label="流程关系图">
          <div className="flow-shell-head">
            <div>
              <h1>流程关系图</h1>
              <p>
                {scenario.project}
                {" · "}
                <b>runtime 当前：{scenario.currentLabel}</b>
                {" · "}
                {scenario.progress}
              </p>
            </div>
            <div className="flow-shell-meta">
              <span className="chip">{scenario.runStatus}</span>
              <span className="chip chip-strong">{scenario.nextAction}</span>
            </div>
          </div>

          <div className="flow-track" role="list">
            {scenario.stages.map((stage, index) => {
              const isRuntime = stage.id === scenario.currentStageId;
              const isSelectedMacro = selectedMacroId === stage.id;
              const edge = scenario.edges.find((e) => e.from === stage.id);
              return (
                <div key={stage.id} className="flow-track-unit" role="listitem">
                  <button
                    type="button"
                    className="macro-node"
                    data-state={stage.state}
                    data-runtime={isRuntime ? "true" : "false"}
                    data-selected={isSelectedMacro && !selectedSub ? "true" : isSelectedMacro ? "soft" : "false"}
                    onClick={() => selectPanel(stage.id, stage.title)}
                  >
                    <div className="macro-node-top">
                      <span className="macro-index">STAGE {stage.index}</span>
                      <span className="stage-badge" data-state={stage.state}>
                        {isRuntime ? "当前 · " : ""}
                        {stage.badge}
                      </span>
                    </div>
                    <strong>{stage.title}</strong>
                    <em>{stage.detail}</em>
                    <div className="macro-metrics">
                      {stage.metrics.map((m) => (
                        <span key={m}>{m}</span>
                      ))}
                    </div>
                    <div className="agent-row compact">
                      {stage.agents.slice(0, 3).map((agent) => (
                        <span
                          key={`${stage.id}-${agent.name}`}
                          className="agent-pill"
                          data-online={agent.online ? "true" : "false"}
                          title={`${agent.name} · ${agent.role}`}
                        >
                          <i>{agent.initial}</i>
                          {agent.name}
                        </span>
                      ))}
                      {stage.agents.length > 3 ? (
                        <span className="agent-pill more">+{stage.agents.length - 3}</span>
                      ) : null}
                    </div>
                    <div className="sub-rail" role="group" aria-label={`${stage.title} 子节点`}>
                      {stage.substages.map((sub) => {
                        const isSubSelected = selectedPanel === sub.id;
                        const isSubRuntime = scenario.currentSubId === sub.id;
                        return (
                          <button
                            key={sub.id}
                            type="button"
                            className="sub-node"
                            data-state={sub.state}
                            data-selected={isSubSelected ? "true" : "false"}
                            data-runtime={isSubRuntime ? "true" : "false"}
                            onClick={(event) => {
                              event.stopPropagation();
                              selectPanel(sub.id, `${stage.title} / ${sub.label}`);
                            }}
                          >
                            <i className="dot" data-state={sub.state} />
                            <span>{sub.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  </button>

                  {index < scenario.stages.length - 1 && edge ? (
                    <div className="flow-edge" data-state={edge.state} aria-hidden="true">
                      <span>{edge.label}</span>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          <div className="flow-legend">
            <span>外环 / 「当前」= runtime 阶段（不随点选消失）</span>
            <span>实心描边 = 你正在操作的节点（同页面板）</span>
            <span>子节点 = 原独立子页面，挂在宏阶段下</span>
          </div>
        </section>

        {/* —— Single-page ops bound to selected node —— */}
        <section className="ops-shell" aria-label="节点操作区">
          <div className="ops-header">
            <div>
              <div className="ops-kicker">
                节点绑定操作区
                <span className="ops-path">
                  {selectedMacroId === "bindings"
                    ? "配置 / 角色绑定"
                    : `${selectedStage?.title ?? ""}${selectedSub ? ` / ${selectedSub.label}` : " / 阶段总控"}`}
                </span>
              </div>
              <h2>{panelMeta.title}</h2>
              <p>
                取代 {panelMeta.legacyPage}：
                <b>不跳路由</b>，只切换本区。流程图始终在上，用于定位与状态感知。
              </p>
            </div>
            <div className="ops-header-actions">
              {selectedSub ? (
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={() => selectedStage && selectPanel(selectedStage.id, selectedStage.title)}
                >
                  回到阶段总控
                </button>
              ) : null}
              {scenario.currentSubId && selectedPanel !== scenario.currentSubId ? (
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => {
                    const subId = scenario.currentSubId!;
                    const stage = scenario.stages.find((s) => s.id === scenario.currentStageId);
                    const sub = stage?.substages.find((s) => s.id === subId);
                    selectPanel(subId, sub ? `${stage?.title} / ${sub.label}` : "runtime 当前");
                  }}
                >
                  跳到 runtime 当前节点
                </button>
              ) : (
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => setToast(`执行：${ops.actions.find((a) => a.primary)?.label ?? "主操作"}（预览）`)}
                >
                  {ops.actions.find((a) => a.primary)?.label ?? "主操作"}
                </button>
              )}
            </div>
          </div>

          <div className="ops-grid">
            <div className="ops-main panel">
              <header>
                <h3>{ops.title}</h3>
                <span>同页作业</span>
              </header>
              <div className="panel-body">
                <p className="ops-lead">{ops.body}</p>
                <dl className="kv">
                  {ops.rows.map((row) => (
                    <div key={row.label} className="kv-row">
                      <dt>{row.label}</dt>
                      <dd>{row.value}</dd>
                    </div>
                  ))}
                </dl>
                <div className="ops-actions">
                  {ops.actions.map((action) => (
                    <button
                      key={action.id}
                      type="button"
                      className={
                        action.primary
                          ? "primary-btn"
                          : action.danger
                            ? "danger-btn"
                            : "ghost-btn"
                      }
                      onClick={() => {
                        if (action.id === "agents") {
                          selectPanel("bindings", "角色绑定");
                          return;
                        }
                        setToast(`${action.label} · 在「${panelMeta.title}」节点内完成（预览）`);
                      }}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
                <ul className="ops-feed">
                  {ops.feed.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="ops-side">
              <div className="panel">
                <header>
                  <h3>本节点 Agent</h3>
                  <span>
                    {selectedSub?.agent
                      ? "子步主责"
                      : selectedStage
                        ? `${selectedStage.agents.length} 角色`
                        : "全局绑定"}
                  </span>
                </header>
                <div className="panel-body">
                  <ul className="agent-list">
                    {(selectedSub
                      ? selectedStage?.agents.filter((a) => a.name === selectedSub.agent)
                      : selectedStage?.agents
                    )?.map((agent) => (
                      <li key={`${agent.name}-${agent.role}`}>
                        <span className="avatar">{agent.initial}</span>
                        <div>
                          <b>
                            {agent.name}
                            {agent.online ? "" : " · 离线"}
                          </b>
                          <small>{agent.role}</small>
                        </div>
                      </li>
                    )) ?? (
                      <li>
                        <span className="avatar">绑</span>
                        <div>
                          <b>打开角色绑定</b>
                          <small>配置阶段 Agent</small>
                        </div>
                      </li>
                    )}
                  </ul>
                </div>
              </div>

              <div className="panel">
                <header>
                  <h3>同页导航模型</h3>
                  <span>取代多页切换</span>
                </header>
                <div className="panel-body research-map">
                  <article>
                    <b>选节点</b>
                    <span>流程图宏节点 / 子节点 → 仅换下方操作区</span>
                  </article>
                  <article>
                    <b>runtime 当前</b>
                    <span>图上高亮独立于「你在看哪」；可一键跳回当前节点</span>
                  </article>
                  <article>
                    <b>深链</b>
                    <span>
                      <code>?node=extract</code> 只设定选中节点，仍在同一工作台壳
                    </span>
                  </article>
                  <article>
                    <b>禁止</b>
                    <span>为每个阶段再开完整路由页作为主路径；board/canvas 双壳并行</span>
                  </article>
                </div>
              </div>
            </div>
          </div>

          <section className="contract-note" aria-label="单页工作台约定">
            <strong>单页 · 节点驱动 · 需求对齐（在前版流程关系图之上收紧）</strong>
            <ul>
              <li>
                <b>一个工作台页面</b>：科研项目进入后只有一个主壳；知识搜集 / 实验 / 迭代 / 子模块不再作为「离开后进入的独立页面」。
              </li>
              <li>
                <b>流程图是主导航</b>：顶部（或主列上半）常驻流程关系图；所有原页面切换 = 选中对应流程节点（宏或子节点）。
              </li>
              <li>
                <b>操作在同页完成</b>：搜索、提炼、协议冻结、跑 batch、评估、Agent 私聊、门禁确认均在节点操作区完成；弹层/抽屉可有，但不得整页路由跳走。
              </li>
              <li>
                <b>选中 ≠ runtime 当前</b>：允许回看已完成节点或预览下游；runtime 当前始终在图上标记，并提供「跳到当前节点」。
              </li>
              <li>
                <b>组织画布降级</b>：角色绑定作为配置节点/侧面板，不再与流程图抢主表面。
              </li>
              <li>
                <b>实现映射</b>：
                <code>selectedNodeId</code> 驱动面板；
                <code>currentStage</code> 驱动高亮；
                现有 stage panels 改为 slot，而不是 route children。
              </li>
            </ul>
          </section>

          <p className="preview-note">
            预览：<code>/research-process-flow-preview.html</code>
            {" · "}
            设计验收 · 不改生产路由
          </p>
        </section>
      </div>

      {toast ? (
        <div className="toast" role="status" aria-live="polite">
          {toast}
        </div>
      ) : null}
    </div>
  );
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <ResearchProcessFlowPreviewApp />
    </StrictMode>,
  );
}
