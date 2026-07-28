/**
 * Research stage launcher console (three-stage + Challenge Cup branch).
 * Wave 8H: extracted from TeamsRoute.tsx for domain componentization.
 * Presentation + local pure helpers; mutations/query objects injected by the route.
 */
import type { ReactNode } from "react";
import { CheckCircle2, Eye, Link2, Play, RefreshCw, Settings2 } from "lucide-react";
import type { NavigateFunction } from "react-router-dom";
import { Link } from "react-router-dom";

import type {
  ExperimentMethodId,
  ResearchProjectAgentTaskKind,
  Team,
} from "../api/types";
import { VNativeButton, VNativeInput, VNativeSelect } from "../components/vui";
import {
  ChallengeCupOperationsWorkspace,
  type ChallengeCupWorkspaceAgent,
} from "./teams/challenge-cup/ChallengeCupOperationsWorkspace";
import {
  researchIterationLifecycleStatusLabel,
  type ExperimentPlanningStatusPayload,
} from "./teams/experimentLoopModel";
import { isChallengeCupResearchWorkflowTeam } from "./teams/teamKindModel";
import { RESEARCH_TEAM_ID } from "./TeamsRoute.canvasData";
import {
  RESEARCH_WORKSPACE_NAV_ITEMS,
  researchCanvasRoute,
  researchSourceCollectionRoute,
  researchWorkspaceStageRoute,
  researchWorkspaceViewLabel,
  type ResearchStageWorkspaceView,
} from "./teams/researchWorkspaceModel";
import type {
  ResearchStagePhaseStatus,
  ResearchStageRoundStatusPayload,
  ResearchStageType,
} from "./teams/source-collection/stageProjection";
import {
  SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES,
  type SourceCollectionDraft,
} from "./teams/source-collection/presentationModel";
import { sourceCollectionRunLabel } from "./teams/source-collection/runModel";
import { ResearchProjectSwitcher } from "./teams/research-projects/ResearchProjectSwitcher";
import { useResearchProjectAgentTasks } from "./teams/research-projects/useResearchProjectAgentTasks";
import { ResearchMemoryEvidencePanel } from "./teams/ResearchMemoryEvidencePanel";
import type { ResearchMemoryContextSummary } from "./teams/ResearchMemoryEvidencePanel";
import researchStyles from "./TeamsRoute.research.styles";
import shellStyles from "./TeamsRoute.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

type Lang = "zh" | "en";

/** Loose injection surface so TeamsRoute can pass live query/mutation objects without over-narrowing. */
export type TeamResearchStageLauncherPanelProps = {
  researchWorkflowTeamSelected: boolean;
  challengeCupResearchTeamSelected: boolean;
  knowledgeExpansionWorkflowTeamSelected: boolean;
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  selectedTeam: Team | null | undefined;
  selectedTeamMemoryMembers: Array<{
    id: string;
    agentName: string;
    agentCode: string;
    roleLabel: string;
    statusTitle: string;
    statusLabel: string;
    statusTone: string;
    configRoute: string;
  }>;
  lang: Lang;
  challengeTeamSurface: "workspace" | "progress";
  sourceCollectionDraft: SourceCollectionDraft;
  setSourceCollectionDraft: (updater: (current: SourceCollectionDraft) => SourceCollectionDraft) => void;
  preferredExperimentMethod: string;
  setPreferredExperimentMethod: (method: any) => void;
  experimentPlanningStatusQuery: {
    isPending: boolean;
    isFetching: boolean;
    refetch: () => unknown;
  };
  sourceCollectionDisplayState: { statusText: string };
  selectedSourceCollectionRun: { runId: string } | null | undefined;
  sourceCollectionSearchOpenAssignmentCount: number;
  selectedTeamExecuteSourceCollectionSearchPending: boolean;
  sourceCollectionAcceptedBackgroundActive: boolean;
  sourceCollectionDownstreamOpenAssignmentCount: number;
  sourceCollectionRunPendingScreeningCount: number;
  selectedTeamStartSourceCollectionPending: boolean;
  sourceCollectionCanStart: boolean;
  selectedTeamStartResearchStagePending: boolean;
  researchStageCanLaunch: boolean;
  sourceCollectionSearchActionReadiness: { disabled: boolean; reason?: string; loading?: boolean };
  sourceCollectionActionInitialDataPending: boolean;
  sourceCollectionActionDataError: boolean;
  sourceCollectionActionBusyReason: string;
  sourceCollectionActionNoInputReason: string;
  sourceCollectionActionLoadingReason: string;
  sourceCollectionActionErrorReason: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionReadiness: (...args: any[]) => { disabled: boolean; reason?: string; loading?: boolean };
  selectedSourceCollectionAssignment: { status: string; agentRole: string; assignmentId: string } | null | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  executeSourceCollectionSearchMutation: { mutate: (payload: any) => void };
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  startSourceCollectionRunMutation: { mutate: (payload: any) => void };
  launchResearchStage: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void;
  navigate: NavigateFunction;
  researchStageRoundStatus: ResearchStageRoundStatusPayload | null | undefined;
  researchStageRoundStatusQuery: {
    isPending: boolean;
    isError: boolean;
    isFetching: boolean;
    refetch: () => unknown;
  };
  researchStagePhases: ResearchStagePhaseStatus[];
  searchParams: URLSearchParams;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  experimentMethodCatalogQuery: { data?: any; isFetching: boolean };
  researchTeamDetailDegraded: boolean;
  selectedTeamDetailLoading: boolean;
  teamDetailQuery: { isFetching: boolean; refetch: () => unknown };
  sourceCollectionSearchOpenAssignmentCountText: string;
  sourceCollectionDownstreamOpenAssignmentCountText: string;
  sourceCollectionCollectedCountText: string;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionQueryCountText: string;
  renderResearchStageAgentSummary: (stageType: ResearchStageType) => ReactNode;
  runKnowledgeCollectionLoopAction: () => void;
  sourceCollectionLoopActionDisabled: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  sourceCollectionLoopActionReadiness: { disabled: boolean; reason?: string; loading?: boolean };
  sourceCollectionLoopActionLabel: string;
  sourceCollectionLoopStartsNewRun: boolean;
  selectedTeamStartResearchStageError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamStartResearchStageResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  researchStageStartFeedbackText: (payload: any, lang: Lang, stageLabel?: string) => string;
};

export function TeamResearchStageLauncherPanel(props: TeamResearchStageLauncherPanelProps) {
  const {
    researchWorkflowTeamSelected,
    challengeCupResearchTeamSelected,
    knowledgeExpansionWorkflowTeamSelected,
    experimentPlanningStatus,
    selectedTeam,
    selectedTeamMemoryMembers,
    lang,
    challengeTeamSurface,
    sourceCollectionDraft,
    setSourceCollectionDraft,
    preferredExperimentMethod,
    setPreferredExperimentMethod,
    experimentPlanningStatusQuery,
    sourceCollectionDisplayState,
    selectedSourceCollectionRun,
    sourceCollectionSearchOpenAssignmentCount,
    selectedTeamExecuteSourceCollectionSearchPending,
    sourceCollectionAcceptedBackgroundActive,
    sourceCollectionDownstreamOpenAssignmentCount,
    sourceCollectionRunPendingScreeningCount,
    selectedTeamStartSourceCollectionPending,
    sourceCollectionCanStart,
    selectedTeamStartResearchStagePending,
    researchStageCanLaunch,
    sourceCollectionSearchActionReadiness,
    sourceCollectionActionInitialDataPending,
    sourceCollectionActionDataError,
    sourceCollectionActionBusyReason,
    sourceCollectionActionNoInputReason,
    sourceCollectionActionLoadingReason,
    sourceCollectionActionErrorReason,
    sourceCollectionActionReadiness,
    selectedSourceCollectionAssignment,
    executeSourceCollectionSearchMutation,
    selectedSourceCollectionRunEffectiveId,
    startSourceCollectionRunMutation,
    launchResearchStage,
    navigate,
    researchStageRoundStatus,
    researchStageRoundStatusQuery,
    researchStagePhases,
    searchParams,
    experimentMethodCatalogQuery,
    researchTeamDetailDegraded,
    selectedTeamDetailLoading,
    teamDetailQuery,
    sourceCollectionSearchOpenAssignmentCountText,
    sourceCollectionDownstreamOpenAssignmentCountText,
    sourceCollectionCollectedCountText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionQueryCountText,
    renderResearchStageAgentSummary,
    runKnowledgeCollectionLoopAction,
    sourceCollectionLoopActionDisabled,
    sourceCollectionActionDisabledTitle,
    sourceCollectionLoopActionReadiness,
    sourceCollectionLoopActionLabel,
    sourceCollectionLoopStartsNewRun,
    selectedTeamStartResearchStageError,
    selectedTeamStartResearchStageResult,
    researchStageStartFeedbackText,
  } = props;
  const workflowTeamId = selectedTeam?.teamId || RESEARCH_TEAM_ID;
  const researchProjectAgentTasks = useResearchProjectAgentTasks({
    teamId: workflowTeamId,
    enabled: challengeCupResearchTeamSelected,
  });

  const startResearchProjectAgentTask = async (
    taskKind: ResearchProjectAgentTaskKind,
    options: { formalRetry?: boolean; retryTaskId?: string } = {},
  ) => {
    const stage = taskKind === "experiment_design" || taskKind === "experiment_evidence_review"
      ? "experiment"
      : "iteration";
    const returnTo = researchWorkspaceStageRoute(workflowTeamId, stage);
    const payload = await researchProjectAgentTasks.startTask(taskKind, {
      ...options,
      returnTo,
      returnLabel: stage === "experiment" ? "返回实验设计" : "返回执行与迭代",
    });
    if (payload.chatRoute) {
      navigate(payload.chatRoute);
    }
  };


    if (!researchWorkflowTeamSelected) {
      return null;
    }
    if (challengeCupResearchTeamSelected) {
      const challengeProjection = experimentPlanningStatus?.challengeProgramProjection;
      const challengeTeamId = workflowTeamId;
      const challengeAgents: ChallengeCupWorkspaceAgent[] = selectedTeamMemoryMembers.map((member) => {
        const normalizedRole = member.roleLabel.toLowerCase();
        const workspace = normalizedRole.includes("source") || normalizedRole.includes("资料")
          ? "证据链"
          : normalizedRole.includes("knowledge") || normalizedRole.includes("知识")
            ? "知识库"
            : normalizedRole.includes("experiment") || normalizedRole.includes("实验")
              ? "题目与结果"
              : normalizedRole.includes("iteration") || normalizedRole.includes("版本")
                ? "深研迭代"
                : "全局";
        return {
          agentId: member.id,
          name: member.agentName,
          code: member.agentCode,
          role: member.roleLabel,
          workspace,
          model: member.statusTitle,
          status: member.statusLabel,
          tone: member.statusTone === "ready" ? "ready" : member.statusTone === "blocked" ? "blocked" : "warning",
          configHref: member.configRoute,
        };
      });
      return (
        <ChallengeCupOperationsWorkspace
          projection={challengeProjection}
          agents={challengeAgents}
          graphHref={researchCanvasRoute(challengeTeamId)}
          projectSwitcher={challengeTeamSurface === "workspace" ? ((context) => (
            <ResearchProjectSwitcher
              teamId={challengeTeamId}
              lang={lang}
              currentTopic={sourceCollectionDraft.topic}
              currentExperimentMethod={preferredExperimentMethod as ExperimentMethodId | ""}
              variant="hero"
              statusLabel={context.statusLabel}
              statusTone={context.statusTone}
              primaryActionHref={context.primaryActionHref}
              primaryActionLabel={context.primaryActionLabel}
              onProjectActivated={(project) => {
                setSourceCollectionDraft((current) => ({ ...current, topic: project.topic }));
                setPreferredExperimentMethod(project.experimentMethod || "");
              }}
            />
          )) : null}
          researchTopic={sourceCollectionDraft.topic}
          surface={challengeTeamSurface}
          stageHrefs={{
            knowledge_collection: researchSourceCollectionRoute(challengeTeamId),
            experiment: researchWorkspaceStageRoute(challengeTeamId, "experiment"),
            iteration: researchWorkspaceStageRoute(challengeTeamId, "iteration"),
          }}
          activeResearchProjectId={researchProjectAgentTasks.activeProjectId}
          researchProjectAgentTasks={researchProjectAgentTasks.tasks}
          researchProjectAgentTasksLoading={researchProjectAgentTasks.isLoading}
          researchProjectAgentTaskStarting={researchProjectAgentTasks.isStarting}
          researchProjectAgentTaskStartingKind={researchProjectAgentTasks.startingTaskKind}
          researchProjectAgentTaskError={researchProjectAgentTasks.error ? "task_request_failed" : ""}
          onStartResearchProjectAgentTask={startResearchProjectAgentTask}
          onOpenResearchProjectAgentTask={(task) => {
            if (task.chatRoute) {
              navigate(task.chatRoute);
            }
          }}
          isLoading={!challengeProjection && experimentPlanningStatusQuery.isPending}
          isUnavailable={!challengeProjection && !experimentPlanningStatusQuery.isPending}
          isRefreshing={experimentPlanningStatusQuery.isFetching}
          onRefresh={() => void experimentPlanningStatusQuery.refetch()}
        />
      );
    }
    const phaseOrder: ResearchStageType[] = knowledgeExpansionWorkflowTeamSelected ? ["knowledge_collection"] : ["knowledge_collection", "experiment", "iteration"];
    const phaseFallback: Record<ResearchStageType, { label: string; primaryAction: string }> = {
      knowledge_collection: {
        label: lang === "zh" ? "知识搜集" : "Knowledge",
        primaryAction: lang === "zh" ? "开始知识搜集" : "Start knowledge",
      },
      experiment: {
        label: lang === "zh" ? "实验设计" : "Experiment design",
        primaryAction: lang === "zh" ? "启动设计" : "Start design",
      },
      iteration: {
        label: lang === "zh" ? "执行与迭代" : "Execution & iteration",
        primaryAction: lang === "zh" ? "启动执行迭代" : "Start execution",
      },
    };
    const renderResearchMemoryContextDetails = (
      summary: ResearchMemoryContextSummary | undefined,
      stage: "experiment" | "iteration",
    ) => {
      return <ResearchMemoryEvidencePanel summary={summary} lang={lang} stage={stage} variant="compact" />;
    };
    const knowledgeCollectionStatusLabel = sourceCollectionDisplayState.statusText;
    const knowledgeCollectionPrimaryActionLabel = !selectedSourceCollectionRun
      ? knowledgeExpansionWorkflowTeamSelected
        ? (lang === "zh" ? "开始扩充" : "Start expansion")
        : (lang === "zh" ? "开始知识搜集" : "Start knowledge")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
          ? (lang === "zh" ? "搜索中" : "Searching")
          : (lang === "zh" ? "搜索下一批" : "Search next batch"))
        : sourceCollectionDownstreamOpenAssignmentCount > 0
          ? (lang === "zh" ? "进入阶段详情" : "Open stage details")
        : sourceCollectionRunPendingScreeningCount > 0
          ? (lang === "zh" ? "进入资料提炼复核" : "Open review")
          : (lang === "zh" ? "进入搜集工作台" : "Open collection workspace");
    const knowledgeCollectionPrimaryDisabled = !selectedSourceCollectionRun
      ? knowledgeExpansionWorkflowTeamSelected
        ? selectedTeamStartSourceCollectionPending || !sourceCollectionCanStart
        : selectedTeamStartResearchStagePending || !researchStageCanLaunch
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? sourceCollectionSearchActionReadiness.disabled
        : sourceCollectionActionInitialDataPending || sourceCollectionActionDataError;
    const knowledgeCollectionPrimaryReadiness = !selectedSourceCollectionRun
      ? sourceCollectionActionReadiness(
          knowledgeCollectionPrimaryDisabled,
          selectedTeamStartSourceCollectionPending || selectedTeamStartResearchStagePending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
        )
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? sourceCollectionSearchActionReadiness
        : sourceCollectionActionReadiness(
            sourceCollectionActionInitialDataPending || sourceCollectionActionDataError,
            sourceCollectionActionInitialDataPending ? sourceCollectionActionLoadingReason : sourceCollectionActionErrorReason,
            sourceCollectionActionInitialDataPending,
          );
    const runSourceCollectionSearchFromConsole = () => {
      if (sourceCollectionSearchActionReadiness.disabled || !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId) {
        return;
      }
      const selectedAssignmentIsRunnable = selectedSourceCollectionAssignment
        ? ["open", "in_progress", "returned"].includes(selectedSourceCollectionAssignment.status)
          && SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES.has(selectedSourceCollectionAssignment.agentRole)
        : false;
      executeSourceCollectionSearchMutation.mutate({
        teamId: selectedTeam.teamId,
        runId: selectedSourceCollectionRunEffectiveId,
        assignmentId: selectedAssignmentIsRunnable ? selectedSourceCollectionAssignment?.assignmentId : "",
        maxQueries: 4,
        maxResultsPerQuery: Math.max(1, Math.min(5, sourceCollectionDraft.maxResultsPerQuery || 2)),
      });
    };
    const runKnowledgeCollectionPrimaryAction = () => {
      if (knowledgeCollectionPrimaryReadiness.disabled) {
        return;
      }
      if (!selectedTeam?.teamId) {
        return;
      }
      if (!selectedSourceCollectionRun) {
        if (knowledgeExpansionWorkflowTeamSelected) {
          if (!sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
            return;
          }
          startSourceCollectionRunMutation.mutate({
            teamId: selectedTeam.teamId,
            draft: sourceCollectionDraft,
          });
          return;
        }
        launchResearchStage("knowledge_collection");
        return;
      }
      if (sourceCollectionSearchOpenAssignmentCount > 0) {
        runSourceCollectionSearchFromConsole();
        return;
      }
      navigate(researchSourceCollectionRoute(selectedTeam.teamId));
    };
    const stagePrimaryLabel = (stageType: ResearchStageType, fallback: string) => {
      if (stageType === "knowledge_collection") {
        return knowledgeCollectionPrimaryActionLabel;
      }
      return fallback;
    };
    const stageStatusLoading = !researchStageRoundStatus && researchStageRoundStatusQuery.isPending;
    const stageStatusUnavailable = !researchStageRoundStatus && researchStageRoundStatusQuery.isError;
    const experimentLifecycleProjection = experimentPlanningStatus?.lifecycleProjection;
    const challengeProgramProjection = challengeTeamSurface === "progress"
      ? experimentPlanningStatus?.challengeProgramProjection
      : undefined;
    const challengeProgramExpected = isChallengeCupResearchWorkflowTeam(selectedTeam)
      && challengeTeamSurface === "progress";
    const challengeProgramLoading = challengeProgramExpected
      && !challengeProgramProjection
      && experimentPlanningStatusQuery.isPending;
    const challengeProgramUnavailable = challengeProgramExpected
      && !challengeProgramProjection
      && !experimentPlanningStatusQuery.isPending;
    const requestedExperimentMethod = searchParams.get("experimentMethod");
    const requestedExperimentMethodIsValid = experimentMethodCatalogQuery.data?.methods.some(
      (method: any) => method.methodId === requestedExperimentMethod,
    );
    const selectedExperimentMethod = preferredExperimentMethod
      || (requestedExperimentMethodIsValid ? requestedExperimentMethod as ExperimentMethodId : "")
      || experimentPlanningStatus?.activePlan?.experimentContract?.experimentMethod
      || experimentMethodCatalogQuery.data?.methods[0]?.methodId
      || "model_training_inference";
    const selectedExperimentMethodDescriptor = experimentMethodCatalogQuery.data?.methods.find(
      (method: any) => method.methodId === selectedExperimentMethod,
    );
    const selectedExperimentResearchMode =
      experimentPlanningStatus?.activePlan?.experimentContract?.researchMode ?? "full_research_loop";
    const selectedExperimentAdapter = selectedExperimentMethodDescriptor?.adapterAvailability[selectedExperimentResearchMode];
    const selectedExperimentRegisteredAdapters = experimentMethodCatalogQuery.data?.adapters.filter(
      (adapter: any) => adapter.method === selectedExperimentMethod && adapter.availability === "available",
    ) ?? [];
    const selectedExperimentPlanningOnly = Boolean(
      selectedExperimentAdapter?.unavailableReason?.toLowerCase().includes("not required"),
    );
    const selectedExperimentAdapterStatus = selectedExperimentAdapter?.resolvedAdapterId
      ? "ready"
      : selectedExperimentRegisteredAdapters.length > 0
        ? "select_required"
        : selectedExperimentPlanningOnly
          ? "not_required"
          : "blocked";
    const selectedExperimentAdapterLabel = selectedExperimentAdapterStatus === "ready"
      ? (lang === "zh" ? "执行器可用" : "Adapter ready")
      : selectedExperimentAdapterStatus === "select_required"
        ? (lang === "zh" ? "需选择执行器" : "Select an adapter")
        : selectedExperimentAdapterStatus === "not_required"
          ? (lang === "zh" ? "无需执行器" : "Adapter not required")
          : (lang === "zh" ? "执行器阻塞" : "Adapter blocked");
    const selectedExperimentAdapterReason = selectedExperimentAdapterStatus === "ready"
      ? `${selectedExperimentAdapter?.resolvedAdapterId} · ${selectedExperimentAdapter?.selectionSource}`
      : selectedExperimentAdapterStatus === "select_required"
        ? (lang === "zh"
          ? `已发现 ${selectedExperimentRegisteredAdapters.length} 个可用执行器，进入配置页后明确选择。`
          : `${selectedExperimentRegisteredAdapters.length} available adapter(s); choose one in setup.`)
        : selectedExperimentAdapterStatus === "not_required"
          ? (lang === "zh"
            ? "当前闭环只生成假设与研究计划，不会启动真实实验。"
            : "This loop only generates hypotheses and a plan; no real experiment starts.")
          : (lang === "zh"
            ? `当前“${selectedExperimentMethodDescriptor?.labelZh || selectedExperimentMethod}”没有已注册且可用的执行器。`
            : (selectedExperimentAdapter?.unavailableReason || "No registered adapter is available for this method."));
    const executableAlternativeMethods = experimentMethodCatalogQuery.data?.methods.filter((method: any) => {
      if (method.methodId === selectedExperimentMethod) {
        return false;
      }
      const automaticAdapter = method.adapterAvailability[selectedExperimentResearchMode]?.resolvedAdapterId;
      const explicitAdapter = experimentMethodCatalogQuery.data?.adapters.some(
        (adapter: any) => adapter.method === method.methodId && adapter.availability === "available",
      );
      return Boolean(automaticAdapter || explicitAdapter);
    }).slice(0, 2) ?? [];
    const selectedExperimentMethodRoute = `${researchWorkspaceStageRoute(
      selectedTeam?.teamId || RESEARCH_TEAM_ID,
      "experiment",
    )}&experimentMethod=${encodeURIComponent(selectedExperimentMethod)}`;
    const challengeTrialReviewRequiredCount = challengeProgramProjection?.stage1ComplianceReadiness.trialRun.outcomeCounts.review_required || 0;
    const challengeTrialApprovedCount = challengeProgramProjection?.stage1ComplianceReadiness.trialRun.outcomeCounts.approved || 0;
    const challengeStageLabel = (stageType: ResearchStageType) => {
      if (stageType === "knowledge_collection") {
        return lang === "zh" ? "MVP 黄金样例" : "MVP golden sample";
      }
      if (stageType === "experiment") {
        return lang === "zh" ? "3 题试运行" : "Three trial questions";
      }
      return lang === "zh" ? "后续规模化与深研" : "Later scale-up and deep research";
    };
    const stageStatusLabel = (stageType: ResearchStageType, active: boolean, latestRound: ResearchStagePhaseStatus["latestRound"] | null | undefined) => {
      if (challengeProgramProjection) {
        if (stageType === "knowledge_collection") {
          const stage1 = challengeProgramProjection.stage1ComplianceReadiness;
          if (stage1.blockers.includes("dashscope_qwen_provider_missing")) {
            return lang === "zh" ? "BLOCKED · 待配置" : "BLOCKED · configuration required";
          }
          if (stage1.blockers.includes("dashscope_qwen_call_evidence_missing")) {
            return lang === "zh" ? "BLOCKED · 待验证" : "BLOCKED · validation required";
          }
          return stage1.singleQuestionSample.completed >= stage1.singleQuestionSample.required
            ? (lang === "zh" ? "已完成" : "completed")
            : (lang === "zh" ? "待收口" : "pending");
        }
        if (stageType === "experiment") {
          const stage1 = challengeProgramProjection.stage1ComplianceReadiness;
          if (stage1.singleQuestionSample.completed < stage1.singleQuestionSample.required) {
            return lang === "zh" ? "等待黄金样例" : "waiting for golden sample";
          }
          return stage1.trialRun.completed >= stage1.trialRun.required
            ? challengeTrialReviewRequiredCount > 0
              ? (lang === "zh" ? "机器验证完成 · 待人工抽检" : "machine checks complete · human review pending")
              : (lang === "zh" ? "验证完成" : "validation complete")
            : (lang === "zh" ? "待测试" : "pending");
        }
        return lang === "zh" ? "MVP 后再启动" : "deferred until after MVP";
      }
      if (stageType === "knowledge_collection") {
        return knowledgeCollectionStatusLabel;
      }
      if (stageType === "experiment" && experimentLifecycleProjection?.stage2) {
        if (experimentLifecycleProjection.stage2.status === "frozen") {
          return lang === "zh" ? "已设计 · 待执行" : "designed · ready";
        }
        if (experimentLifecycleProjection.stage2.status === "draft") {
          return lang === "zh" ? "设计中" : "designing";
        }
      }
      if (stageType === "iteration" && experimentLifecycleProjection?.stage3) {
        return researchIterationLifecycleStatusLabel(experimentLifecycleProjection.stage3.status, lang);
      }
      if (stageStatusLoading) {
        return lang === "zh" ? "状态同步中" : "Syncing status";
      }
      if (stageStatusUnavailable) {
        return lang === "zh" ? "状态暂不可用" : "Status unavailable";
      }
      if (active) {
        return lang === "zh" ? "运行中" : "running";
      }
      if (latestRound) {
        return lang === "zh" ? "已有轮次" : "has round";
      }
      return lang === "zh" ? "未启动" : "not started";
    };
    const stageStatusStyle = (stageType: ResearchStageType, active: boolean, latestRound: ResearchStagePhaseStatus["latestRound"] | null | undefined) => {
      if (challengeProgramProjection) {
        const stage1 = challengeProgramProjection.stage1ComplianceReadiness;
        if (stageType === "knowledge_collection") {
          return stage1.singleQuestionSample.completed >= stage1.singleQuestionSample.required
            ? styles.researchStageStatusRecorded
            : styles.researchStageStatusUnavailable;
        }
        if (stageType === "experiment") {
          return stage1.trialRun.completed >= stage1.trialRun.required
            ? styles.researchStageStatusRecorded
            : styles.researchStageStatusPending;
        }
        return styles.researchStageStatusPending;
      }
      if (stageType !== "knowledge_collection" && stageStatusLoading) {
        return styles.researchStageStatusLoading;
      }
      if (stageType !== "knowledge_collection" && stageStatusUnavailable) {
        return styles.researchStageStatusUnavailable;
      }
      if (active) {
        return styles.researchStageStatusActive;
      }
      if (latestRound || (stageType === "knowledge_collection" && selectedSourceCollectionRun)) {
        return styles.researchStageStatusRecorded;
      }
      return styles.researchStageStatusPending;
    };
    const stagePrimaryDisabled = (stageType: ResearchStageType) => {
      if (challengeProgramProjection) {
        return true;
      }
      if (stageType === "knowledge_collection") {
        return knowledgeCollectionPrimaryDisabled;
      }
      return stageStatusLoading || stageStatusUnavailable || selectedTeamStartResearchStagePending;
    };
    const runStagePrimaryAction = (stageType: ResearchStageType) => {
      if (stageType === "knowledge_collection") {
        runKnowledgeCollectionPrimaryAction();
        return;
      }
      launchResearchStage(stageType);
    };
    const stageHint = (stageType: ResearchStageType, active: boolean, latestRound: ResearchStagePhaseStatus["latestRound"] | null | undefined) => {
      if (challengeProgramProjection) {
        if (stageType === "knowledge_collection") {
          const providerReady = challengeProgramProjection.stage1ComplianceReadiness.dashscopeQwenProvider.configured;
          return providerReady
            ? (lang === "zh" ? "先把 1 题完整跑通：真实模型调用、证据、假设、七维审查、研究计划和四个人工门禁均可追踪。" : "Complete one end-to-end sample with a real model call, evidence, hypotheses, review, plan, and human gates.")
            : (lang === "zh" ? "缺少 DashScope/Qwen 正式 provider；只允许契约测试和样例草稿，禁止冒充真实调用。" : "DashScope/Qwen provider is missing; only contract tests and drafts are allowed.");
        }
        if (stageType === "experiment") {
          return lang === "zh"
            ? "黄金样例通过后，再用 3 个试运行题验证可重复性、跨领域能力和缺证据时的正确阻塞。"
            : "After the golden sample, validate repeatability, cross-domain behavior, and explicit evidence blocking on three questions.";
        }
        return lang === "zh"
          ? "125 题批跑、三个深研案例和最终参赛封装均延后到 MVP 验收之后，不计入本轮完成条件。"
          : "The 125-question run, three deep cases, and submission package are deferred until after MVP acceptance.";
      }
      if (stageType === "knowledge_collection") {
        if (!selectedSourceCollectionRun) {
          return lang === "zh" ? "生成搜索计划和团队分工，先把资料搜索跑起来。" : "Create the search plan and team assignments.";
        }
        if (selectedTeamExecuteSourceCollectionSearchPending) {
          return lang === "zh" ? "正在执行搜索，结果会写入资料记录和候选资料仓库。" : "Searching now; results will be written into DataRecords and candidates.";
        }
        if (sourceCollectionSearchOpenAssignmentCount > 0) {
          return lang === "zh" ? "还有搜索任务，可继续跑下一批。" : "Search tasks are ready for another batch.";
        }
        if (sourceCollectionDownstreamOpenAssignmentCount > 0) {
          return lang === "zh" ? "搜索已停，后续进入提炼或筛选。" : "Search is idle; extraction or screening is next.";
        }
        if (sourceCollectionRunPendingScreeningCount > 0) {
          return lang === "zh" ? "已有候选资料，下一步进入筛选。" : "Candidate sources are ready for screening.";
        }
        return lang === "zh" ? "本轮可补充搜集，或由用户决定进入实验。" : "Add another collection round or move to experiments.";
      }
      if (stageType === "experiment") {
        if (experimentLifecycleProjection?.stage2.status === "frozen") {
          return lang === "zh"
            ? "实验设计已冻结；训练结果不参与本阶段完成判定。"
            : "The design is frozen; training results do not determine Stage 2 completion.";
        }
        if (active) {
          return lang === "zh" ? "补齐假设、变量、控制组、预算、指标与执行门禁。" : "Complete hypotheses, variables, controls, budget, metrics, and gates.";
        }
        return latestRound
          ? (lang === "zh" ? "可重新规划实验，或查看上一轮计划。" : "Replan or review the latest plan.")
          : (lang === "zh" ? "知识搜集后，由用户决定启动实验规划。" : "Start experiment planning after collection.");
      }
      if (experimentLifecycleProjection?.stage3.status === "accepted_for_writeup") {
        return lang === "zh"
          ? "最佳版本已通过评估；最近诊断单独展示，不覆盖主线结果。"
          : "The best version passed review; diagnostics remain separate from the main result.";
      }
      if (active) {
        return lang === "zh" ? "按冻结设计执行、评估、归因并受控迭代。" : "Execute the frozen design, evaluate, diagnose, and iterate under control.";
      }
      return latestRound
        ? (lang === "zh" ? "可开启新一轮优化，沉淀交付计划。" : "Start another optimization round and prepare delivery.")
        : (lang === "zh" ? "冻结实验设计后进入执行、优化和迭代。" : "Enter execution and iteration after the design is frozen.");
    };
    const currentStageLabel = researchStageRoundStatus?.currentStage
      ? researchWorkspaceViewLabel(researchStageRoundStatus.currentStage as ResearchStageWorkspaceView, lang)
      : lang === "zh" ? "待启动" : "not started";
    const renderChallengeProgramResults = () => {
      if (!challengeProgramProjection) {
        return null;
      }
      const stage1 = challengeProgramProjection.stage1ComplianceReadiness;
      const goldenSampleApproved = stage1.acceptance.allFourHumanGatesApproved;
      const deepCase = challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0];
      const deepCaseStatus = deepCase?.internalStatus === "accepted_for_writeup"
        ? (lang === "zh" ? "案例内部已通过撰写审查" : "case accepted for write-up")
        : deepCase?.internalStatus || (lang === "zh" ? "尚未启动" : "not started");
      return (
        <section
          id="challenge-mvp-results"
          className={styles.challengeProgramResults}
          aria-labelledby="challenge-mvp-results-title"
        >
          <header className={styles.challengeProgramResultsHeader}>
            <div>
              <strong id="challenge-mvp-results-title">{lang === "zh" ? "MVP 验收结果" : "MVP acceptance results"}</strong>
              <span>
                {lang === "zh"
                  ? `机器验证 ${stage1.mvpManifest.completedQuestionCount}/${stage1.mvpManifest.requiredQuestionCount}；人工审核与机器验证分开记录`
                  : `Machine validation ${stage1.mvpManifest.completedQuestionCount}/${stage1.mvpManifest.requiredQuestionCount}; human review is tracked separately`}
              </span>
            </div>
            <span className={`${styles.researchStageStatus} ${styles.researchStageStatusRecorded}`}>
              {lang === "zh" ? "MVP 可验收" : "MVP ready for acceptance"}
            </span>
          </header>
          <div className={styles.challengeProgramResultGrid}>
            <article id="challenge-mvp-sample" className={styles.challengeProgramResultCard}>
              <header>
                <strong>{lang === "zh" ? "黄金样例" : "Golden sample"}</strong>
                <span className={`${styles.researchStageStatus} ${goldenSampleApproved ? styles.researchStageStatusRecorded : styles.researchStageStatusPending}`}>
                  {goldenSampleApproved
                    ? (lang === "zh" ? "人工审核通过" : "human review approved")
                    : (lang === "zh" ? "待人工审核" : "human review pending")}
                </span>
              </header>
              <div className={styles.challengeProgramQuestionList}>
                <span>{stage1.mvpManifest.goldenSampleQuestionId}</span>
              </div>
              <p>
                {lang === "zh"
                  ? `Schema、引用、七维审查与研究计划均已记录；反馈修订 ${stage1.acceptance.feedbackRevisionCount} 次。`
                  : `Schema, citations, seven-dimension review, and the research plan are recorded; ${stage1.acceptance.feedbackRevisionCount} feedback revision(s).`}
              </p>
            </article>
            <article id="challenge-mvp-trials" className={styles.challengeProgramResultCard}>
              <header>
                <strong>{lang === "zh" ? "三题试运行" : "Three trial questions"}</strong>
                <span className={`${styles.researchStageStatus} ${challengeTrialReviewRequiredCount > 0 ? styles.researchStageStatusPending : styles.researchStageStatusRecorded}`}>
                  {challengeTrialReviewRequiredCount > 0
                    ? (lang === "zh" ? `待人工抽检 ${challengeTrialReviewRequiredCount}` : `${challengeTrialReviewRequiredCount} awaiting human review`)
                    : (lang === "zh" ? "审核完成" : "review complete")}
                </span>
              </header>
              <div className={styles.challengeProgramQuestionList}>
                {(stage1.mvpManifest.trialQuestionIds ?? stage1.mvpManifest.testQuestionIds).map((questionId) => <span key={questionId}>{questionId}</span>)}
              </div>
              <p>
                {lang === "zh"
                  ? `机器验证 ${stage1.trialRun.completed}/${stage1.trialRun.required}；人工已批准 ${challengeTrialApprovedCount}，其余保持待审核，不计作正式人工通过。`
                  : `Machine validation ${stage1.trialRun.completed}/${stage1.trialRun.required}; ${challengeTrialApprovedCount} human-approved, with the remainder explicitly pending.`}
              </p>
            </article>
            <article id="challenge-mvp-roadmap" className={styles.challengeProgramResultCard}>
              <header>
                <strong>{lang === "zh" ? "MVP 后续范围" : "Post-MVP scope"}</strong>
                <span className={`${styles.researchStageStatus} ${styles.researchStageStatusPending}`}>
                  {lang === "zh" ? "暂缓" : "deferred"}
                </span>
              </header>
              <p>{lang === "zh" ? "125 题批跑与三案例深研不计入本轮 MVP 完成条件。" : "The 125-question run and three deep cases are outside this MVP."}</p>
              <p>
                {deepCase
                  ? `${deepCase.title} · ${deepCaseStatus}`
                  : (lang === "zh" ? "当前没有已登记的代表性深研案例。" : "No representative deep-research case is registered.")}
              </p>
            </article>
          </div>
        </section>
      );
    };
    return (
      <section
        className={styles.researchStageLauncher}
        aria-label={lang === "zh" ? "科研控制台" : "Research console"}
        aria-busy={challengeProgramLoading}
        aria-live="polite"
      >
        <div className={styles.researchStageLauncherHeader}>
          <div>
            <strong>{challengeProgramProjection?.program.title || (lang === "zh" ? "科研控制台（三阶段）" : "Research console (3 stages)")}</strong>
            <span>
              {challengeProgramProjection
                ? `${challengeProgramProjection.program.officialProblemId} · ${challengeProgramProjection.program.track}`
                : researchStageRoundStatus
                ? `${lang === "zh" ? "当前阶段" : "Current"} · ${currentStageLabel}`
                : researchStageRoundStatusQuery.isPending
                ? (lang === "zh" ? "读取阶段状态中" : "Loading stage status")
                : (lang === "zh" ? "选择一个阶段开始" : "Choose a stage to start")}
            </span>
          </div>
          <div className={styles.researchStageHeaderActions}>
            <Link to={researchCanvasRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}>
              <Eye size={13} />
              {lang === "zh" ? "研究关系图" : "Research graph"}
            </Link>
            <VNativeButton type="button" onClick={() => void researchStageRoundStatusQuery.refetch()} disabled={researchStageRoundStatusQuery.isFetching} title={lang === "zh" ? "刷新阶段状态" : "Refresh stage status"}>
              <RefreshCw size={13} />
            </VNativeButton>
          </div>
        </div>
        {researchTeamDetailDegraded ? (
          <div className={styles.researchStageDegradedNotice} role="status">
            <span>{selectedTeamDetailLoading
              ? (lang === "zh" ? "正在补齐团队详情；科研阶段状态仍可独立读取。" : "Loading team details; research stage status remains available.")
              : (lang === "zh" ? "团队详情暂时不可用；当前保留已读取的科研状态。" : "Team details are temporarily unavailable; loaded research state is retained.")}
            </span>
            <VNativeButton type="button" onClick={() => void teamDetailQuery.refetch()} disabled={teamDetailQuery.isFetching}>
              <RefreshCw size={13} />
              {lang === "zh" ? "重试详情" : "Retry details"}
            </VNativeButton>
          </div>
        ) : null}
        <ResearchProjectSwitcher
          teamId={selectedTeam?.teamId || RESEARCH_TEAM_ID}
          lang={lang}
          currentTopic={sourceCollectionDraft.topic}
          currentExperimentMethod={preferredExperimentMethod as ExperimentMethodId | ""}
          onProjectActivated={(project) => {
            setSourceCollectionDraft((current) => ({ ...current, topic: project.topic }));
            setPreferredExperimentMethod(project.experimentMethod || "");
          }}
        />
        {challengeProgramProjection ? (
          <div className={styles.challengeProgramScope}>
            <strong>{lang === "zh" ? "当前范围：1 个黄金样例 + 3 个试运行题（共 4 题）" : "Current scope: 1 golden sample + 3 trial questions (4 total)"}</strong>
            <span>{lang === "zh" ? "125 题规模化与三案例深研已明确延后" : "125-question scale-up and three deep cases are explicitly deferred"}</span>
          </div>
        ) : challengeProgramExpected ? null : (
          <label className={styles.researchStageTopicInput}>
            <span>{lang === "zh" ? "研究主题" : "Research topic"}</span>
            <VNativeInput
              value={sourceCollectionDraft.topic}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, topic: event.target.value }))}
              placeholder={lang === "zh" ? "例如：predictive coding" : "e.g. predictive coding"}
            />
          </label>
        )}
        {challengeProgramLoading ? (
          <div className={styles.researchStageDegradedNotice} role="status">
            <span>{lang === "zh" ? "正在读取挑战杯 MVP 状态，不会显示旧科研流程。" : "Loading the Challenge Cup MVP state without falling back to the legacy workflow."}</span>
          </div>
        ) : challengeProgramUnavailable ? (
          <div className={styles.researchStageDegradedNotice} role="alert">
            <span>{lang === "zh" ? "挑战杯 MVP 状态暂不可用；旧科研流程已保持隐藏，避免产生错误操作。" : "The Challenge Cup MVP state is unavailable; the legacy workflow remains hidden to prevent incorrect actions."}</span>
            <VNativeButton type="button" onClick={() => void experimentPlanningStatusQuery.refetch()} disabled={experimentPlanningStatusQuery.isFetching}>
              <RefreshCw size={13} />
              {lang === "zh" ? "重试" : "Retry"}
            </VNativeButton>
          </div>
        ) : (
        <>
        <div className={styles.researchStageGrid}>
          {phaseOrder.map((stageType) => {
            const phase = researchStagePhases.find((item) => item.stageType === stageType);
            const fallback = phaseFallback[stageType];
            const latestRound = phase?.latestRound;
            const active = Boolean(phase?.activeRoundId);
            const disabled = stagePrimaryDisabled(stageType);
            const navItem = RESEARCH_WORKSPACE_NAV_ITEMS.find((item) => item.view === stageType);
            const primaryLabel = stagePrimaryLabel(stageType, fallback.primaryAction);
            return (
              <article
                key={stageType}
                className={active ? `${styles.researchStageCard} ${styles.researchStageCardActive}` : styles.researchStageCard}
                aria-busy={stageType !== "knowledge_collection" && stageStatusLoading}
                aria-current={active ? "step" : undefined}
              >
                <div className={styles.researchStageCardHead}>
                  <small>{String(phaseOrder.indexOf(stageType) + 1).padStart(2, "0")}</small>
                  <div>
                    <strong>{challengeProgramProjection ? challengeStageLabel(stageType) : fallback.label}</strong>
                    <span className={`${styles.researchStageStatus} ${stageStatusStyle(stageType, active, latestRound)}`}>{stageStatusLabel(stageType, active, latestRound)}</span>
                  </div>
                </div>
                <p>{stageHint(stageType, active, latestRound)}</p>
                {!challengeProgramProjection && stageType === "experiment" ? (
                  <div className={styles.researchExperimentMethodQuickSelect}>
                    <label>
                      <span>{lang === "zh" ? "实验方式" : "Experiment method"}</span>
                      <VNativeSelect
                        value={selectedExperimentMethod}
                        onChange={(event) => setPreferredExperimentMethod(event.target.value as ExperimentMethodId | "")}
                        disabled={experimentMethodCatalogQuery.isFetching || !experimentMethodCatalogQuery.data}
                        aria-label={lang === "zh" ? "选择实验方式" : "Select experiment method"}
                      >
                        {experimentMethodCatalogQuery.data?.methods.map((method: any) => (
                          <option key={method.methodId} value={method.methodId}>
                            {lang === "zh" ? method.labelZh : method.labelEn}
                          </option>
                        ))}
                      </VNativeSelect>
                    </label>
                    <div>
                      <span>
                        {selectedExperimentMethodDescriptor
                          ? `${selectedExperimentMethodDescriptor.requiredConfigFields.length} ${lang === "zh" ? "项配置" : "fields"}`
                          : (experimentMethodCatalogQuery.isFetching
                            ? (lang === "zh" ? "读取方式中" : "Loading methods")
                            : (lang === "zh" ? "方式目录不可用" : "Method catalog unavailable"))}
                      </span>
                      <span className={["ready", "not_required"].includes(selectedExperimentAdapterStatus) ? styles.researchExperimentMethodReady : styles.researchExperimentMethodPending}>
                        {selectedExperimentAdapterLabel}
                      </span>
                      <Link to={selectedExperimentMethodRoute}>
                        <Settings2 size={13} />
                        {lang === "zh" ? "配置方法" : "Configure"}
                      </Link>
                    </div>
                    <p className={styles.researchExperimentMethodReason}>{selectedExperimentAdapterReason}</p>
                    {selectedExperimentAdapterStatus === "blocked" && executableAlternativeMethods.length > 0 ? (
                      <div className={styles.researchExperimentMethodAlternatives}>
                        <span>{lang === "zh" ? "可执行替代" : "Executable alternatives"}</span>
                        {executableAlternativeMethods.map((method: any) => (
                          <VNativeButton
                            key={method.methodId}
                            type="button"
                            onClick={() => setPreferredExperimentMethod(method.methodId as ExperimentMethodId)}
                          >
                            {lang === "zh" ? method.labelZh : method.labelEn}
                          </VNativeButton>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {challengeProgramProjection ? (
                  <div className={styles.researchStageCardMetrics}>
                    {stageType === "knowledge_collection" ? (
                      <>
                        <span>{lang === "zh" ? "真实样例" : "real sample"} {challengeProgramProjection.stage1ComplianceReadiness.singleQuestionSample.completed}/{challengeProgramProjection.stage1ComplianceReadiness.singleQuestionSample.required}</span>
                        <span>{lang === "zh" ? "百炼证据" : "DashScope evidence"} {challengeProgramProjection.stage1ComplianceReadiness.officialModelCallEvidence.count}</span>
                        <span>{lang === "zh" ? "人工审核" : "human review"} {challengeProgramProjection.stage1ComplianceReadiness.acceptance.allFourHumanGatesApproved ? (lang === "zh" ? "通过" : "approved") : (lang === "zh" ? "待处理" : "pending")}</span>
                        <span>{lang === "zh" ? "独立维度" : "dimensions"} {challengeProgramProjection.stage1ComplianceReadiness.independentEvaluationDimensions.length} · {lang === "zh" ? "人工门禁" : "human gates"} {challengeProgramProjection.stage1ComplianceReadiness.humanGates.length}</span>
                      </>
                    ) : stageType === "experiment" ? (
                      <>
                        <span>{lang === "zh" ? "试运行题" : "trial questions"} {challengeProgramProjection.stage1ComplianceReadiness.trialRun.completed}/{challengeProgramProjection.stage1ComplianceReadiness.trialRun.required}</span>
                        <span>{lang === "zh" ? "人工抽检" : "human review"} {challengeTrialReviewRequiredCount > 0 ? (lang === "zh" ? `待 ${challengeTrialReviewRequiredCount}` : `${challengeTrialReviewRequiredCount} pending`) : (lang === "zh" ? "完成" : "complete")}</span>
                        <span>{lang === "zh" ? "MVP 总进度" : "MVP progress"} {challengeProgramProjection.stage1ComplianceReadiness.mvpManifest.completedQuestionCount}/{challengeProgramProjection.stage1ComplianceReadiness.mvpManifest.requiredQuestionCount}</span>
                        <span>{lang === "zh" ? "规模化" : "scale-up"} {lang === "zh" ? "已延后" : "deferred"}</span>
                      </>
                    ) : (
                      <>
                        <span>{lang === "zh" ? "125 题批跑" : "125-question run"} · {lang === "zh" ? "暂缓" : "deferred"}</span>
                        <span>{lang === "zh" ? "深研案例" : "deep cases"} {challengeProgramProjection.stage3DeepResearchDelivery.representativeCaseCount}/{challengeProgramProjection.stage3DeepResearchDelivery.requiredRepresentativeCaseCount}</span>
                        <span title={challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.claimBoundary || ""}>
                          {challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.title || (lang === "zh" ? "单案例" : "case")} · {challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.internalStatus === "accepted_for_writeup"
                            ? (lang === "zh" ? "案例内部已通过撰写审查" : "case accepted for write-up")
                            : challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.internalStatus || "-"}
                        </span>
                      </>
                    )}
                  </div>
                ) : stageType === "knowledge_collection" && selectedSourceCollectionRun ? (
                  <div className={styles.researchStageCardMetrics}>
                    <span>{sourceCollectionRunLabel(selectedSourceCollectionRun.runId)}</span>
                    <span>{lang === "zh" ? `可搜索 ${sourceCollectionSearchOpenAssignmentCountText}` : `search ${sourceCollectionSearchOpenAssignmentCountText}`}</span>
                    <span>{lang === "zh" ? `后续 ${sourceCollectionDownstreamOpenAssignmentCountText}` : `next ${sourceCollectionDownstreamOpenAssignmentCountText}`}</span>
                    <span>{lang === "zh" ? `原始 ${sourceCollectionCollectedCountText}` : `raw ${sourceCollectionCollectedCountText}`}</span>
                    <span>{lang === "zh" ? `候选 ${sourceCollectionDisplayedCandidateCountText}` : `candidates ${sourceCollectionDisplayedCandidateCountText}`}</span>
                    <span>{lang === "zh" ? `查询 ${sourceCollectionQueryCountText}` : `queries ${sourceCollectionQueryCountText}`}</span>
                  </div>
                ) : stageType === "experiment" && experimentLifecycleProjection?.stage2 ? (
                  <>
                    <div className={styles.researchStageCardMetrics}>
                      <span>{lang === "zh" ? `冻结设计 v${experimentLifecycleProjection.stage2.frozenDesignRevision || "-"}` : `frozen v${experimentLifecycleProjection.stage2.frozenDesignRevision || "-"}`}</span>
                      <span title={experimentLifecycleProjection.stage2.activeDesignPlanId}>
                        {lang === "zh" ? "当前设计" : "design"} {experimentLifecycleProjection.stage2.activeDesignPlanId || "-"}
                      </span>
                      <span>{experimentLifecycleProjection.stage2.readyForExecution ? (lang === "zh" ? "可执行" : "executable") : (lang === "zh" ? "待冻结" : "not frozen")}</span>
                      <span title={experimentLifecycleProjection.stage2.memoryContextSummary?.missingEvidence.join(" / ") || ""}>
                        {lang === "zh" ? "团队记忆" : "memory"} {experimentLifecycleProjection.stage2.memoryContextSummary?.knowledgeItemCount ?? 0}
                        {" · "}{lang === "zh" ? "负向" : "negative"} {experimentLifecycleProjection.stage2.memoryContextSummary?.negativeExperimentCount ?? 0}
                      </span>
                    </div>
                    {renderResearchMemoryContextDetails(experimentLifecycleProjection.stage2.memoryContextSummary, "experiment")}
                  </>
                ) : stageType === "iteration" && experimentLifecycleProjection?.stage3 ? (
                  <>
                    <div className={styles.researchStageCardMetrics}>
                      <span title={experimentLifecycleProjection.stage3.bestCandidateId}>
                        {lang === "zh" ? "最佳候选" : "best"} {experimentLifecycleProjection.stage3.bestCandidateId || "-"}
                      </span>
                      <span title={experimentLifecycleProjection.stage3.bestValidatedResultId}>
                        {lang === "zh" ? "最佳结果" : "result"} {experimentLifecycleProjection.stage3.bestValidatedResultId || "-"}
                      </span>
                      <span title={experimentLifecycleProjection.stage3.latestDiagnosticStatus.title}>
                        {lang === "zh" ? "最近诊断" : "diagnostic"} {experimentLifecycleProjection.stage3.latestDiagnosticStatus.status || "-"}
                      </span>
                      <span title={experimentLifecycleProjection.stage3.memoryContextSummary?.missingEvidence.join(" / ") || ""}>
                        {lang === "zh" ? "已用记忆" : "memory used"} {experimentLifecycleProjection.stage3.memoryContextSummary?.knowledgeItemCount ?? 0}
                        {" · "}{lang === "zh" ? "禁重" : "blocked repeats"} {experimentLifecycleProjection.stage3.memoryContextSummary?.forbiddenDuplicateExperimentCount ?? 0}
                      </span>
                    </div>
                    {renderResearchMemoryContextDetails(experimentLifecycleProjection.stage3.memoryContextSummary, "iteration")}
                  </>
                ) : (
                  <em>{navItem ? (lang === "zh" ? navItem.zhModules : navItem.enModules) : ""}</em>
                )}
                {renderResearchStageAgentSummary(stageType)}
                <div className={styles.researchStageActions}>
                  {challengeProgramProjection ? (
                    <a href={stageType === "knowledge_collection"
                      ? "#challenge-mvp-sample"
                      : stageType === "experiment"
                        ? "#challenge-mvp-trials"
                        : "#challenge-mvp-roadmap"}
                    >
                      <Eye size={13} />
                      {stageType === "knowledge_collection"
                        ? (lang === "zh" ? "查看黄金样例" : "View golden sample")
                        : stageType === "experiment"
                          ? (lang === "zh" ? "查看试运行结果" : "View trial results")
                          : (lang === "zh" ? "查看后续范围" : "View post-MVP scope")}
                    </a>
                  ) : stageType === "knowledge_collection" ? (
                    <VNativeButton
                      type="button"
                      onClick={() => void runKnowledgeCollectionLoopAction()}
                      disabled={sourceCollectionLoopActionDisabled}
                      title={sourceCollectionActionDisabledTitle(sourceCollectionLoopActionReadiness, sourceCollectionLoopActionLabel)}
                    >
                      {sourceCollectionLoopStartsNewRun ? <Play size={13} /> : <CheckCircle2 size={13} />}
                      {sourceCollectionLoopActionLabel}
                    </VNativeButton>
                  ) : (
                    <VNativeButton
                      type="button"
                      onClick={() => runStagePrimaryAction(stageType)}
                      disabled={disabled}
                      title={primaryLabel}
                    >
                      <Play size={13} />
                      {primaryLabel}
                    </VNativeButton>
                  )}
                  {!challengeProgramProjection ? (
                    <Link to={researchWorkspaceStageRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID, stageType)}>
                      <Link2 size={13} />
                      {stageType === "knowledge_collection"
                        ? (lang === "zh" ? "手动控制" : "Manual controls")
                        : (lang === "zh" ? "阶段详情" : "Details")}
                    </Link>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
        {renderChallengeProgramResults()}
        {selectedTeamStartResearchStageError ? (
          <div className={styles.workflowError}>{selectedTeamStartResearchStageError.message}</div>
        ) : null}
        {selectedTeamStartResearchStageResult?.stageRound ? (
          <div className={styles.workflowSuccess}>
            {researchStageStartFeedbackText(
              selectedTeamStartResearchStageResult,
              lang,
              researchWorkspaceViewLabel(selectedTeamStartResearchStageResult.stageRound.stageType as ResearchStageWorkspaceView, lang),
            )}
          </div>
        ) : null}
        </>
        )}
      </section>
    );

}
