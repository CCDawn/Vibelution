/**
 * Full-page product preview for research overview UX.
 * Open: /research-overview-preview.html (Vite: npm run dev -- --port 5179)
 * Design acceptance only — not wired into production TeamsRoute.
 *
 * Contract (P0 overview):
 * 1. Single solid primary CTA in hero — no sibling ghost "open stage" control
 * 2. Three stage cards are read-only progress; "查看" is quiet secondary
 * 3. Advanced details collapsed by default (evidence / validation / owner)
 * 4. Productized error surface for cascade-reset style failures
 */
import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import "./research-overview-preview.css";

type ScenarioId =
  | "empty"
  | "collecting"
  | "handoff"
  | "experiment"
  | "iteration"
  | "blocked"
  | "error";

type StageTone = "done" | "active" | "idle";

type StageCard = {
  id: string;
  index: string;
  title: string;
  status: string;
  tone: StageTone;
  body: string;
  meta: string[];
};

type AgentRow = {
  name: string;
  role: string;
  online: boolean;
  initial: string;
};

type Scenario = {
  id: ScenarioId;
  label: string;
  projectName: string;
  topic: string;
  projectBadge: string;
  projectTone: StageTone | "danger" | "warning";
  nextTitle: string;
  nextBody: string;
  cta: string;
  ctaBlocked?: boolean;
  handoff?: { from: string; to: string; note: string };
  metrics: Array<{ label: string; value: string }>;
  stages: StageCard[];
  agents: AgentRow[];
  activity: Array<{ time: string; text: string }>;
  advanced: Array<{ label: string; value: string }>;
  error?: {
    title: string;
    body: string;
    raw: string;
    primaryAction: string;
    secondaryAction: string;
  };
};

const PROJECT =
  "三阶段验收 | 稀疏预测误差门控假说";
const TOPIC =
  "新假说：在相同数据、固定 seed=42 和同一代理执行器下，引入稀疏预测误差门控，相比固定阈值基线能够降低 reconstruction_mse。";

const AGENTS_KC: AgentRow[] = [
  { name: "白书遥", role: "资料寻找 · 等待任务", online: true, initial: "白" },
  { name: "白望舒", role: "资料提炼 · 可用", online: true, initial: "白" },
  { name: "顾言初", role: "关系整理 · 待命", online: false, initial: "顾" },
];

const AGENTS_EX: AgentRow[] = [
  { name: "林知序", role: "假设起草 · 进行中", online: true, initial: "林" },
  { name: "沈观止", role: "协议冻结 · 可用", online: true, initial: "沈" },
  { name: "顾言初", role: "证据关联 · 待命", online: true, initial: "顾" },
];

const AGENTS_IT: AgentRow[] = [
  { name: "周衡", role: "执行调度 · 运行中", online: true, initial: "周" },
  { name: "沈观止", role: "评估门禁 · 可用", online: true, initial: "沈" },
  { name: "林知序", role: "晋升决策 · 待命", online: false, initial: "林" },
];

const SCENARIOS: Scenario[] = [
  {
    id: "empty",
    label: "空项目",
    projectName: PROJECT,
    topic: TOPIC,
    projectBadge: "未启动",
    projectTone: "idle",
    nextTitle: "开始知识搜集",
    nextBody: "从资料搜索批次开始，建立本项目的证据基础。完成后可进入实验设计。",
    cta: "开始搜集",
    metrics: [
      { label: "阶段", value: "知识搜集" },
      { label: "资料批次", value: "0" },
      { label: "候选", value: "0" },
    ],
    stages: [
      {
        id: "kc",
        index: "01",
        title: "知识搜集",
        status: "未开始",
        tone: "idle",
        body: "生成搜索计划和团队分工，先把资料搜索跑起来。",
        meta: ["资料寻找", "提炼", "关系", "入库"],
      },
      {
        id: "ex",
        index: "02",
        title: "实验设计",
        status: "等待上游",
        tone: "idle",
        body: "知识搜集后，由用户决定启动实验规划。",
        meta: ["假设", "变量", "冻结设计"],
      },
      {
        id: "it",
        index: "03",
        title: "执行与迭代",
        status: "等待上游",
        tone: "idle",
        body: "冻结实验设计后进入执行、评估和迭代。",
        meta: ["批次", "评估", "晋升"],
      },
    ],
    agents: AGENTS_KC,
    activity: [
      { time: "—", text: "尚无项目活动" },
    ],
    advanced: [
      { label: "工作流", value: "challenge_cup_research" },
      { label: "Owner", value: "team-lead-agent" },
      { label: "校验", value: "延后至需要时" },
    ],
  },
  {
    id: "collecting",
    label: "搜集中",
    projectName: PROJECT,
    topic: TOPIC,
    projectBadge: "知识搜集中",
    projectTone: "active",
    nextTitle: "继续知识搜集",
    nextBody: "完善资料批次、提炼与入库；形成可用假设后可进入实验设计。",
    cta: "进入知识搜集",
    metrics: [
      { label: "阶段", value: "知识搜集" },
      { label: "资料批次", value: "2" },
      { label: "候选", value: "17" },
    ],
    stages: [
      {
        id: "kc",
        index: "01",
        title: "知识搜集",
        status: "进行中",
        tone: "active",
        body: "已有资料批次与候选；继续提炼、审查并准备入库。",
        meta: ["批次 2", "候选 17", "成员 5/5"],
      },
      {
        id: "ex",
        index: "02",
        title: "实验设计",
        status: "未开始",
        tone: "idle",
        body: "待知识搜集形成可用假设后启动。",
        meta: ["假设", "变量", "冻结设计"],
      },
      {
        id: "it",
        index: "03",
        title: "执行与迭代",
        status: "等待上游",
        tone: "idle",
        body: "冻结实验设计后进入执行、评估和迭代。",
        meta: ["批次", "评估", "晋升"],
      },
    ],
    agents: AGENTS_KC,
    activity: [
      { time: "10:34", text: "资料寻找返回 17 条候选" },
      { time: "10:31", text: "创建知识搜集批次 #2" },
      { time: "10:28", text: "更新研究主题" },
    ],
    advanced: [
      { label: "证据链", value: "模型调用证据 2/6 · 若干 missing 项" },
      { label: "校验", value: "候选校验已延后" },
      { label: "活跃项", value: "3" },
    ],
  },
  {
    id: "handoff",
    label: "可交接",
    projectName: PROJECT,
    topic: TOPIC,
    projectBadge: "可进入实验",
    projectTone: "active",
    nextTitle: "进入实验设计",
    nextBody:
      "资料阶段已有轮次。建议进入实验设计，将证据收敛为可证伪假设与冻结协议。",
    cta: "进入实验设计",
    handoff: {
      from: "知识搜集",
      to: "实验设计",
      note: "资料阶段可交接 · 证据已形成可用假设",
    },
    metrics: [
      { label: "阶段", value: "知识搜集 → 实验" },
      { label: "资料批次", value: "2" },
      { label: "候选", value: "17" },
    ],
    stages: [
      {
        id: "kc",
        index: "01",
        title: "知识搜集",
        status: "已完成",
        tone: "done",
        body: "知识搜集已形成可用假设；可查看历史，或按新问题补充资料。",
        meta: ["成员 5/5", "入库就绪"],
      },
      {
        id: "ex",
        index: "02",
        title: "实验设计",
        status: "可启动",
        tone: "active",
        body: "上游已就绪。起草假设、变量与复现合同。",
        meta: ["假设", "变量", "冻结设计"],
      },
      {
        id: "it",
        index: "03",
        title: "执行与迭代",
        status: "等待上游",
        tone: "idle",
        body: "冻结实验设计后进入执行、评估和迭代。",
        meta: ["批次", "评估", "晋升"],
      },
    ],
    agents: AGENTS_EX,
    activity: [
      { time: "11:02", text: "知识阶段门禁通过" },
      { time: "10:58", text: "审核入库 12 条" },
      { time: "10:34", text: "资料批次 #2 完成" },
    ],
    advanced: [
      { label: "交接", value: "knowledge_collection → experiment" },
      { label: "证据", value: "正式条目 12 · 候选关联 17" },
      { label: "校验", value: "valid 12 / 17" },
    ],
  },
  {
    id: "experiment",
    label: "实验中",
    projectName: PROJECT,
    topic: TOPIC,
    projectBadge: "实验设计中",
    projectTone: "active",
    nextTitle: "继续实验设计",
    nextBody: "设计已冻结；可补证据或在门禁允许时进入执行迭代。",
    cta: "继续实验设计",
    metrics: [
      { label: "阶段", value: "实验设计" },
      { label: "资料批次", value: "2" },
      { label: "候选", value: "17" },
    ],
    stages: [
      {
        id: "kc",
        index: "01",
        title: "知识搜集",
        status: "已完成",
        tone: "done",
        body: "知识搜集已形成可用假设；可查看历史，或按新问题补充资料。",
        meta: ["成员 5/5"],
      },
      {
        id: "ex",
        index: "02",
        title: "实验设计",
        status: "已设计 · 待执行",
        tone: "active",
        body: "实验设计已冻结；训练结果不参与本阶段完成判定。",
        meta: ["方式：模型训练", "冻结 v4", "可执行"],
      },
      {
        id: "it",
        index: "03",
        title: "执行与迭代",
        status: "可启动",
        tone: "idle",
        body: "冻结实验设计后进入执行、优化和迭代。",
        meta: ["成员 4/4"],
      },
    ],
    agents: AGENTS_EX,
    activity: [
      { time: "14:20", text: "冻结 Design v4" },
      { time: "14:05", text: "绑定执行器 formal" },
      { time: "13:40", text: "起草可证伪假设" },
    ],
    advanced: [
      { label: "计划", value: "exp-plan-20260803120114-a634fb45" },
      { label: "证据", value: "正式写入关闭 · 候选关联 2" },
      { label: "门禁", value: "4 / 4 已满足" },
    ],
  },
  {
    id: "iteration",
    label: "迭代中",
    projectName: PROJECT,
    topic: TOPIC,
    projectBadge: "执行迭代中",
    projectTone: "active",
    nextTitle: "继续执行与迭代",
    nextBody: "在执行迭代台查看批次、评估与晋升门禁。",
    cta: "进入执行迭代",
    metrics: [
      { label: "阶段", value: "执行与迭代" },
      { label: "资料批次", value: "2" },
      { label: "候选", value: "17" },
    ],
    stages: [
      {
        id: "kc",
        index: "01",
        title: "知识搜集",
        status: "已完成",
        tone: "done",
        body: "知识搜集已形成可用假设。",
        meta: ["成员 5/5"],
      },
      {
        id: "ex",
        index: "02",
        title: "实验设计",
        status: "已设计 · 待执行",
        tone: "done",
        body: "实验设计已冻结。",
        meta: ["冻结 v4", "可执行"],
      },
      {
        id: "it",
        index: "03",
        title: "执行与迭代",
        status: "已晋升",
        tone: "active",
        body: "最佳版本已通过评估；最近诊断单独展示，不覆盖主线结果。",
        meta: ["诊断 smoke_needs_review", "成员 4/4"],
      },
    ],
    agents: AGENTS_IT,
    activity: [
      { time: "16:12", text: "formal-v4 通过门禁 · +2.8%" },
      { time: "15:50", text: "诊断 run smoke_needs_review" },
      { time: "15:10", text: "启动 formal 批次 · 5 seeds" },
    ],
    advanced: [
      { label: "最近诊断", value: "smoke_needs_review" },
      { label: "记忆", value: "已用 5 · 禁重 0" },
      { label: "最佳候选", value: "formal-v4" },
    ],
  },
  {
    id: "blocked",
    label: "阻塞",
    projectName: PROJECT,
    topic: TOPIC,
    projectBadge: "等待上游",
    projectTone: "warning",
    nextTitle: "先选择科研项目",
    nextBody: "总览需要激活的科研项目后才能给出下一步。",
    cta: "选择项目",
    ctaBlocked: true,
    metrics: [
      { label: "阶段", value: "—" },
      { label: "资料批次", value: "—" },
      { label: "候选", value: "—" },
    ],
    stages: [
      {
        id: "kc",
        index: "01",
        title: "知识搜集",
        status: "不可用",
        tone: "idle",
        body: "激活科研项目后显示阶段状态。",
        meta: ["—"],
      },
      {
        id: "ex",
        index: "02",
        title: "实验设计",
        status: "不可用",
        tone: "idle",
        body: "激活科研项目后显示阶段状态。",
        meta: ["—"],
      },
      {
        id: "it",
        index: "03",
        title: "执行与迭代",
        status: "不可用",
        tone: "idle",
        body: "激活科研项目后显示阶段状态。",
        meta: ["—"],
      },
    ],
    agents: [],
    activity: [{ time: "—", text: "未绑定活跃科研项目" }],
    advanced: [
      { label: "阻塞原因", value: "无激活科研项目" },
      { label: "建议", value: "在项目切换器中选择或新建项目" },
    ],
  },
  {
    id: "error",
    label: "错误态",
    projectName: PROJECT,
    topic: TOPIC,
    projectBadge: "清空受阻",
    projectTone: "danger",
    nextTitle: "继续知识搜集",
    nextBody: "完善资料批次、提炼与入库；形成可用假设后可进入实验设计。",
    cta: "进入知识搜集",
    metrics: [
      { label: "阶段", value: "知识搜集" },
      { label: "资料批次", value: "2" },
      { label: "候选", value: "17" },
    ],
    stages: [
      {
        id: "kc",
        index: "01",
        title: "知识搜集",
        status: "进行中",
        tone: "active",
        body: "已有资料批次与候选；清空资料受下游实验/迭代阻塞。",
        meta: ["批次 2", "候选 17"],
      },
      {
        id: "ex",
        index: "02",
        title: "实验设计",
        status: "已有轮次",
        tone: "done",
        body: "存在实验产物，阻止「仅清资料」。",
        meta: ["冻结 v4"],
      },
      {
        id: "it",
        index: "03",
        title: "执行与迭代",
        status: "已有轮次",
        tone: "done",
        body: "存在迭代产物，需级联重置才能清空资料。",
        meta: ["formal-v4"],
      },
    ],
    agents: AGENTS_KC,
    activity: [
      { time: "17:01", text: "清空资料失败 · 下游产物阻塞" },
      { time: "16:12", text: "formal-v4 通过门禁" },
    ],
    advanced: [
      { label: "重置策略", value: "cascade · 含 experiment / iteration" },
      { label: "范围", value: "当前 researchProjectId" },
    ],
    error: {
      title: "仅清资料不可用",
      body: "本项目已有实验/迭代或下游候选。可改用「连同实验与迭代一起清空」，或保留现状继续推进。",
      raw: "Cannot clear sources: downstream experiment/iteration artifacts exist",
      primaryAction: "连同实验与迭代一起清空",
      secondaryAction: "保留并继续",
    },
  },
];

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        transform: open ? "rotate(0deg)" : "rotate(-90deg)",
        transition: "transform 150ms ease",
        color: "var(--subtle)",
      }}
      aria-hidden="true"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function CompassIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" aria-hidden="true">
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}

function AlertIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

function ResearchOverviewPreviewApp() {
  const [scenarioId, setScenarioId] = useState<ScenarioId>("handoff");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [toast, setToast] = useState("");

  const scenario = useMemo(
    () => SCENARIOS.find((item) => item.id === scenarioId) ?? SCENARIOS[0],
    [scenarioId],
  );

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const connectorFilled = (leftTone: StageTone) => leftTone === "done";

  return (
    <div className="preview-app">
      <header className="topbar">
        <div className="topbar-brand">
          <div className="topbar-mark" aria-hidden="true" />
          <div>
            <strong>Vibelution</strong>
            <span>本地 Agent 工作台</span>
          </div>
        </div>
        <nav className="topbar-nav" aria-label="主导航">
          <button type="button">对话</button>
          <button type="button">监督进化</button>
          <button type="button">自进化</button>
          <button type="button" data-active="true">
            团队
          </button>
          <button type="button">Kernel</button>
          <button type="button">记忆库</button>
        </nav>
        <div className="topbar-meta">
          <span className="pill">
            <span className="pill-dot" />
            前端预览
          </span>
          <span>v1.0.16</span>
          <button type="button" className="icon-btn" aria-label="刷新">
            ↻
          </button>
          <button type="button" className="icon-btn" aria-label="设置">
            ⚙
          </button>
        </div>
      </header>

      <div className="layout">
        <aside className="rail" aria-label="团队侧栏">
          <div className="rail-block">
            <div className="rail-label">团队</div>
            <button type="button" className="rail-item" data-active="true">
              挑战杯科研
              <small>活跃</small>
            </button>
            <button type="button" className="rail-item">
              示例协作组
            </button>
          </div>
          <div className="rail-block">
            <div className="rail-label">视图</div>
            <button type="button" className="rail-item" data-active="true">
              科研总览
            </button>
            <button type="button" className="rail-item">
              知识搜集
            </button>
            <button type="button" className="rail-item">
              实验设计
            </button>
            <button type="button" className="rail-item">
              执行迭代
            </button>
          </div>
          <div className="rail-block">
            <div className="rail-label">预览说明</div>
            <p style={{ margin: "0 6px", fontSize: 11.5, lineHeight: 1.45, color: "var(--subtle)" }}>
              本页验收「总览只读 + 单一主 CTA」信息架构。阶段工作台不在此展开。
            </p>
          </div>
        </aside>

        <main className="page">
          <div className="scenario-bar" aria-label="预览场景">
            <strong>场景</strong>
            {SCENARIOS.map((item) => (
              <button
                key={item.id}
                type="button"
                data-active={item.id === scenarioId ? "true" : "false"}
                onClick={() => {
                  setScenarioId(item.id);
                  setAdvancedOpen(false);
                }}
              >
                {item.label}
              </button>
            ))}
            <span className="scenario-hint">切换假数据 · 不请求后端</span>
          </div>

          <div className="workspace-tabs" role="tablist" aria-label="工作区">
            <button type="button" data-active="true" role="tab" aria-selected="true">
              科研工作台
            </button>
            <button type="button" role="tab" aria-selected="false">
              项目进展
            </button>
          </div>

          <section className="project-header" aria-label="当前项目">
            <div className="project-header-main">
              <div className="eyebrow">当前研究项目</div>
              <div className="project-title-line">
                <h1 className="project-title">{scenario.projectName}</h1>
                <span className="state-badge" data-tone={scenario.projectTone}>
                  {scenario.projectBadge}
                </span>
              </div>
              <p className="project-topic">{scenario.topic}</p>
            </div>
            <div className="project-actions">
              <select className="select" defaultValue={scenario.projectName} aria-label="切换项目">
                <option>{scenario.projectName}</option>
                <option>示例项目 B · 临床知识推理</option>
              </select>
              <button type="button" className="btn btn-ghost">
                编辑
              </button>
              <button type="button" className="btn">
                研究关系图
              </button>
            </div>
          </section>

          {scenario.error ? (
            <section className="error-surface" aria-label="工作流错误">
              <header>
                <AlertIcon />
                <strong>{scenario.error.title}</strong>
              </header>
              <p>{scenario.error.body}</p>
              <p className="error-raw">{scenario.error.raw}</p>
              <div className="error-actions">
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => setToast(`已触发：${scenario.error!.primaryAction}`)}
                >
                  {scenario.error.primaryAction}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setToast(scenario.error!.secondaryAction)}
                >
                  {scenario.error.secondaryAction}
                </button>
              </div>
            </section>
          ) : null}

          {/* Single hero next step — Linear style */}
          <section
            className="next-card"
            aria-label="建议下一步"
            data-blocked={scenario.ctaBlocked ? "true" : "false"}
          >
            <div className="next-card-top">
              <span className="next-badge">
                <CompassIcon />
                下一步
              </span>
              <span aria-hidden="true">·</span>
              <span>{scenario.projectName}</span>
            </div>
            <h2>{scenario.nextTitle}</h2>
            <p>{scenario.nextBody}</p>
            {scenario.handoff ? (
              <div className="handoff-banner" role="status">
                <strong>阶段交接</strong>
                <span>
                  {scenario.handoff.from} → {scenario.handoff.to}
                </span>
                <span aria-hidden="true">·</span>
                <span>{scenario.handoff.note}</span>
              </div>
            ) : null}
            <div className="metric-row">
              {scenario.metrics.map((metric) => (
                <div key={metric.label} className="metric">
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                </div>
              ))}
            </div>
            <div className="next-card-actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={scenario.ctaBlocked}
                onClick={() => {
                  if (scenario.ctaBlocked) return;
                  setToast(`已触发主 CTA：${scenario.cta}`);
                }}
              >
                {scenario.cta}
                {!scenario.ctaBlocked ? <ArrowIcon /> : null}
              </button>
              {/* Intentionally NO sibling ghost "打开对应阶段工作台" */}
            </div>
          </section>

          <div className="section-label">
            <h3>三阶段进度</h3>
            <span>只读概览 · 操作请用上方主按钮</span>
          </div>

          <section className="stage-pipeline" aria-label="三阶段进度">
            {scenario.stages.flatMap((stage, index) => {
              const nodes = [];
              if (index > 0) {
                nodes.push(
                  <div
                    key={`c-${stage.id}`}
                    className="stage-connector"
                    data-filled={
                      connectorFilled(scenario.stages[index - 1].tone) ? "true" : "false"
                    }
                    aria-hidden="true"
                  />,
                );
              }
              nodes.push(
                <article key={stage.id} className="stage-card" data-tone={stage.tone}>
                  <div className="stage-head">
                    <div className="stage-index">{stage.index}</div>
                    <div>
                      <h4>{stage.title}</h4>
                      <span className="status-chip" data-tone={stage.tone}>
                        {stage.status}
                      </span>
                    </div>
                  </div>
                  <p className="stage-body">{stage.body}</p>
                  <div className="stage-meta">
                    {stage.meta.map((item) => (
                      <em key={item}>{item}</em>
                    ))}
                  </div>
                  <div className="stage-foot">
                    <span className="role">
                      {stage.tone === "active"
                        ? "当前阶段"
                        : stage.tone === "done"
                          ? "已完成"
                          : "未开始"}
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => setToast(`只读查看：${stage.title}（不启动阶段）`)}
                    >
                      查看
                    </button>
                  </div>
                </article>,
              );
              return nodes;
            })}
          </section>

          <div className="secondary-grid">
            <section className="panel-card" aria-label="协作状态">
              <header>
                <h3>当前阶段 Agent</h3>
                <span>{scenario.agents.length ? `${scenario.agents.filter((a) => a.online).length} 在线` : "—"}</span>
              </header>
              {scenario.agents.length ? (
                <div className="agent-list">
                  {scenario.agents.map((agent) => (
                    <div key={agent.name} className="agent-row">
                      <span className="avatar">{agent.initial}</span>
                      <div>
                        <strong>{agent.name}</strong>
                        <small>{agent.role}</small>
                      </div>
                      <i className="online-dot" data-off={!agent.online ? "true" : undefined} />
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ margin: 0, fontSize: 12.5, color: "var(--subtle)" }}>
                  激活项目后显示阶段协作成员
                </p>
              )}
            </section>

            <section className="panel-card" aria-label="最近活动">
              <header>
                <h3>最近活动</h3>
                <span>项目动态</span>
              </header>
              <ul className="activity-list">
                {scenario.activity.map((item) => (
                  <li key={`${item.time}-${item.text}`}>
                    <time>{item.time}</time>
                    <p>{item.text}</p>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section className="advanced">
            <button
              type="button"
              className="advanced-toggle"
              aria-expanded={advancedOpen}
              onClick={() => setAdvancedOpen((value) => !value)}
            >
              <Chevron open={advancedOpen} />
              <strong>高级详情</strong>
              <span>{advancedOpen ? "收起" : "证据与校验"}</span>
            </button>
            {advancedOpen ? (
              <dl className="advanced-panel">
                {scenario.advanced.map((row) => (
                  <div key={row.label} className="advanced-row">
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
                <div className="advanced-row">
                  <dt>说明</dt>
                  <dd>
                    预览页不展示原始磁盘路径；生产环境路径仅出现在高级详情展开后。
                  </dd>
                </div>
              </dl>
            ) : null}
          </section>

          <section className="contract-note" aria-label="设计验收约定">
            <strong>设计验收约定（P0 总览）</strong>
            <ul>
              <li>主路径只有一颗实心主按钮；禁止在 CTA 旁放「打开对应阶段工作台」幽灵文案控件</li>
              <li>三阶段卡片只读：展示进度与「查看」，不在总览内嵌完整工作台</li>
              <li>高级详情默认折叠：证据链 / 校验 / Owner / 计划 ID</li>
              <li>下游阻塞清空时使用产品化错误文案 + 级联重置动作，不用原始英文堆栈</li>
              <li>暗色壳层对齐工作台 tokens，避免浅色 demo 与产品验收错位</li>
            </ul>
          </section>

          <p className="preview-note">
            预览地址：<code>/research-overview-preview.html</code>
            {" · "}
            设计验收用，不依赖后端
            {" · "}
            场景切换不影响生产路由
          </p>
        </main>
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
      <ResearchOverviewPreviewApp />
    </StrictMode>,
  );
}
