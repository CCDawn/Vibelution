import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import css from "./ChallengeCupOperationsWorkspace.module.css";

type ChallengeProgramProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;
type WorkspaceTab = "overview" | "questions" | "evidence" | "agents";

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
  isLoading: boolean;
  isUnavailable: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
};

type QuestionRow = {
  id: string;
  kind: "完整样例" | "通用性测试";
  machinePassed: boolean;
  humanApproved: boolean;
};

function cx(...tokens: Array<string | false | null | undefined>) {
  return tokens
    .filter((token): token is string => Boolean(token))
    .map((token) => css[token] || token)
    .join(" ");
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

export function ChallengeCupOperationsWorkspace({
  projection,
  agents,
  graphHref,
  isLoading,
  isUnavailable,
  isRefreshing,
  onRefresh,
}: ChallengeCupOperationsWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("overview");
  const stage1 = projection?.stage1ComplianceReadiness;
  const stage2 = projection?.stage2BatchGovernance;
  const stage3 = projection?.stage3DeepResearchDelivery;
  const goldenId = stage1?.mvpManifest.goldenSampleQuestionId || stage1?.singleQuestionSample.questionId || "SCI-096";
  const testIds = stage1?.mvpManifest.testQuestionIds ?? [];
  const questionIds = [goldenId, ...testIds].filter(Boolean);
  const machineCompleted = stage1?.mvpManifest.completedQuestionCount ?? 0;
  const machineRequired = stage1?.mvpManifest.requiredQuestionCount ?? 4;
  const humanApproved = stage1?.trialRun.outcomeCounts.approved ?? (stage1?.acceptance.allFourHumanGatesApproved ? 1 : 0);
  const reviewRequired = stage1?.trialRun.outcomeCounts.review_required ?? Math.max(0, machineRequired - humanApproved);
  const officialCallCount = stage1?.officialModelCallEvidence.count ?? 0;
  const modelLabel = stage1?.dashscopeQwenProvider.modelRefs[0]?.split("/").at(-1) || "Qwen";
  const goldenApproved = Boolean(stage1?.acceptance.allFourHumanGatesApproved);
  const approvedTrialCount = Math.max(0, humanApproved - (goldenApproved ? 1 : 0));
  const questions = useMemo<QuestionRow[]>(
    () => questionIds.map((id, index) => ({
      id,
      kind: index === 0 ? "完整样例" : "通用性测试",
      machinePassed: index === 0
        ? Boolean(stage1?.singleQuestionSample.completed)
        : Boolean(stage1?.trialRun.completedQuestionIds.includes(id)),
      humanApproved: index === 0 ? goldenApproved : index <= approvedTrialCount,
    })),
    [
      approvedTrialCount,
      goldenApproved,
      questionIds.join("|"),
      stage1?.singleQuestionSample.completed,
      stage1?.trialRun.completedQuestionIds,
    ],
  );
  const pendingQuestions = questions.filter((question) => question.machinePassed && !question.humanApproved);
  const schemaGate = Boolean(stage1?.acceptance.schemaValidation);
  const citationGate = Boolean(stage1?.acceptance.citationValidation);
  const dimensionsGate = Boolean(stage1?.acceptance.allSevenDimensionsReviewed);
  const humanGate = reviewRequired === 0 && humanApproved >= machineRequired;
  const completeGateCount = [schemaGate, citationGate, dimensionsGate, humanGate].filter(Boolean).length;
  const humanPercent = machineRequired > 0 ? Math.round((humanApproved / machineRequired) * 100) : 0;
  const readyAgentCount = agents.filter((agent) => agent.tone === "ready").length;
  const programTitle = (
    projection?.program.title || "面向前沿科学问题的 AI 假设生成与研究计划设计平台"
  ).replace("的AI", "的 AI");
  const programId = projection?.program.officialProblemId || "XH-202619";
  const programTrack = projection?.program.track || "赛道一 / 方向一 / A 科学假设生成与研究计划设计";
  const currentGate = reviewRequired > 0 ? "等待人工验收" : machineCompleted >= machineRequired ? "MVP 验收完成" : "等待机器验证";
  const isReady = machineCompleted >= machineRequired && reviewRequired === 0;

  const selectTab = (tab: WorkspaceTab) => {
    setActiveTab(tab);
    window.requestAnimationFrame(() => {
      document.getElementById(`challenge-workspace-${tab}`)?.focus({ preventScroll: true });
    });
  };

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
            <p>当前 MVP 聚焦“1 个完整样例 + 3 个通用性测试”，后续规模化任务保持明确延后。</p>
          </div>
          <div className={cx("program-actions")}>
            <Link className={cx("button", "secondary")} to={graphHref}>
              <GraphMark />
              研究关系图
            </Link>
            <button className={cx("button", "primary")} type="button" onClick={() => selectTab("questions")}>
              审核 {reviewRequired} 个待抽检题
              <ArrowMark />
            </button>
          </div>
        </section>

        <nav className={cx("section-tabs")} aria-label="挑战杯工作区">
          {(["overview", "questions", "evidence", "agents"] as WorkspaceTab[]).map((tab) => (
            <button
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
            </button>
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
              <button className={cx("button", "primary")} type="button" onClick={onRefresh} disabled={isRefreshing}>
                {isRefreshing ? "重新读取中" : "重新读取"}
              </button>
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
                  <span className={cx("stat-note", reviewRequired > 0 ? "warning-text" : "success-text")}>
                    {reviewRequired > 0 ? `${reviewRequired} 题待抽检` : "全部通过"}
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
                    <span className={cx("badge", humanGate ? "success" : "warning")}>人工验收 {humanPercent}%</span>
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
                            {question.machinePassed ? "机器通过" : "机器待验证"} · {question.humanApproved ? "人工通过" : "待人工"}
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
                            <td><span className={cx("status-icon", question.machinePassed ? "success" : "warning")}>{question.machinePassed ? "通过" : "待验证"}</span></td>
                            <td>{question.machinePassed ? "已追溯" : "待生成"}</td>
                            <td><span className={cx("status-icon", question.humanApproved ? "success" : "warning")}>{question.humanApproved ? "已批准" : "待抽检"}</span></td>
                            <td><button className={cx("text-button")} type="button" onClick={() => selectTab("questions")}>{question.humanApproved ? "查看" : "审核"}</button></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>

                <aside className={cx("side-stack")}>
                  <section className={cx("surface", "next-action")} aria-labelledby="challenge-next-action-title">
                    <span className={cx("eyebrow")}>下一步</span>
                    <h2 id="challenge-next-action-title">{reviewRequired > 0 ? `完成 ${reviewRequired} 题人工抽检` : "准备 MVP 验收记录"}</h2>
                    <p>{reviewRequired > 0 ? "机器验证已完成，但尚不能把测试题计为人工验收通过。" : "机器验证与人工审核均已完成，可进入 MVP 验收记录。"}</p>
                    <div className={cx("action-meta")}><span>预计操作</span><strong>逐题审查 · {reviewRequired} 项</strong></div>
                    <button className={cx("button", "primary", "full")} type="button" onClick={() => selectTab("questions")}>进入人工审核</button>
                  </section>

                  <section className={cx("surface", "gate-summary")} aria-labelledby="challenge-gate-title">
                    <header className={cx("surface-header", "compact")}>
                      <div><span className={cx("eyebrow")}>验收门禁</span><h2 id="challenge-gate-title">完成条件</h2></div>
                      <span className={cx("badge", "neutral")}>{completeGateCount} / 4</span>
                    </header>
                    <ul className={cx("check-list")}>
                      <li className={cx(schemaGate && "done")}><span />结构化输出符合 Schema</li>
                      <li className={cx(citationGate && "done")}><span />来源与证据锚点完整</li>
                      <li className={cx(dimensionsGate && "done")}><span />七维独立评估已记录</li>
                      <li className={cx(humanGate && "done")}><span />{humanGate ? "人工抽检全部完成" : `${reviewRequired} 题人工抽检待完成`}</li>
                    </ul>
                  </section>
                </aside>
              </div>

              <details className={cx("roadmap")}>
                <summary>
                  <div><span className={cx("eyebrow")}>MVP 后续范围</span><strong>125 题批处理与 3 个代表性深研案例</strong></div>
                  <span className={cx("badge", "neutral")}>当前延后</span>
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
                <div className={cx("panel-actions")}><span className={cx("badge", reviewRequired > 0 ? "warning" : "success")}>{reviewRequired} 个待处理结果</span></div>
              </header>
              <div className={cx("question-review-list")}>
                {(pendingQuestions.length ? pendingQuestions : questions).map((question) => (
                  <article className={cx("review-row")} key={question.id}>
                    <div className={cx("review-id")}><strong>{question.id}</strong><span>{question.kind}</span></div>
                    <div><span>机器验证</span><strong className={cx(question.machinePassed ? "success-text" : "warning-text")}>{question.machinePassed ? "通过" : "待验证"}</strong></div>
                    <div><span>证据状态</span><strong>{question.machinePassed ? "可追溯" : "待生成"}</strong></div>
                    <div><span>假设输出</span><strong>≥ {stage1.acceptance.minimumHypothesisCount} 条</strong></div>
                    <div><span>人工状态</span><strong className={cx(question.humanApproved ? "success-text" : "warning-text")}>{question.humanApproved ? "已批准" : "待抽检"}</strong></div>
                    <button className={cx("button", "secondary")} type="button" title="审核写入仍由现有人工门禁流程负责">
                      {question.humanApproved ? "查看记录" : "开始审核"}
                    </button>
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
                      <time>{question.humanApproved ? "已批准" : "待抽检"}</time>
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
                <span className={cx("badge", readyAgentCount === agents.length ? "success" : "warning")}>{readyAgentCount} / {agents.length} 可用</span>
              </header>
              <div className={cx("agent-table")} role="table" aria-label="挑战杯 Agent 团队">
                <div className={cx("agent-row", "agent-head")} role="row">
                  <span role="columnheader">Agent</span><span role="columnheader">职责</span><span role="columnheader">所属工作区</span><span role="columnheader">模型</span><span role="columnheader">状态</span><span role="columnheader" />
                </div>
                {agents.map((agent) => (
                  <div className={cx("agent-row")} role="row" key={agent.agentId}>
                    <span className={cx("agent-person")}><i>{agent.name.slice(0, 1)}</i><b>{agent.name}</b><small>{agent.code}</small></span>
                    <span>{agent.role}</span><span>{agent.workspace}</span><span title={agent.model}>{agent.model}</span>
                    <span className={cx("status-icon", agent.tone === "ready" ? "success" : "warning")}>{agent.status}</span>
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
