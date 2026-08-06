import { type ReactNode, useEffect, useMemo, useState } from "react";

import {
  VNativeButton,
  VRouteLinkButton,
  VStatusChip,
  type VStatusTone,
} from "../../../components/vui";
import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTask,
} from "../../../api/types";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import { ChallengeCupExperimentStage } from "./ChallengeCupExperimentStage";
import { ChallengeCupIterationStage } from "./ChallengeCupIterationStage";
import { ChallengeCupKnowledgeStage } from "./ChallengeCupKnowledgeStage";
import { ChallengeCupStageRail, type ChallengeCupStageObject } from "./ChallengeCupStageRail";
import {
  CHALLENGE_CUP_STAGE_META,
  type ChallengeCupQuestion,
  type ChallengeCupStage,
  type ChallengeCupStageStatus,
} from "./challengeCupStageModel";
import css from "./ChallengeCupOperationsWorkspace.module.css";

type ChallengeProgramProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;

export type ChallengeCupProjectSwitcherContext = {
  activeStage: ChallengeCupStage;
  statusLabel: string;
  statusTone: "neutral" | "active" | "ready" | "warning";
  primaryActionHref: string;
  primaryActionLabel: string;
};

export type ChallengeCupOperationsWorkspaceProps = {
  projection?: ChallengeProgramProjection;
  graphHref: string;
  projectSwitcher?: ReactNode | ((context: ChallengeCupProjectSwitcherContext) => ReactNode);
  researchTopic?: string;
  initialStage?: ChallengeCupStage;
  stageHrefs?: Partial<Record<ChallengeCupStage, string>>;
  questionHref: (questionId: string) => string;
  agentConfiguration?: (stage: ChallengeCupStage) => ReactNode;
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

function cx(...tokens: Array<string | false | null | undefined>) {
  return tokens
    .filter((token): token is string => Boolean(token))
    .map((token) => css[token] || token)
    .join(" ");
}

function vuiStatusTone(tone: ChallengeCupProjectSwitcherContext["statusTone"]): VStatusTone {
  if (tone === "active" || tone === "ready") return "accent";
  if (tone === "warning") return "warning";
  return "neutral";
}

function GraphMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M8.2 11l7.4-4M8.2 13l7.4 4" />
      <circle cx="6.5" cy="12" r="2.4" />
      <circle cx="17.8" cy="6" r="2.4" />
      <circle cx="17.8" cy="18" r="2.4" />
    </svg>
  );
}

export function ChallengeCupOperationsWorkspace({
  projection,
  graphHref,
  projectSwitcher,
  researchTopic = "",
  initialStage = "knowledge_collection",
  stageHrefs = {},
  questionHref,
  agentConfiguration,
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
  const [activeStage, setActiveStage] = useState<ChallengeCupStage>(initialStage);
  const stage1 = projection?.stage1ComplianceReadiness;
  const stage2 = projection?.stage2BatchGovernance;
  const stage3 = projection?.stage3DeepResearchDelivery;

  useEffect(() => {
    setActiveStage(initialStage);
  }, [initialStage]);

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
  const programTitle = (projection?.program.title || "面向前沿科学问题的 AI 假设生成与研究计划设计平台")
    .replace("的AI", "的 AI");

  const questions = useMemo<ChallengeCupQuestion[]>(
    () => questionIds.map((id, index) => {
      const humanStatus: ChallengeCupQuestion["humanStatus"] = humanReview?.rejectedQuestionIds.includes(id)
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
    [approvedTrialCount, goldenApproved, humanReview, questionIds.join("|"), stage1?.singleQuestionSample.completed, stage1?.trialRun.completedQuestionIds],
  );

  const humanStatusLabel = (status: ChallengeCupQuestion["humanStatus"]) => {
    if (status === "approved") return "已批准";
    if (status === "revision_requested") return "需修订";
    if (status === "rejected") return "已拒绝";
    return "待抽检";
  };
  const citationGate = Boolean(stage1?.acceptance.citationValidation);
  const humanGate = humanReview?.allQuestionsApproved
    ?? (humanOutstanding === 0 && humanApproved >= machineRequired);
  const activeStageHref = stageHrefs[activeStage] || graphHref;
  const resolveQuestionHref = (questionId: string) => questionHref(questionId);

  const stageState = (stage: ChallengeCupStage): ChallengeCupStageStatus => {
    if (!stage1) return { label: "读取中", tone: "neutral", count: "" };
    if (stage === "knowledge_collection") {
      const blocked = stage1.blockers.length > 0;
      return {
        label: blocked ? "阻塞" : machineCompleted > 0 ? "进行中" : "未开始",
        tone: blocked ? "warning" : machineCompleted > 0 ? "active" : "neutral",
        count: "",
      };
    }
    if (stage === "experiment") {
      const designReady = stage1.acceptance.researchPlanPresent && stage1.acceptance.feedbackRevisionCount > 0;
      return { label: designReady ? "已有设计" : "待设计", tone: designReady ? "ready" : "neutral", count: "" };
    }
    const caseCount = stage3?.representativeCaseCount ?? 0;
    return { label: caseCount > 0 ? "迭代中" : "待执行", tone: caseCount > 0 ? "active" : "neutral", count: "" };
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
  const stageObjects: ChallengeCupStageObject[] = activeStage === "knowledge_collection"
    ? questions.slice(0, 3).map((question) => ({
        id: question.id,
        title: question.id,
        detail: `${question.kind} · ${question.machinePassed ? humanStatusLabel(question.humanStatus) : "待机器验证"}`,
        tone: question.humanApproved ? "ready" : question.machinePassed ? "active" : "neutral",
        href: resolveQuestionHref(question.id),
      }))
    : activeStage === "experiment"
      ? [{
          id: "experiment-design",
          title: researchTopic.trim() || "当前实验设计",
          detail: stage1?.acceptance.researchPlanPresent ? "研究计划已登记" : "等待生成可执行研究计划",
          tone: stage1?.acceptance.researchPlanPresent ? "ready" : "neutral",
          href: activeStageHref,
        }]
      : (stage3?.caseRecords ?? []).slice(0, 3).map((record) => ({
          id: record.caseId,
          title: record.title,
          detail: `${record.internalStatus} · ${record.bestValidatedResultId || "未登记"}`,
          tone: record.bestValidatedResultId ? "active" : "neutral",
          href: activeStageHref,
        }));

  return (
    <section className={cx("workspace", "platform-workspace")} aria-label="科研工作台" data-testid="challenge-cup-platform-workspace">
      <main className={cx("platform-frame")}>
        {!renderedProjectSwitcher ? <header className={cx("platform-project-header")}>
          <div className={cx("platform-project-identity")}>
            <div>
              <h1>{programTitle}</h1>
              <VStatusChip className={cx("status-pill")} tone={vuiStatusTone(activeStageState.tone)}>
                {activeStageState.label}
              </VStatusChip>
            </div>
          </div>
          <div className={cx("platform-project-actions")}>
            <VRouteLinkButton className={cx("button", "secondary")} icon={<GraphMark />} to={graphHref} variant="secondary">
              研究关系图
            </VRouteLinkButton>
            <VNativeButton className={cx("button", "secondary")} type="button" onClick={onRefresh} disabled={isRefreshing}>
              {isRefreshing ? "刷新中" : "刷新"}
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
              <VNativeButton className={cx("button", "primary")} type="button" onClick={onRefresh} disabled={isRefreshing}>
                {isRefreshing ? "重新读取中" : "重新读取"}
              </VNativeButton>
            </div>
          </section>
        ) : (
          <>
            {renderedProjectSwitcher ? <div className={cx("platform-project-switcher")}>{renderedProjectSwitcher}</div> : null}
            <div className={cx("platform-console")}>
              <ChallengeCupStageRail
                activeStage={activeStage}
                onSelectStage={setActiveStage}
                stageObjects={stageObjects}
                stageState={stageState}
              />
              <section className={cx("platform-canvas")} aria-labelledby="platform-stage-title">
                <header className={cx("platform-canvas-header")}>
                  <div>
                    <div>
                      <h2 id="platform-stage-title">{CHALLENGE_CUP_STAGE_META[activeStage].label}</h2>
                      <VStatusChip className={cx("status-pill")} tone={vuiStatusTone(activeStageState.tone)}>
                        {activeStageState.label}
                      </VStatusChip>
                    </div>
                  </div>
                  {activeStage === "knowledge_collection" ? (
                    <div className={cx("platform-canvas-actions")}>
                      <VRouteLinkButton className={cx("button", "secondary")} to={activeStageHref} variant="secondary">
                        打开
                      </VRouteLinkButton>
                    </div>
                  ) : null}
                </header>

                <div className={cx("platform-stage-layout")}>
                  <div className={cx("platform-stage-content")}>
                    {activeStage === "knowledge_collection" ? (
                      <ChallengeCupKnowledgeStage
                    citationGate={citationGate}
                    humanGate={humanGate}
                    humanStatusLabel={humanStatusLabel}
                    machineCompleted={machineCompleted}
                    modelLabel={modelLabel}
                    officialCallCount={officialCallCount}
                    onOpenQuestion={resolveQuestionHref}
                    programTitle={programTitle}
                    questions={questions}
                    researchTopic={researchTopic}
                    revisionRequired={revisionRequired}
                    sourceQuestionId={stage1.mvpManifest.goldenSampleQuestionId || ""}
                      />
                    ) : activeStage === "experiment" ? (
                      <ChallengeCupExperimentStage
                    activeProjectId={activeResearchProjectId}
                    isLoading={researchProjectAgentTasksLoading}
                    isStarting={researchProjectAgentTaskStarting}
                    onOpenTask={onOpenResearchProjectAgentTask}
                    onStartTask={onStartResearchProjectAgentTask}
                    stage1={stage1}
                    stage2={stage2}
                    startingTaskKind={researchProjectAgentTaskStartingKind}
                    taskError={researchProjectAgentTaskError}
                    tasks={researchProjectAgentTasks}
                      />
                    ) : (
                      <ChallengeCupIterationStage
                    activeProjectId={activeResearchProjectId}
                    cases={stage3?.caseRecords ?? []}
                    isLoading={researchProjectAgentTasksLoading}
                    isStarting={researchProjectAgentTaskStarting}
                    onOpenTask={onOpenResearchProjectAgentTask}
                    onStartTask={onStartResearchProjectAgentTask}
                    startingTaskKind={researchProjectAgentTaskStartingKind}
                    taskError={researchProjectAgentTaskError}
                    tasks={researchProjectAgentTasks}
                      />
                    )}
                  </div>
                  {agentConfiguration ? (
                    <aside className={cx("platform-stage-agent-configuration")}>
                      {agentConfiguration(activeStage)}
                    </aside>
                  ) : null}
                </div>
              </section>
            </div>
          </>
        )}
      </main>
    </section>
  );
}
