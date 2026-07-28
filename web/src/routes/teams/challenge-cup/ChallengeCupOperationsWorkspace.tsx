import { Fragment, type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { VNativeButton, VStatusChip, type VStatusTone } from "../../../components/vui";
import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTask,
} from "../../../api/types";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import { ResearchProjectAgentTaskPanel } from "./ResearchProjectAgentTaskPanel";
import css from "./ChallengeCupOperationsWorkspace.module.css";

type ChallengeProgramProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;
type WorkspaceTab = "overview" | "questions" | "evidence" | "agents";
type PlatformStage = "knowledge_collection" | "experiment" | "iteration";

export type ChallengeCupProjectSwitcherContext = {
  activeStage: PlatformStage;
  statusLabel: string;
  statusTone: "neutral" | "active" | "ready" | "warning";
  primaryActionHref: string;
  primaryActionLabel: string;
};

export type ChallengeCupWorkspaceAgent = {
  agentId: string;
  name: string;
  code: string;
  role: string;
  workspace: string;
  model: string;
  status: string;
  tone: "ready" | "warning" | "blocked";
  configHref: string;
};

export type ChallengeCupOperationsWorkspaceProps = {
  projection?: ChallengeProgramProjection;
  agents: ChallengeCupWorkspaceAgent[];
  graphHref: string;
  projectSwitcher?: ReactNode | ((context: ChallengeCupProjectSwitcherContext) => ReactNode);
  researchTopic?: string;
  surface?: "workspace" | "progress";
  stageHrefs?: Partial<Record<PlatformStage, string>>;
  questionHref: (questionId: string) => string;
  activeResearchProjectId?: string;
  researchProjectAgentTasks?: TeamResearchProjectAgentTask[];
  researchProjectAgentTasksLoading?: boolean;
  researchProjectAgentTaskStarting?: boolean;
  researchProjectAgentTaskStartingKind?: ResearchProjectAgentTaskKind | null;
  researchProjectAgentTaskError?: string;
  onStartResearchProjectAgentTask?: (
    taskKind: ResearchProjectAgentTaskKind,
    options?: { formalRetry?: boolean; retryTaskId?: string },
  ) => Promise<void>;
  onOpenResearchProjectAgentTask?: (task: TeamResearchProjectAgentTask) => void;
  isLoading: boolean;
  isUnavailable: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
};

type QuestionRow = {
  id: string;
  kind: "黄金样例" | "试运行题";
  machinePassed: boolean;
  humanApproved: boolean;
  humanStatus: "approved" | "pending" | "revision_requested" | "rejected";
};

function cx(...tokens: Array<string | false | null | undefined>) {
  return tokens
    .filter((token): token is string => Boolean(token))
    .map((token) => css[token] || token)
    .join(" ");
}

function vuiStatusTone(tone: ChallengeCupProjectSwitcherContext["statusTone"]): VStatusTone {
  if (tone === "active") return "accent";
  if (tone === "ready") return "success";
  if (tone === "warning") return "warning";
  return "neutral";
}

function CheckMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m6 12 4 4 8-9" />
    </svg>
  );
}

function ArrowMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

function GraphMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="6" cy="12" r="2.4" />
      <circle cx="18" cy="6" r="2.4" />
      <circle cx="18" cy="18" r="2.4" />
      <path d="M8.2 11l7.4-4M8.2 13l7.4 4" />
    </svg>
  );
}

function tabLabel(tab: WorkspaceTab) {
  return {
    overview: "总览",
    questions: "题目与结果",
    evidence: "证据链",
    agents: "Agent 团队",
  }[tab];
}

const PLATFORM_STAGE_META: Record<PlatformStage, { index: string; label: string; shortLabel: string }> = {
  knowledge_collection: { index: "01", label: "知识搜集", shortLabel: "资料与证据" },
  experiment: { index: "02", label: "实验设计", shortLabel: "假设与方案" },
  iteration: { index: "03", label: "执行与迭代", shortLabel: "运行与结论" },
};

export function ChallengeCupOperationsWorkspace({
  projection,
  agents,
  graphHref,
  projectSwitcher,
  researchTopic = "",
  surface = "progress",
  stageHrefs = {},
  questionHref,
  activeResearchProjectId = "",
  researchProjectAgentTasks = [],
  researchProjectAgentTasksLoading = false,
  researchProjectAgentTaskStarting = false,
  researchProjectAgentTaskStartingKind = null,
  researchProjectAgentTaskError = "",
  onStartResearchProjectAgentTask = async () => undefined,
  onOpenResearchProjectAgentTask,
  isLoading,
  isUnavailable,
  isRefreshing,
  onRefresh,
}: ChallengeCupOperationsWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("overview");
  const [activeStage, setActiveStage] = useState<PlatformStage>("knowledge_collection");
  const stage1 = projection?.stage1ComplianceReadiness;
  const stage2 = projection?.stage2BatchGovernance;
  const stage3 = projection?.stage3DeepResearchDelivery;
  const goldenId = stage1?.mvpManifest.goldenSampleQuestionId || stage1?.singleQuestionSample.questionId || "SCI-096";
  const trialIds = stage1?.mvpManifest.trialQuestionIds ?? stage1?.mvpManifest.testQuestionIds ?? [];
  const questionIds = [goldenId, ...trialIds].filter(Boolean);
  const machineCompleted = stage1?.mvpManifest.completedQuestionCount ?? 0;
  const machineRequired = stage1?.mvpManifest.requiredQuestionCount ?? 4;
  const humanReview = stage1?.humanReview;
  const humanApproved = humanReview?.approvedQuestionCount
    ?? stage1?.trialRun.outcomeCounts.approved
    ?? (stage1?.acceptance.allFourHumanGatesApproved ? machineRequired : 0);
  const reviewRequired = humanReview?.pendingQuestionIds.length
    ?? stage1?.trialRun.outcomeCounts.review_required
    ?? Math.max(0, machineRequired - humanApproved);
  const revisionRequired = (
    humanReview?.revisionRequiredQuestionIds.length
    ?? stage1?.trialRun.outcomeCounts.needs_revision
    ?? 0
  ) + (
    humanReview?.rejectedQuestionIds.length
    ?? stage1?.trialRun.outcomeCounts.rejected
    ?? 0
  );
  const humanOutstanding = reviewRequired + revisionRequired;
  const officialCallCount = stage1?.officialModelCallEvidence.count ?? 0;
  const modelLabel = stage1?.dashscopeQwenProvider.modelRefs[0]?.split("/").at(-1) || "Qwen";
  const goldenApproved = humanReview
    ? humanReview.approvedQuestionIds.includes(goldenId)
    : (stage1?.trialRun.outcomeCounts.approved ?? 0) > 0;
  const approvedTrialCount = humanReview
    ? humanReview.approvedQuestionIds.filter((questionId) => questionId !== goldenId).length
    : Math.max(0, humanApproved - (goldenApproved ? 1 : 0));
  const questions = useMemo<QuestionRow[]>(
    () => questionIds.map((id, index) => {
      const humanStatus: QuestionRow["humanStatus"] = humanReview?.rejectedQuestionIds.includes(id)
        ? "rejected"
        : humanReview?.revisionRequiredQuestionIds.includes(id)
          ? "revision_requested"
          : humanReview?.pendingQuestionIds.includes(id)
            ? "pending"
            : humanReview?.approvedQuestionIds.includes(id)
              ? "approved"
            : (index === 0 ? goldenApproved : index <= approvedTrialCount)
              ? "approved"
              : "pending";
      return {
        id,
        kind: index === 0 ? "黄金样例" : "试运行题",
        machinePassed: index === 0
          ? Boolean(stage1?.singleQuestionSample.completed)
          : Boolean(stage1?.trialRun.completedQuestionIds.includes(id)),
        humanApproved: humanStatus === "approved",
        humanStatus,
      };
    }),
    [
      approvedTrialCount,
      goldenApproved,
      humanReview,
      questionIds.join("|"),
      stage1?.singleQuestionSample.completed,
      stage1?.trialRun.completedQuestionIds,
    ],
  );
  const pendingQuestions = questions.filter((question) => question.machinePassed && !question.humanApproved);
  const humanStatusLabel = (status: QuestionRow["humanStatus"]) => {
    if (status === "approved") return "已批准";
    if (status === "revision_requested") return "需修订";
    if (status === "rejected") return "已拒绝";
    return "待抽检";
  };
  const schemaGate = Boolean(stage1?.acceptance.schemaValidation);
  const citationGate = Boolean(stage1?.acceptance.citationValidation);
  const dimensionsGate = Boolean(stage1?.acceptance.allSevenDimensionsReviewed);
  const humanGate = humanReview?.allQuestionsApproved
    ?? (humanOutstanding === 0 && humanApproved >= machineRequired);
  const completeGateCount = [schemaGate, citationGate, dimensionsGate, humanGate].filter(Boolean).length;
  const humanPercent = machineRequired > 0 ? Math.round((humanApproved / machineRequired) * 100) : 0;
  const readyAgentCount = agents.filter((agent) => agent.tone === "ready").length;
  const programTitle = (
    projection?.program.title || "面向前沿科学问题的 AI 假设生成与研究计划设计平台"
  ).replace("的AI", "的 AI");
  const programId = projection?.program.officialProblemId || "XH-202619";
  const programTrack = projection?.program.track || "赛道一 / 方向一 / A 科学假设生成与研究计划设计";
  const currentGate = revisionRequired > 0
    ? "等待修订"
    : reviewRequired > 0
      ? "等待人工验收"
      : machineCompleted >= machineRequired
        ? "MVP 验收完成"
        : "等待机器验证";
  const isReady = machineCompleted >= machineRequired && humanGate;
  const activeStageHref = stageHrefs[activeStage] || graphHref;
  const resolveQuestionHref = (questionId: string) => questionHref(questionId);

  const stageState = (stage: PlatformStage) => {
    if (!stage1) {
      return { label: "读取中", tone: "neutral" as const, count: "—" };
    }
    if (stage === "knowledge_collection") {
      const blocked = stage1.blockers.length > 0;
      return {
        label: blocked ? "阻塞" : machineCompleted > 0 ? "进行中" : "未开始",
        tone: blocked ? "warning" as const : machineCompleted > 0 ? "active" as const : "neutral" as const,
        count: `${Math.min(machineCompleted, machineRequired)} / ${machineRequired}`,
      };
    }
    if (stage === "experiment") {
      const designReady = stage1.acceptance.researchPlanPresent && stage1.acceptance.feedbackRevisionCount > 0;
      return {
        label: designReady ? "已有设计" : "待设计",
        tone: designReady ? "ready" as const : "neutral" as const,
        count: designReady ? "1 / 1" : "0 / 1",
      };
    }
    const caseCount = stage3?.representativeCaseCount ?? 0;
    return {
      label: caseCount > 0 ? "迭代中" : "待执行",
      tone: caseCount > 0 ? "active" as const : "neutral" as const,
      count: `${caseCount} / ${stage3?.requiredRepresentativeCaseCount ?? 3}`,
    };
  };

  const selectTab = (tab: WorkspaceTab) => {
    setActiveTab(tab);
    window.requestAnimationFrame(() => {
      document.getElementById(`challenge-workspace-${tab}`)?.focus({ preventScroll: true });
    });
  };

  const activeStageState = stageState(activeStage);
  const projectSwitcherContext: ChallengeCupProjectSwitcherContext = {
    activeStage,
    statusLabel: activeStageState.label,
    statusTone: activeStageState.tone,
    primaryActionHref: activeStageHref,
    primaryActionLabel: activeStage === "knowledge_collection"
      ? "继续知识搜集"
      : activeStage === "experiment"
        ? "继续实验设计"
        : "继续执行与迭代",
  };
  const renderedProjectSwitcher = typeof projectSwitcher === "function"
    ? projectSwitcher(projectSwitcherContext)
    : projectSwitcher;
  const stageObjects = activeStage === "knowledge_collection"
    ? questions.slice(0, 3).map((question) => ({
        id: question.id,
        title: question.id,
        summary: `${question.kind} · ${question.machinePassed ? humanStatusLabel(question.humanStatus) : "待机器验证"}`,
        tone: question.humanApproved ? "ready" : question.machinePassed ? "active" : "neutral",
        href: resolveQuestionHref(question.id),
      }))
    : activeStage === "experiment"
      ? [{
          id: "experiment-design",
          title: researchTopic.trim() || "当前实验设计",
          summary: stage1?.acceptance.researchPlanPresent
            ? `研究计划已登记 · revision ${Math.max(1, stage1.acceptance.feedbackRevisionCount)}`
            : "等待生成可执行研究计划",
          tone: stage1?.acceptance.researchPlanPresent ? "ready" : "neutral",
          href: activeStageHref,
        }]
      : (stage3?.caseRecords ?? []).slice(0, 3).map((record) => ({
          id: record.caseId,
          title: record.title,
          summary: `${record.internalStatus} · ${record.bestValidatedResultId || "暂无最佳结果"}`,
          tone: record.bestValidatedResultId ? "active" : "neutral",
          href: activeStageHref,
        }));

  if (surface === "workspace") {
    return (
      <section className={cx("workspace", "platform-workspace")} aria-label="通用科研工作台" data-testid="challenge-cup-platform-workspace">
        <main className={cx("platform-frame")}>
          {!renderedProjectSwitcher ? <header className={cx("platform-project-header")}>
            <div className={cx("platform-project-identity")}>
              <span>研究计划</span>
              <div>
                <h1>{programTitle}</h1>
                <VStatusChip className={cx("status-pill")} tone={vuiStatusTone(stageState(activeStage).tone)}>
                  {stageState(activeStage).label}
                </VStatusChip>
                <span className={cx("autosave-label")}>{isLoading ? "同步中" : projection ? "投影已同步" : "投影不可用"}</span>
              </div>
              <p>研究主题：{researchTopic.trim() || programTitle}</p>
            </div>
            <div className={cx("platform-project-actions")}>
              <span>项目操作</span>
              <Link className={cx("button", "secondary")} to={graphHref}>
                <GraphMark />
                研究关系图
              </Link>
              <VNativeButton className={cx("button", "secondary")} type="button" onClick={onRefresh} disabled={isRefreshing}>
                {isRefreshing ? "刷新中" : "刷新状态"}
              </VNativeButton>
            </div>
          </header> : null}

          {isLoading ? (
            <section className={cx("platform-state")} aria-live="polite" data-testid="challenge-cup-platform-loading">
              <div className={cx("skeleton", "w-60")} />
              <div className={cx("skeleton-panel")} />
            </section>
          ) : isUnavailable || !projection || !stage1 ? (
            <section className={cx("platform-state", "error-state")} role="alert" data-testid="challenge-cup-platform-unavailable">
              <div className={cx("error-icon")} aria-hidden="true">!</div>
              <div>
                <strong>科研工作台数据暂不可用</strong>
                <p>页面不会回退到模拟数据。请重新读取真实 challengeProgramProjection。</p>
                <VNativeButton className={cx("button", "primary")} type="button" onClick={onRefresh} disabled={isRefreshing}>
                  {isRefreshing ? "重新读取中" : "重新读取"}
                </VNativeButton>
              </div>
            </section>
          ) : (
            <>
              {renderedProjectSwitcher ? <div className={cx("platform-project-switcher")}>{renderedProjectSwitcher}</div> : null}
              <div className={cx("platform-console")}>
                <nav className={cx("platform-stage-rail")} aria-label="科研三阶段">
                  {(Object.keys(PLATFORM_STAGE_META) as PlatformStage[]).map((stage, index, stages) => {
                    const meta = PLATFORM_STAGE_META[stage];
                    const state = stageState(stage);
                    const selected = activeStage === stage;
                    return (
                      <Fragment key={stage}>
                        <VNativeButton
                          className={cx("platform-stage-button", selected && "selected")}
                          type="button"
                          aria-current={selected ? "step" : undefined}
                          onClick={() => setActiveStage(stage)}
                        >
                          <span className={cx("stage-index")}>{meta.index}</span>
                          <span className={cx("stage-label")}>
                            <strong>{meta.label}</strong>
                            <small>{meta.shortLabel}</small>
                          </span>
                          <VStatusChip className={cx("stage-state")} tone={vuiStatusTone(state.tone)}>
                            {state.label}
                          </VStatusChip>
                          <strong className={cx("stage-count")}>{state.count}</strong>
                        </VNativeButton>
                        {index < stages.length - 1 ? <span className={cx("platform-stage-connector")} aria-hidden="true" /> : null}
                      </Fragment>
                    );
                  })}
                  <section className={cx("platform-stage-objects")} aria-label="当前阶段对象">
                    <header>
                      <span>当前对象 · {stageObjects.length}</span>
                    </header>
                    {stageObjects.length > 0 ? stageObjects.map((item, index) => (
                      <Link
                        className={cx("platform-stage-object", index === 0 && "selected")}
                        key={item.id}
                        to={item.href}
                      >
                        <span><i className={cx(item.tone)} />{item.title}</span>
                        <small>{item.summary}</small>
                      </Link>
                    )) : (
                      <p className={cx("platform-stage-object-empty")}>当前阶段尚无已登记对象</p>
                    )}
                  </section>
                </nav>

                <div className={cx("platform-grid")}>
                <section className={cx("platform-canvas")} aria-labelledby="platform-stage-title">
                  <header className={cx("platform-canvas-header")}>
                    <div>
                      <span>阶段 {PLATFORM_STAGE_META[activeStage].index} · 当前工作区</span>
                      <div>
                        <h2 id="platform-stage-title">{PLATFORM_STAGE_META[activeStage].label}</h2>
                        <VStatusChip className={cx("status-pill")} tone={vuiStatusTone(stageState(activeStage).tone)}>
                          {stageState(activeStage).label}
                        </VStatusChip>
                      </div>
                    </div>
                    <div className={cx("platform-canvas-actions")}>
                      <Link className={cx("button", "secondary")} to={activeStageHref}>查看阶段详情</Link>
                    </div>
                  </header>

                  {activeStage === "knowledge_collection" ? (
                    <div className={cx("platform-stage-content")}>
                      <div className={cx("platform-substage-rail")} aria-label="知识搜集子阶段">
                        {[
                          ["资料发现", machineCompleted > 0],
                          ["内容提炼", officialCallCount > 0],
                          ["关系整理", citationGate],
                          ["入库审核", humanGate],
                        ].map(([label, done], index) => (
                          <div className={cx("platform-substage", Boolean(done) && "complete")} key={String(label)}>
                            <span>{done ? <CheckMark /> : index + 1}</span>
                            <strong>{label}</strong>
                          </div>
                        ))}
                      </div>

                      <div className={cx("platform-metrics")}>
                        <article><span>题目记录</span><strong>{machineCompleted}</strong></article>
                        <article><span>模型调用证据</span><strong>{officialCallCount}</strong></article>
                        <article><span>人工待处理</span><strong>{humanOutstanding}</strong></article>
                        <article><span>团队成员</span><strong>{readyAgentCount} / {agents.length}</strong></article>
                      </div>

                      <section className={cx("platform-task-card")}>
                        <div>
                          <span>本轮任务</span>
                          <h3>{researchTopic.trim() || programTitle}</h3>
                          <div className={cx("topic-tags")}>
                            {stage1.independentEvaluationDimensions.slice(0, 3).map((dimension) => (
                              <span key={dimension}>{dimension}</span>
                            ))}
                          </div>
                        </div>
                        <dl>
                          <div><dt>当前批次</dt><dd>{stage1.mvpManifest.goldenSampleQuestionId || "未登记"}</dd></div>
                          <div><dt>最近更新</dt><dd>{stage1.acceptance.feedbackRevisionCount} 次反馈修订</dd></div>
                          <div><dt>阶段判断</dt><dd>{humanGate ? "证据与人工门禁已闭环" : revisionRequired > 0 ? "人工审核已退回，等待修订" : "资料已找到，等待人工验收"}</dd></div>
                        </dl>
                      </section>

                      <section className={cx("platform-data-surface")} aria-labelledby="platform-source-title">
                        <header>
                          <div><span>资料工作表</span><h3 id="platform-source-title">题目、证据与审核队列</h3></div>
                          <div className={cx("dataset-tabs")} aria-label="资料视图">
                            <span className={cx("selected")}>资料 {questions.length}</span>
                            <span>Claim Map 0</span>
                            <span>审核队列 {pendingQuestions.length}</span>
                          </div>
                        </header>
                        <div className={cx("table-wrap", "platform-table")}>
                          <table>
                            <thead><tr><th>对象</th><th>类型</th><th>机器验证</th><th>人工审核</th><th>证据</th></tr></thead>
                            <tbody>
                              {questions.map((question) => (
                                <tr key={question.id}>
                                  <td>
                                    <Link className={cx("text-button")} to={resolveQuestionHref(question.id)}>
                                      {question.id}
                                    </Link>
                                    <span>{question.kind}</span>
                                  </td>
                                  <td>{modelLabel}</td>
                                  <td>
                                    <VStatusChip className={cx("status-icon")} tone={question.machinePassed ? "success" : "warning"}>
                                      {question.machinePassed ? "通过" : "待验证"}
                                    </VStatusChip>
                                  </td>
                                  <td>
                                    <VStatusChip className={cx("status-icon")} tone={question.humanApproved ? "success" : "warning"}>
                                      {humanStatusLabel(question.humanStatus)}
                                    </VStatusChip>
                                  </td>
                                  <td>{question.machinePassed ? "可追溯" : "待生成"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <p className={cx("data-footnote")}>当前投影未提供正式 Claim Map 时保持为 0，不使用预览占位数据冒充真实研究结论。</p>
                      </section>
                    </div>
                  ) : activeStage === "experiment" ? (
                    <div className={cx("platform-stage-content", "platform-design-content")}>
                      <section className={cx("design-summary")}>
                        <header><span>Experiment Design</span><h3>冻结前的研究设计与治理检查</h3></header>
                        <div className={cx("design-grid")}>
                          <article><span>研究计划</span><strong>{stage1.acceptance.researchPlanPresent ? "已生成" : "待生成"}</strong><p>研究问题、假设与可执行协议来自正式投影。</p></article>
                          <article><span>反馈修订</span><strong>v{Math.max(1, stage1.acceptance.feedbackRevisionCount)}</strong><p>仅展示已登记的修订次数，不推断不存在的版本。</p></article>
                          <article><span>批处理治理</span><strong>{stage2?.completedQuestionCount ?? 0} / {stage2?.questionCount ?? 125}</strong><p>{stage2?.status || "未返回状态"}</p></article>
                          <article><span>账本门禁</span><strong>{stage2?.ledger.initialized ? "已初始化" : "待初始化"}</strong><p>Manifest、引用审计和失败记录保持独立。</p></article>
                        </div>
                      </section>
                      <ResearchProjectAgentTaskPanel
                        stage="experiment"
                        activeProjectId={activeResearchProjectId}
                        tasks={researchProjectAgentTasks}
                        isLoading={researchProjectAgentTasksLoading}
                        isStarting={researchProjectAgentTaskStarting}
                        startingTaskKind={researchProjectAgentTaskStartingKind}
                        errorMessage={researchProjectAgentTaskError}
                        onStartTask={onStartResearchProjectAgentTask}
                        onOpenTask={onOpenResearchProjectAgentTask}
                      />
                      <section className={cx("platform-empty-state")}>
                        <strong>当前 DTO 未返回冻结 Experiment Design 明细</strong>
                        <p>生产页面保留清晰空态；进入阶段详情后继续使用现有实验规划链路。</p>
                        <Link className={cx("button", "primary")} to={activeStageHref}>进入实验设计</Link>
                      </section>
                    </div>
                  ) : (
                    <div className={cx("platform-stage-content", "platform-run-content")}>
                      <section className={cx("run-summary")}>
                        <header><span>Run history</span><h3>代表性深研案例与版本链</h3></header>
                        <div className={cx("run-list")}>
                          {(stage3?.caseRecords.length ? stage3.caseRecords : []).map((record) => (
                            <article key={record.caseId}>
                              <div><strong>{record.title}</strong><span>{record.caseId}</span></div>
                              <dl>
                                <div><dt>内部状态</dt><dd>{record.internalStatus}</dd></div>
                                <div><dt>最佳结果</dt><dd>{record.bestValidatedResultId || "未登记"}</dd></div>
                                <div><dt>项目状态</dt><dd>{record.projectCompletionStatus}</dd></div>
                              </dl>
                              <p>{record.claimBoundary}</p>
                            </article>
                          ))}
                        </div>
                        {!stage3?.caseRecords.length ? <div className={cx("platform-empty-state")}>尚无已登记的代表性深研案例。</div> : null}
                      </section>
                      <ResearchProjectAgentTaskPanel
                        stage="iteration"
                        activeProjectId={activeResearchProjectId}
                        tasks={researchProjectAgentTasks}
                        isLoading={researchProjectAgentTasksLoading}
                        isStarting={researchProjectAgentTaskStarting}
                        startingTaskKind={researchProjectAgentTaskStartingKind}
                        errorMessage={researchProjectAgentTaskError}
                        onStartTask={onStartResearchProjectAgentTask}
                        onOpenTask={onOpenResearchProjectAgentTask}
                      />
                    </div>
                  )}
                </section>

                <aside className={cx("platform-inspector")} aria-label="阶段检查器">
                  <section>
                    <span>当前对象</span>
                    <h2>{PLATFORM_STAGE_META[activeStage].label}</h2>
                    <p>{activeStage === "knowledge_collection"
                      ? "从真实题目、模型调用证据与人工门禁判断资料是否足以进入设计。"
                      : activeStage === "experiment"
                        ? "冻结可执行设计；没有 DTO 明细时不会伪造实验参数。"
                        : "按版本检查运行结果、适用边界和下一轮受控修改。"}</p>
                  </section>
                  <section>
                    <span>下一步</span>
                    <strong>{activeStage === "knowledge_collection"
                      ? revisionRequired > 0
                        ? `修订 ${revisionRequired} 项审核问题`
                        : reviewRequired > 0
                          ? `完成 ${reviewRequired} 项人工审核`
                          : "进入实验设计"
                      : activeStage === "experiment"
                        ? "补齐并冻结设计"
                        : "审查最佳版本与边界"}</strong>
                    <Link className={cx("button", "primary")} to={activeStageHref}>进入工作区</Link>
                  </section>
                  <section>
                    <span>Agent 团队</span>
                    <strong>{readyAgentCount} / {agents.length} 可用</strong>
                    <div className={cx("inspector-agent-list")}>
                      {agents.slice(0, 4).map((agent) => <span key={agent.agentId}>{agent.name} · {agent.role}</span>)}
                    </div>
                  </section>
                </aside>
                </div>
              </div>
            </>
          )}
        </main>
      </section>
    );
  }

  return (
    <section className={cx("workspace")} aria-label="挑战杯科研任务操作台" data-testid="challenge-cup-operations-workspace">
      <main className={cx("page-frame")}>
        <div className={cx("breadcrumbs")} aria-label="面包屑">
          <span>团队</span>
          <span aria-hidden="true">/</span>
          <strong>挑战杯 AI 科研团队</strong>
        </div>

        <section className={cx("program-header")} aria-labelledby="challenge-program-title">
          <div className={cx("program-identity")}>
            <div className={cx("program-kicker")}>
              <span className={cx("id-chip")}>{programId}</span>
              <span>{programTrack}</span>
            </div>
            <h1 id="challenge-program-title">{programTitle}</h1>
            <p>当前 MVP 聚焦“1 个黄金样例 + 3 个试运行题（共 4 题）”，后续规模化任务保持明确延后。</p>
          </div>
          <div className={cx("program-actions")}>
            <Link className={cx("button", "secondary")} to={graphHref}>
              <GraphMark />
              研究关系图
            </Link>
            <VNativeButton className={cx("button", "primary")} type="button" onClick={() => selectTab("questions")}>
              {revisionRequired > 0 ? `修订 ${revisionRequired} 个退回题` : `审核 ${reviewRequired} 个待抽检题`}
              <ArrowMark />
            </VNativeButton>
          </div>
        </section>

        <nav className={cx("section-tabs")} aria-label="挑战杯工作区">
          {(["overview", "questions", "evidence", "agents"] as WorkspaceTab[]).map((tab) => (
            <VNativeButton
              key={tab}
              id={`challenge-tab-${tab}`}
              className={cx("tab", activeTab === tab && "active")}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              aria-controls={`challenge-workspace-${tab}`}
              onClick={() => selectTab(tab)}
            >
              {tabLabel(tab)}
              {tab === "questions" ? <span className={cx("tab-count")}>{questionIds.length}</span> : null}
              {tab === "agents" ? <span className={cx("tab-count")}>{agents.length}</span> : null}
            </VNativeButton>
          ))}
        </nav>

        {isLoading ? (
          <section className={cx("scene", "state-scene")} aria-live="polite" data-testid="challenge-cup-loading">
            <div className={cx("loading-header")}>
              <div className={cx("skeleton", "w-24")} />
              <div className={cx("skeleton", "w-60")} />
              <div className={cx("skeleton", "w-44")} />
            </div>
            <div className={cx("loading-stats")}>
              {Array.from({ length: 4 }, (_, index) => <div className={cx("skeleton-block")} key={index} />)}
            </div>
            <div className={cx("loading-body")}>
              <div className={cx("skeleton-panel")} />
              <div className={cx("skeleton-panel", "short")} />
            </div>
            <p>正在读取挑战杯 MVP 状态。固定题名和页面结构保持不变，不回退到旧科研流程。</p>
          </section>
        ) : isUnavailable || !projection || !stage1 ? (
          <section className={cx("scene", "state-scene", "error-state")} role="alert" data-testid="challenge-cup-unavailable">
            <div className={cx("error-icon")} aria-hidden="true">!</div>
            <div>
              <span className={cx("eyebrow")}>挑战杯状态暂不可用</span>
              <h2>无法读取 MVP 投影</h2>
              <p>当前不展示旧科研流程，也不会提供可能产生错误写入的操作。团队和赛题身份仍保持可见。</p>
              <VNativeButton className={cx("button", "primary")} type="button" onClick={onRefresh} disabled={isRefreshing}>
                {isRefreshing ? "重新读取中" : "重新读取"}
              </VNativeButton>
            </div>
          </section>
        ) : (
          <div className={cx("scene")}>
            <section
              id="challenge-workspace-overview"
              className={cx("tab-panel", activeTab === "overview" && "active")}
              role="tabpanel"
              tabIndex={-1}
              aria-labelledby="challenge-tab-overview"
            >
              <h2 className={cx("sr-only")}>挑战杯 MVP 总览</h2>
              <div className={cx("status-strip")} aria-label="MVP 核心状态">
                <article>
                  <span className={cx("stat-label")}>机器验证</span>
                  <strong>{machineCompleted} / {machineRequired}</strong>
                  <span className={cx("stat-note", machineCompleted >= machineRequired && "success-text")}>
                    {machineCompleted >= machineRequired ? "全部通过" : "尚未完成"}
                  </span>
                </article>
                <article>
                  <span className={cx("stat-label")}>人工审核</span>
                  <strong>{humanApproved} / {machineRequired}</strong>
                  <span className={cx("stat-note", humanOutstanding > 0 ? "warning-text" : "success-text")}>
                    {revisionRequired > 0
                      ? `${revisionRequired} 题需修订`
                      : reviewRequired > 0
                        ? `${reviewRequired} 题待抽检`
                        : "全部通过"}
                  </span>
                </article>
                <article>
                  <span className={cx("stat-label")}>模型调用证据</span>
                  <strong>{officialCallCount}</strong>
                  <span className={cx("stat-note")}>可追溯记录</span>
                </article>
                <article>
                  <span className={cx("stat-label")}>当前门禁</span>
                  <strong className={cx("status-heading")}>{currentGate}</strong>
                  <span className={cx("stat-note", isReady ? "success-text" : "warning-text")}>
                    {isReady ? "当前 MVP 已完成" : "尚未完成 MVP"}
                  </span>
                </article>
              </div>

              <div className={cx("overview-grid")}>
                <section className={cx("surface", "progress-surface")} aria-labelledby="challenge-progress-title">
                  <header className={cx("surface-header")}>
                    <div>
                      <span className={cx("eyebrow")}>MVP 进度</span>
                      <h2 id="challenge-progress-title">{machineRequired} 个问题的验证与审核轨迹</h2>
                    </div>
                    <VStatusChip className={cx("badge")} tone={humanGate ? "success" : "warning"}>
                      人工验收 {humanPercent}%
                    </VStatusChip>
                  </header>

                  <div className={cx("progress-rail")}>
                    {questions.map((question, index) => (
                      <article className={cx("progress-step", question.humanApproved ? "complete" : "pending")} key={question.id}>
                        <div className={cx("step-marker")} aria-hidden="true">
                          {question.humanApproved ? <CheckMark /> : index + 1}
                        </div>
                        <div>
                          <strong>{question.id}</strong>
                          <span>{question.kind}</span>
                          <small>
                            {question.machinePassed ? "机器通过" : "机器待验证"} · {humanStatusLabel(question.humanStatus)}
                          </small>
                        </div>
                      </article>
                    ))}
                  </div>

                  <div className={cx("table-wrap", "compact-table")}>
                    <table>
                      <thead>
                        <tr><th>题目</th><th>模型</th><th>Schema</th><th>证据</th><th>人工审核</th><th><span className={cx("sr-only")}>操作</span></th></tr>
                      </thead>
                      <tbody>
                        {questions.map((question) => (
                          <tr key={question.id}>
                            <td><strong>{question.id}</strong><span>{question.kind}</span></td>
                            <td>{modelLabel}</td>
                            <td>
                              <VStatusChip className={cx("status-icon")} tone={question.machinePassed ? "success" : "warning"}>
                                {question.machinePassed ? "通过" : "待验证"}
                              </VStatusChip>
                            </td>
                            <td>{question.machinePassed ? "已追溯" : "待生成"}</td>
                            <td>
                              <VStatusChip className={cx("status-icon")} tone={question.humanApproved ? "success" : "warning"}>
                                {humanStatusLabel(question.humanStatus)}
                              </VStatusChip>
                            </td>
                            <td>
                              <Link className={cx("text-button")} to={resolveQuestionHref(question.id)}>
                                {question.humanApproved ? "查看" : "审核"}
                              </Link>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>

                <aside className={cx("side-stack")}>
                  <section className={cx("surface", "next-action")} aria-labelledby="challenge-next-action-title">
                    <span className={cx("eyebrow")}>下一步</span>
                    <h2 id="challenge-next-action-title">
                      {revisionRequired > 0
                        ? `修订 ${revisionRequired} 题证据与计划`
                        : reviewRequired > 0
                          ? `完成 ${reviewRequired} 题人工抽检`
                          : "准备 MVP 验收记录"}
                    </h2>
                    <p>
                      {revisionRequired > 0
                        ? "人工审核已发现来源或研究设计问题；机器验证记录保留，但不得计为 MVP 人工通过。"
                        : reviewRequired > 0
                          ? "机器验证已完成，但尚不能把试运行题计为人工验收通过。"
                          : "机器验证与人工审核均已完成，可进入 MVP 验收记录。"}
                    </p>
                    <div className={cx("action-meta")}><span>预计操作</span><strong>{revisionRequired > 0 ? `逐题修订 · ${revisionRequired} 项` : `逐题审查 · ${reviewRequired} 项`}</strong></div>
                    <VNativeButton className={cx("button", "primary", "full")} type="button" onClick={() => selectTab("questions")}>进入人工审核</VNativeButton>
                  </section>

                  <section className={cx("surface", "gate-summary")} aria-labelledby="challenge-gate-title">
                    <header className={cx("surface-header", "compact")}>
                      <div><span className={cx("eyebrow")}>验收门禁</span><h2 id="challenge-gate-title">完成条件</h2></div>
                      <VStatusChip className={cx("badge")} tone="neutral">{completeGateCount} / 4</VStatusChip>
                    </header>
                    <ul className={cx("check-list")}>
                      <li className={cx(schemaGate && "done")}><span />结构化输出符合 Schema</li>
                      <li className={cx(citationGate && "done")}><span />来源与证据锚点完整</li>
                      <li className={cx(dimensionsGate && "done")}><span />七维独立评估已记录</li>
                      <li className={cx(humanGate && "done")}><span />{humanGate ? "人工抽检全部完成" : revisionRequired > 0 ? `${revisionRequired} 题需修订` : `${reviewRequired} 题人工抽检待完成`}</li>
                    </ul>
                  </section>
                </aside>
              </div>

              <details className={cx("roadmap")}>
                <summary>
                  <div><span className={cx("eyebrow")}>MVP 后续范围</span><strong>125 题批处理与 3 个代表性深研案例</strong></div>
                  <VStatusChip className={cx("badge")} tone="neutral">当前延后</VStatusChip>
                </summary>
                <div className={cx("roadmap-grid")}>
                  <article><span>规模化批处理</span><strong>{stage2?.completedQuestionCount ?? 0} / {stage2?.questionCount ?? 125}</strong><p>待 MVP 人工验收完成后再启动，不计入当前完成条件。</p></article>
                  <article><span>代表性深研</span><strong>{stage3?.representativeCaseCount ?? 0} / {stage3?.requiredRepresentativeCaseCount ?? 3}</strong><p>FashionMNIST 仅为工程案例，内部撰写审查不代表项目第三阶段完成。</p></article>
                  <article><span>参赛封装</span><strong>未启动</strong><p>结果包、引用包、复现包和演示材料将在规模化验证后准备。</p></article>
                </div>
              </details>
            </section>

            <section
              id="challenge-workspace-questions"
              className={cx("tab-panel", activeTab === "questions" && "active")}
              role="tabpanel"
              tabIndex={-1}
            >
              <header className={cx("panel-heading")}>
                <div><span className={cx("eyebrow")}>题目与结果</span><h2>人工抽检队列</h2><p>机器结果与人工决定分开记录，任何待审项都不会被计为正式通过。</p></div>
                <div className={cx("panel-actions")}>
                  <VStatusChip className={cx("badge")} tone={humanOutstanding > 0 ? "warning" : "success"}>
                    {humanOutstanding} 个待处理结果
                  </VStatusChip>
                </div>
              </header>
              <div className={cx("question-review-list")}>
                {(pendingQuestions.length ? pendingQuestions : questions).map((question) => (
                  <article className={cx("review-row")} key={question.id}>
                    <div className={cx("review-id")}><strong>{question.id}</strong><span>{question.kind}</span></div>
                    <div><span>机器验证</span><strong className={cx(question.machinePassed ? "success-text" : "warning-text")}>{question.machinePassed ? "通过" : "待验证"}</strong></div>
                    <div><span>证据状态</span><strong>{question.machinePassed ? "可追溯" : "待生成"}</strong></div>
                    <div><span>假设输出</span><strong>≥ {stage1.acceptance.minimumHypothesisCount} 条</strong></div>
                    <div><span>人工状态</span><strong className={cx(question.humanApproved ? "success-text" : "warning-text")}>{humanStatusLabel(question.humanStatus)}</strong></div>
                    <Link
                      className={cx("button", "secondary")}
                      to={resolveQuestionHref(question.id)}
                      title="打开该题正式工件；审核写入仍由现有人工门禁流程负责"
                    >
                      {question.humanApproved ? "查看记录" : "开始审核"}
                    </Link>
                  </article>
                ))}
              </div>
            </section>

            <section
              id="challenge-workspace-evidence"
              className={cx("tab-panel", activeTab === "evidence" && "active")}
              role="tabpanel"
              tabIndex={-1}
            >
              <header className={cx("panel-heading")}>
                <div><span className={cx("eyebrow")}>证据链</span><h2>模型调用与来源追踪</h2><p>只显示可审计摘要；原始请求、密钥和完整提示词不会暴露在前端。</p></div>
              </header>
              <div className={cx("evidence-grid")}>
                <article className={cx("surface", "evidence-card")}><span>正式模型调用</span><strong>{officialCallCount} 条</strong><p>{modelLabel} provider · 调用 ID 与响应摘要可追踪</p></article>
                <article className={cx("surface", "evidence-card")}><span>问题结果</span><strong>{machineCompleted} 条</strong><p>每题保留输出摘要、状态和证据引用</p></article>
                <article className={cx("surface", "evidence-card")}><span>Schema 校验</span><strong>{machineCompleted} / {machineRequired}</strong><p>当前 MVP 输出结构校验状态</p></article>
              </div>
              <section className={cx("surface", "evidence-ledger")}>
                <header className={cx("surface-header", "compact")}><div><span className={cx("eyebrow")}>最近证据</span><h2>可审计事件</h2></div></header>
                <ol>
                  {questions.map((question) => (
                    <li key={question.id}>
                      <time>{humanStatusLabel(question.humanStatus)}</time>
                      <strong>{question.id} {question.machinePassed ? "Schema 与引用校验通过" : "等待机器验证"}</strong>
                      <span>{question.machinePassed ? "模型调用与输出摘要可追溯" : "尚无正式完成证据"}</span>
                    </li>
                  ))}
                </ol>
              </section>
            </section>

            <section
              id="challenge-workspace-agents"
              className={cx("tab-panel", activeTab === "agents" && "active")}
              role="tabpanel"
              tabIndex={-1}
            >
              <header className={cx("panel-heading")}>
                <div><span className={cx("eyebrow")}>Agent 团队</span><h2>{agents.length} 个角色按职责分组</h2><p>总览只保留团队健康摘要；模型、职责和入口在这里集中管理。</p></div>
                <VStatusChip className={cx("badge")} tone={readyAgentCount === agents.length ? "success" : "warning"}>
                  {readyAgentCount} / {agents.length} 可用
                </VStatusChip>
              </header>
              <div className={cx("agent-table")} role="table" aria-label="挑战杯 Agent 团队">
                <div className={cx("agent-row", "agent-head")} role="row">
                  <span role="columnheader">Agent</span><span role="columnheader">职责</span><span role="columnheader">所属工作区</span><span role="columnheader">模型</span><span role="columnheader">状态</span><span role="columnheader" />
                </div>
                {agents.map((agent) => (
                  <div className={cx("agent-row")} role="row" key={agent.agentId}>
                    <span className={cx("agent-person")}><i>{agent.name.slice(0, 1)}</i><b>{agent.name}</b><small>{agent.code}</small></span>
                    <span>{agent.role}</span><span>{agent.workspace}</span><span title={agent.model}>{agent.model}</span>
                    <VStatusChip className={cx("status-icon")} tone={agent.tone === "ready" ? "success" : "warning"}>
                      {agent.status}
                    </VStatusChip>
                    <Link className={cx("text-button")} to={agent.configHref}>配置</Link>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )}
      </main>
    </section>
  );
}
