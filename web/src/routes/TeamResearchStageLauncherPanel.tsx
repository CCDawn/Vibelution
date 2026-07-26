/**
 * Research stage launcher console (three-stage + Challenge Cup branch).
 * Wave 8H: extracted from TeamsRoute.tsx for domain componentization.
 * Presentation + local pure helpers; mutations/query objects injected by the route.
 */
import type { ReactNode } from "react";
import { CheckCircle2, Eye, Link2, Play, RefreshCw, Settings2 } from "lucide-react";
import type { NavigateFunction } from "react-router-dom";
import { Link } from "react-router-dom";

import type { ExperimentMethodId, Team } from "../api/types";
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


    if (!researchWorkflowTeamSelected) {
      return null;
    }
    if (challengeCupResearchTeamSelected) {
      const challengeProjection = experimentPlanningStatus?.challengeProgramProjection;
      const challengeTeamId = selectedTeam?.teamId || RESEARCH_TEAM_ID;
      const challengeAgents: ChallengeCupWorkspaceAgent[] = selectedTeamMemoryMembers.map((member) => {
        const normalizedRole = member.roleLabel.toLowerCase();
        const workspace = normalizedRole.includes("source") || normalizedRole.includes("璧勬枡")
          ? "璇佹嵁閾?
          : normalizedRole.includes("knowledge") || normalizedRole.includes("鐭ヨ瘑")
            ? "鐭ヨ瘑搴?
            : normalizedRole.includes("experiment") || normalizedRole.includes("瀹為獙")
              ? "棰樼洰涓庣粨鏋?
              : normalizedRole.includes("iteration") || normalizedRole.includes("鐗堟湰")
                ? "娣辩爺杩唬"
                : "鍏ㄥ眬";
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
                setPreferredExperimentMethod((project.experimentMethod || "") as ExperimentMethodId | "");
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
        label: lang === "zh" ? "鐭ヨ瘑鎼滈泦" : "Knowledge",
        primaryAction: lang === "zh" ? "寮€濮嬬煡璇嗘悳闆? : "Start knowledge",
      },
      experiment: {
        label: lang === "zh" ? "瀹為獙璁捐" : "Experiment design",
        primaryAction: lang === "zh" ? "鍚姩璁捐" : "Start design",
      },
      iteration: {
        label: lang === "zh" ? "鎵ц涓庤凯浠? : "Execution & iteration",
        primaryAction: lang === "zh" ? "鍚姩鎵ц杩唬" : "Start execution",
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
        ? (lang === "zh" ? "寮€濮嬫墿鍏? : "Start expansion")
        : (lang === "zh" ? "寮€濮嬬煡璇嗘悳闆? : "Start knowledge")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
          ? (lang === "zh" ? "鎼滅储涓? : "Searching")
          : (lang === "zh" ? "鎼滅储涓嬩竴鎵? : "Search next batch"))
        : sourceCollectionDownstreamOpenAssignmentCount > 0
          ? (lang === "zh" ? "杩涘叆闃舵璇︽儏" : "Open stage details")
        : sourceCollectionRunPendingScreeningCount > 0
          ? (lang === "zh" ? "杩涘叆璧勬枡鎻愮偧澶嶆牳" : "Open review")
          : (lang === "zh" ? "杩涘叆鎼滈泦宸ヤ綔鍙? : "Open collection workspace");
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
      ? (lang === "zh" ? "鎵ц鍣ㄥ彲鐢? : "Adapter ready")
      : selectedExperimentAdapterStatus === "select_required"
        ? (lang === "zh" ? "闇€閫夋嫨鎵ц鍣? : "Select an adapter")
        : selectedExperimentAdapterStatus === "not_required"
          ? (lang === "zh" ? "鏃犻渶鎵ц鍣? : "Adapter not required")
          : (lang === "zh" ? "鎵ц鍣ㄩ樆濉? : "Adapter blocked");
    const selectedExperimentAdapterReason = selectedExperimentAdapterStatus === "ready"
      ? `${selectedExperimentAdapter?.resolvedAdapterId} 路 ${selectedExperimentAdapter?.selectionSource}`
      : selectedExperimentAdapterStatus === "select_required"
        ? (lang === "zh"
          ? `宸插彂鐜?${selectedExperimentRegisteredAdapters.length} 涓彲鐢ㄦ墽琛屽櫒锛岃繘鍏ラ厤缃〉鍚庢槑纭€夋嫨銆俙
          : `${selectedExperimentRegisteredAdapters.length} available adapter(s); choose one in setup.`)
        : selectedExperimentAdapterStatus === "not_required"
          ? (lang === "zh"
            ? "褰撳墠闂幆鍙敓鎴愬亣璁句笌鐮旂┒璁″垝锛屼笉浼氬惎鍔ㄧ湡瀹炲疄楠屻€?
            : "This loop only generates hypotheses and a plan; no real experiment starts.")
          : (lang === "zh"
            ? `褰撳墠鈥?{selectedExperimentMethodDescriptor?.labelZh || selectedExperimentMethod}鈥濇病鏈夊凡娉ㄥ唽涓斿彲鐢ㄧ殑鎵ц鍣ㄣ€俙
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
        return lang === "zh" ? "MVP 瀹屾暣鏍蜂緥" : "MVP golden sample";
      }
      if (stageType === "experiment") {
        return lang === "zh" ? "3 棰橀€氱敤鎬ф祴璇? : "Three-question validation";
      }
      return lang === "zh" ? "鍚庣画瑙勬ā鍖栦笌娣辩爺" : "Later scale-up and deep research";
    };
    const stageStatusLabel = (stageType: ResearchStageType, active: boolean, latestRound: ResearchStagePhaseStatus["latestRound"] | null | undefined) => {
      if (challengeProgramProjection) {
        if (stageType === "knowledge_collection") {
          const stage1 = challengeProgramProjection.stage1ComplianceReadiness;
          if (stage1.blockers.includes("dashscope_qwen_provider_missing")) {
            return lang === "zh" ? "BLOCKED 路 寰呴厤缃? : "BLOCKED 路 configuration required";
          }
          if (stage1.blockers.includes("dashscope_qwen_call_evidence_missing")) {
            return lang === "zh" ? "BLOCKED 路 寰呴獙璇? : "BLOCKED 路 validation required";
          }
          return stage1.singleQuestionSample.completed >= stage1.singleQuestionSample.required
            ? (lang === "zh" ? "宸插畬鎴? : "completed")
            : (lang === "zh" ? "寰呮敹鍙? : "pending");
        }
        if (stageType === "experiment") {
          const stage1 = challengeProgramProjection.stage1ComplianceReadiness;
          if (stage1.singleQuestionSample.completed < stage1.singleQuestionSample.required) {
            return lang === "zh" ? "绛夊緟瀹屾暣鏍蜂緥" : "waiting for golden sample";
          }
          return stage1.trialRun.completed >= stage1.trialRun.required
            ? challengeTrialReviewRequiredCount > 0
              ? (lang === "zh" ? "鏈哄櫒楠岃瘉瀹屾垚 路 寰呬汉宸ユ娊妫€" : "machine checks complete 路 human review pending")
              : (lang === "zh" ? "楠岃瘉瀹屾垚" : "validation complete")
            : (lang === "zh" ? "寰呮祴璇? : "pending");
        }
        return lang === "zh" ? "MVP 鍚庡啀鍚姩" : "deferred until after MVP";
      }
      if (stageType === "knowledge_collection") {
        return knowledgeCollectionStatusLabel;
      }
      if (stageType === "experiment" && experimentLifecycleProjection?.stage2) {
        if (experimentLifecycleProjection.stage2.status === "frozen") {
          return lang === "zh" ? "宸茶璁?路 寰呮墽琛? : "designed 路 ready";
        }
        if (experimentLifecycleProjection.stage2.status === "draft") {
          return lang === "zh" ? "璁捐涓? : "designing";
        }
      }
      if (stageType === "iteration" && experimentLifecycleProjection?.stage3) {
        return researchIterationLifecycleStatusLabel(experimentLifecycleProjection.stage3.status, lang);
      }
      if (stageStatusLoading) {
        return lang === "zh" ? "鐘舵€佸悓姝ヤ腑" : "Syncing status";
      }
      if (stageStatusUnavailable) {
        return lang === "zh" ? "鐘舵€佹殏涓嶅彲鐢? : "Status unavailable";
      }
      if (active) {
        return lang === "zh" ? "杩愯涓? : "running";
      }
      if (latestRound) {
        return lang === "zh" ? "宸叉湁杞" : "has round";
      }
      return lang === "zh" ? "鏈惎鍔? : "not started";
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
            ? (lang === "zh" ? "鍏堟妸 1 棰樺畬鏁磋窇閫氾細鐪熷疄妯″瀷璋冪敤銆佽瘉鎹€佸亣璁俱€佷竷缁村鏌ャ€佺爺绌惰鍒掑拰鍥涗釜浜哄伐闂ㄧ鍧囧彲杩借釜銆? : "Complete one end-to-end sample with a real model call, evidence, hypotheses, review, plan, and human gates.")
            : (lang === "zh" ? "缂哄皯 DashScope/Qwen 姝ｅ紡 provider锛涘彧鍏佽濂戠害娴嬭瘯鍜屾牱渚嬭崏绋匡紝绂佹鍐掑厖鐪熷疄璋冪敤銆? : "DashScope/Qwen provider is missing; only contract tests and drafts are allowed.");
        }
        if (stageType === "experiment") {
          return lang === "zh"
            ? "瀹屾暣鏍蜂緥閫氳繃鍚庯紝鍐嶇敤 3 涓笉鍚屽満鏅楠岃瘉鍙噸澶嶆€с€佽法棰嗗煙鑳藉姏鍜岀己璇佹嵁鏃剁殑姝ｇ‘闃诲銆?
            : "After the golden sample, validate repeatability, cross-domain behavior, and explicit evidence blocking on three questions.";
        }
        return lang === "zh"
          ? "125 棰樻壒璺戙€佷笁涓繁鐮旀渚嬪拰鏈€缁堝弬璧涘皝瑁呭潎寤跺悗鍒?MVP 楠屾敹涔嬪悗锛屼笉璁″叆鏈疆瀹屾垚鏉′欢銆?
          : "The 125-question run, three deep cases, and submission package are deferred until after MVP acceptance.";
      }
      if (stageType === "knowledge_collection") {
        if (!selectedSourceCollectionRun) {
          return lang === "zh" ? "鐢熸垚鎼滅储璁″垝鍜屽洟闃熷垎宸ワ紝鍏堟妸璧勬枡鎼滅储璺戣捣鏉ャ€? : "Create the search plan and team assignments.";
        }
        if (selectedTeamExecuteSourceCollectionSearchPending) {
          return lang === "zh" ? "姝ｅ湪鎵ц鎼滅储锛岀粨鏋滀細鍐欏叆璧勬枡璁板綍鍜屽€欓€夎祫鏂欎粨搴撱€? : "Searching now; results will be written into DataRecords and candidates.";
        }
        if (sourceCollectionSearchOpenAssignmentCount > 0) {
          return lang === "zh" ? "杩樻湁鎼滅储浠诲姟锛屽彲缁х画璺戜笅涓€鎵广€? : "Search tasks are ready for another batch.";
        }
        if (sourceCollectionDownstreamOpenAssignmentCount > 0) {
          return lang === "zh" ? "鎼滅储宸插仠锛屽悗缁繘鍏ユ彁鐐兼垨绛涢€夈€? : "Search is idle; extraction or screening is next.";
        }
        if (sourceCollectionRunPendingScreeningCount > 0) {
          return lang === "zh" ? "宸叉湁鍊欓€夎祫鏂欙紝涓嬩竴姝ヨ繘鍏ョ瓫閫夈€? : "Candidate sources are ready for screening.";
        }
        return lang === "zh" ? "鏈疆鍙ˉ鍏呮悳闆嗭紝鎴栫敱鐢ㄦ埛鍐冲畾杩涘叆瀹為獙銆? : "Add another collection round or move to experiments.";
      }
      if (stageType === "experiment") {
        if (experimentLifecycleProjection?.stage2.status === "frozen") {
          return lang === "zh"
            ? "瀹為獙璁捐宸插喕缁擄紱璁粌缁撴灉涓嶅弬涓庢湰闃舵瀹屾垚鍒ゅ畾銆?
            : "The design is frozen; training results do not determine Stage 2 completion.";
        }
        if (active) {
          return lang === "zh" ? "琛ラ綈鍋囪銆佸彉閲忋€佹帶鍒剁粍銆侀绠椼€佹寚鏍囦笌鎵ц闂ㄧ銆? : "Complete hypotheses, variables, controls, budget, metrics, and gates.";
        }
        return latestRound
          ? (lang === "zh" ? "鍙噸鏂拌鍒掑疄楠岋紝鎴栨煡鐪嬩笂涓€杞鍒掋€? : "Replan or review the latest plan.")
          : (lang === "zh" ? "鐭ヨ瘑鎼滈泦鍚庯紝鐢辩敤鎴峰喅瀹氬惎鍔ㄥ疄楠岃鍒掋€? : "Start experiment planning after collection.");
      }
      if (experimentLifecycleProjection?.stage3.status === "accepted_for_writeup") {
        return lang === "zh"
          ? "鏈€浣崇増鏈凡閫氳繃璇勪及锛涙渶杩戣瘖鏂崟鐙睍绀猴紝涓嶈鐩栦富绾跨粨鏋溿€?
          : "The best version passed review; diagnostics remain separate from the main result.";
      }
      if (active) {
        return lang === "zh" ? "鎸夊喕缁撹璁℃墽琛屻€佽瘎浼般€佸綊鍥犲苟鍙楁帶杩唬銆? : "Execute the frozen design, evaluate, diagnose, and iterate under control.";
      }
      return latestRound
        ? (lang === "zh" ? "鍙紑鍚柊涓€杞紭鍖栵紝娌夋穩浜や粯璁″垝銆? : "Start another optimization round and prepare delivery.")
        : (lang === "zh" ? "鍐荤粨瀹為獙璁捐鍚庤繘鍏ユ墽琛屻€佷紭鍖栧拰杩唬銆? : "Enter execution and iteration after the design is frozen.");
    };
    const currentStageLabel = researchStageRoundStatus?.currentStage
      ? researchWorkspaceViewLabel(researchStageRoundStatus.currentStage as ResearchStageWorkspaceView, lang)
      : lang === "zh" ? "寰呭惎鍔? : "not started";
    const renderChallengeProgramResults = () => {
      if (!challengeProgramProjection) {
        return null;
      }
      const stage1 = challengeProgramProjection.stage1ComplianceReadiness;
      const goldenSampleApproved = stage1.acceptance.allFourHumanGatesApproved;
      const deepCase = challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0];
      const deepCaseStatus = deepCase?.internalStatus === "accepted_for_writeup"
        ? (lang === "zh" ? "妗堜緥鍐呴儴宸查€氳繃鎾板啓瀹℃煡" : "case accepted for write-up")
        : deepCase?.internalStatus || (lang === "zh" ? "灏氭湭鍚姩" : "not started");
      return (
        <section
          id="challenge-mvp-results"
          className={styles.challengeProgramResults}
          aria-labelledby="challenge-mvp-results-title"
        >
          <header className={styles.challengeProgramResultsHeader}>
            <div>
              <strong id="challenge-mvp-results-title">{lang === "zh" ? "MVP 楠屾敹缁撴灉" : "MVP acceptance results"}</strong>
              <span>
                {lang === "zh"
                  ? `鏈哄櫒楠岃瘉 ${stage1.mvpManifest.completedQuestionCount}/${stage1.mvpManifest.requiredQuestionCount}锛涗汉宸ュ鏍镐笌鏈哄櫒楠岃瘉鍒嗗紑璁板綍`
                  : `Machine validation ${stage1.mvpManifest.completedQuestionCount}/${stage1.mvpManifest.requiredQuestionCount}; human review is tracked separately`}
              </span>
            </div>
            <span className={`${styles.researchStageStatus} ${styles.researchStageStatusRecorded}`}>
              {lang === "zh" ? "MVP 鍙獙鏀? : "MVP ready for acceptance"}
            </span>
          </header>
          <div className={styles.challengeProgramResultGrid}>
            <article id="challenge-mvp-sample" className={styles.challengeProgramResultCard}>
              <header>
                <strong>{lang === "zh" ? "瀹屾暣鏍蜂緥" : "Golden sample"}</strong>
                <span className={`${styles.researchStageStatus} ${goldenSampleApproved ? styles.researchStageStatusRecorded : styles.researchStageStatusPending}`}>
                  {goldenSampleApproved
                    ? (lang === "zh" ? "浜哄伐瀹℃牳閫氳繃" : "human review approved")
                    : (lang === "zh" ? "寰呬汉宸ュ鏍? : "human review pending")}
                </span>
              </header>
              <div className={styles.challengeProgramQuestionList}>
                <span>{stage1.mvpManifest.goldenSampleQuestionId}</span>
              </div>
              <p>
                {lang === "zh"
                  ? `Schema銆佸紩鐢ㄣ€佷竷缁村鏌ヤ笌鐮旂┒璁″垝鍧囧凡璁板綍锛涘弽棣堜慨璁?${stage1.acceptance.feedbackRevisionCount} 娆°€俙
                  : `Schema, citations, seven-dimension review, and the research plan are recorded; ${stage1.acceptance.feedbackRevisionCount} feedback revision(s).`}
              </p>
            </article>
            <article id="challenge-mvp-trials" className={styles.challengeProgramResultCard}>
              <header>
                <strong>{lang === "zh" ? "涓夐閫氱敤鎬ф祴璇? : "Three-question validation"}</strong>
                <span className={`${styles.researchStageStatus} ${challengeTrialReviewRequiredCount > 0 ? styles.researchStageStatusPending : styles.researchStageStatusRecorded}`}>
                  {challengeTrialReviewRequiredCount > 0
                    ? (lang === "zh" ? `寰呬汉宸ユ娊妫€ ${challengeTrialReviewRequiredCount}` : `${challengeTrialReviewRequiredCount} awaiting human review`)
                    : (lang === "zh" ? "瀹℃牳瀹屾垚" : "review complete")}
                </span>
              </header>
              <div className={styles.challengeProgramQuestionList}>
                {stage1.mvpManifest.testQuestionIds.map((questionId) => <span key={questionId}>{questionId}</span>)}
              </div>
              <p>
                {lang === "zh"
                  ? `鏈哄櫒楠岃瘉 ${stage1.trialRun.completed}/${stage1.trialRun.required}锛涗汉宸ュ凡鎵瑰噯 ${challengeTrialApprovedCount}锛屽叾浣欎繚鎸佸緟瀹℃牳锛屼笉璁′綔姝ｅ紡浜哄伐閫氳繃銆俙
                  : `Machine validation ${stage1.trialRun.completed}/${stage1.trialRun.required}; ${challengeTrialApprovedCount} human-approved, with the remainder explicitly pending.`}
              </p>
            </article>
            <article id="challenge-mvp-roadmap" className={styles.challengeProgramResultCard}>
              <header>
                <strong>{lang === "zh" ? "MVP 鍚庣画鑼冨洿" : "Post-MVP scope"}</strong>
                <span className={`${styles.researchStageStatus} ${styles.researchStageStatusPending}`}>
                  {lang === "zh" ? "鏆傜紦" : "deferred"}
                </span>
              </header>
              <p>{lang === "zh" ? "125 棰樻壒璺戜笌涓夋渚嬫繁鐮斾笉璁″叆鏈疆 MVP 瀹屾垚鏉′欢銆? : "The 125-question run and three deep cases are outside this MVP."}</p>
              <p>
                {deepCase
                  ? `${deepCase.title} 路 ${deepCaseStatus}`
                  : (lang === "zh" ? "褰撳墠娌℃湁宸茬櫥璁扮殑浠ｈ〃鎬ф繁鐮旀渚嬨€? : "No representative deep-research case is registered.")}
              </p>
            </article>
          </div>
        </section>
      );
    };
    return (
      <section
        className={styles.researchStageLauncher}
        aria-label={lang === "zh" ? "绉戠爺鎺у埗鍙? : "Research console"}
        aria-busy={challengeProgramLoading}
        aria-live="polite"
      >
        <div className={styles.researchStageLauncherHeader}>
          <div>
            <strong>{challengeProgramProjection?.program.title || (lang === "zh" ? "绉戠爺鎺у埗鍙帮紙涓夐樁娈碉級" : "Research console (3 stages)")}</strong>
            <span>
              {challengeProgramProjection
                ? `${challengeProgramProjection.program.officialProblemId} 路 ${challengeProgramProjection.program.track}`
                : researchStageRoundStatus
                ? `${lang === "zh" ? "褰撳墠闃舵" : "Current"} 路 ${currentStageLabel}`
                : researchStageRoundStatusQuery.isPending
                ? (lang === "zh" ? "璇诲彇闃舵鐘舵€佷腑" : "Loading stage status")
                : (lang === "zh" ? "閫夋嫨涓€涓樁娈靛紑濮? : "Choose a stage to start")}
            </span>
          </div>
          <div className={styles.researchStageHeaderActions}>
            <Link to={researchCanvasRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}>
              <Eye size={13} />
              {lang === "zh" ? "鐮旂┒鍏崇郴鍥? : "Research graph"}
            </Link>
            <VNativeButton type="button" onClick={() => void researchStageRoundStatusQuery.refetch()} disabled={researchStageRoundStatusQuery.isFetching} title={lang === "zh" ? "鍒锋柊闃舵鐘舵€? : "Refresh stage status"}>
              <RefreshCw size={13} />
            </VNativeButton>
          </div>
        </div>
        {researchTeamDetailDegraded ? (
          <div className={styles.researchStageDegradedNotice} role="status">
            <span>{selectedTeamDetailLoading
              ? (lang === "zh" ? "姝ｅ湪琛ラ綈鍥㈤槦璇︽儏锛涚鐮旈樁娈电姸鎬佷粛鍙嫭绔嬭鍙栥€? : "Loading team details; research stage status remains available.")
              : (lang === "zh" ? "鍥㈤槦璇︽儏鏆傛椂涓嶅彲鐢紱褰撳墠淇濈暀宸茶鍙栫殑绉戠爺鐘舵€併€? : "Team details are temporarily unavailable; loaded research state is retained.")}
            </span>
            <VNativeButton type="button" onClick={() => void teamDetailQuery.refetch()} disabled={teamDetailQuery.isFetching}>
              <RefreshCw size={13} />
              {lang === "zh" ? "閲嶈瘯璇︽儏" : "Retry details"}
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
            <strong>{lang === "zh" ? "褰撳墠鑼冨洿锛? 涓畬鏁存牱渚?+ 3 涓€氱敤鎬ф祴璇? : "Current scope: 1 golden sample + 3 validation questions"}</strong>
            <span>{lang === "zh" ? "125 棰樿妯″寲涓庝笁妗堜緥娣辩爺宸叉槑纭欢鍚? : "125-question scale-up and three deep cases are explicitly deferred"}</span>
          </div>
        ) : challengeProgramExpected ? null : (
          <label className={styles.researchStageTopicInput}>
            <span>{lang === "zh" ? "鐮旂┒涓婚" : "Research topic"}</span>
            <VNativeInput
              value={sourceCollectionDraft.topic}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, topic: event.target.value }))}
              placeholder={lang === "zh" ? "渚嬪锛歱redictive coding" : "e.g. predictive coding"}
            />
          </label>
        )}
        {challengeProgramLoading ? (
          <div className={styles.researchStageDegradedNotice} role="status">
            <span>{lang === "zh" ? "姝ｅ湪璇诲彇鎸戞垬鏉?MVP 鐘舵€侊紝涓嶄細鏄剧ず鏃х鐮旀祦绋嬨€? : "Loading the Challenge Cup MVP state without falling back to the legacy workflow."}</span>
          </div>
        ) : challengeProgramUnavailable ? (
          <div className={styles.researchStageDegradedNotice} role="alert">
            <span>{lang === "zh" ? "鎸戞垬鏉?MVP 鐘舵€佹殏涓嶅彲鐢紱鏃х鐮旀祦绋嬪凡淇濇寔闅愯棌锛岄伩鍏嶄骇鐢熼敊璇搷浣溿€? : "The Challenge Cup MVP state is unavailable; the legacy workflow remains hidden to prevent incorrect actions."}</span>
            <VNativeButton type="button" onClick={() => void experimentPlanningStatusQuery.refetch()} disabled={experimentPlanningStatusQuery.isFetching}>
              <RefreshCw size={13} />
              {lang === "zh" ? "閲嶈瘯" : "Retry"}
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
                      <span>{lang === "zh" ? "瀹為獙鏂瑰紡" : "Experiment method"}</span>
                      <VNativeSelect
                        value={selectedExperimentMethod}
                        onChange={(event) => setPreferredExperimentMethod(event.target.value as ExperimentMethodId | "")}
                        disabled={experimentMethodCatalogQuery.isFetching || !experimentMethodCatalogQuery.data}
                        aria-label={lang === "zh" ? "閫夋嫨瀹為獙鏂瑰紡" : "Select experiment method"}
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
                          ? `${selectedExperimentMethodDescriptor.requiredConfigFields.length} ${lang === "zh" ? "椤归厤缃? : "fields"}`
                          : (experimentMethodCatalogQuery.isFetching
                            ? (lang === "zh" ? "璇诲彇鏂瑰紡涓? : "Loading methods")
                            : (lang === "zh" ? "鏂瑰紡鐩綍涓嶅彲鐢? : "Method catalog unavailable"))}
                      </span>
                      <span className={["ready", "not_required"].includes(selectedExperimentAdapterStatus) ? styles.researchExperimentMethodReady : styles.researchExperimentMethodPending}>
                        {selectedExperimentAdapterLabel}
                      </span>
                      <Link to={selectedExperimentMethodRoute}>
                        <Settings2 size={13} />
                        {lang === "zh" ? "閰嶇疆鏂规硶" : "Configure"}
                      </Link>
                    </div>
                    <p className={styles.researchExperimentMethodReason}>{selectedExperimentAdapterReason}</p>
                    {selectedExperimentAdapterStatus === "blocked" && executableAlternativeMethods.length > 0 ? (
                      <div className={styles.researchExperimentMethodAlternatives}>
                        <span>{lang === "zh" ? "鍙墽琛屾浛浠? : "Executable alternatives"}</span>
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
                        <span>{lang === "zh" ? "鐪熷疄鏍蜂緥" : "real sample"} {challengeProgramProjection.stage1ComplianceReadiness.singleQuestionSample.completed}/{challengeProgramProjection.stage1ComplianceReadiness.singleQuestionSample.required}</span>
                        <span>{lang === "zh" ? "鐧剧偧璇佹嵁" : "DashScope evidence"} {challengeProgramProjection.stage1ComplianceReadiness.officialModelCallEvidence.count}</span>
                        <span>{lang === "zh" ? "浜哄伐瀹℃牳" : "human review"} {challengeProgramProjection.stage1ComplianceReadiness.acceptance.allFourHumanGatesApproved ? (lang === "zh" ? "閫氳繃" : "approved") : (lang === "zh" ? "寰呭鐞? : "pending")}</span>
                        <span>{lang === "zh" ? "鐙珛缁村害" : "dimensions"} {challengeProgramProjection.stage1ComplianceReadiness.independentEvaluationDimensions.length} 路 {lang === "zh" ? "浜哄伐闂ㄧ" : "human gates"} {challengeProgramProjection.stage1ComplianceReadiness.humanGates.length}</span>
                      </>
                    ) : stageType === "experiment" ? (
                      <>
                        <span>{lang === "zh" ? "娴嬭瘯棰? : "test questions"} {challengeProgramProjection.stage1ComplianceReadiness.trialRun.completed}/{challengeProgramProjection.stage1ComplianceReadiness.trialRun.required}</span>
                        <span>{lang === "zh" ? "浜哄伐鎶芥" : "human review"} {challengeTrialReviewRequiredCount > 0 ? (lang === "zh" ? `寰?${challengeTrialReviewRequiredCount}` : `${challengeTrialReviewRequiredCount} pending`) : (lang === "zh" ? "瀹屾垚" : "complete")}</span>
                        <span>{lang === "zh" ? "MVP 鎬昏繘搴? : "MVP progress"} {challengeProgramProjection.stage1ComplianceReadiness.mvpManifest.completedQuestionCount}/{challengeProgramProjection.stage1ComplianceReadiness.mvpManifest.requiredQuestionCount}</span>
                        <span>{lang === "zh" ? "瑙勬ā鍖? : "scale-up"} {lang === "zh" ? "宸插欢鍚? : "deferred"}</span>
                      </>
                    ) : (
                      <>
                        <span>{lang === "zh" ? "125 棰樻壒璺? : "125-question run"} 路 {lang === "zh" ? "鏆傜紦" : "deferred"}</span>
                        <span>{lang === "zh" ? "娣辩爺妗堜緥" : "deep cases"} {challengeProgramProjection.stage3DeepResearchDelivery.representativeCaseCount}/{challengeProgramProjection.stage3DeepResearchDelivery.requiredRepresentativeCaseCount}</span>
                        <span title={challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.claimBoundary || ""}>
                          {challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.title || (lang === "zh" ? "鍗曟渚? : "case")} 路 {challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.internalStatus === "accepted_for_writeup"
                            ? (lang === "zh" ? "妗堜緥鍐呴儴宸查€氳繃鎾板啓瀹℃煡" : "case accepted for write-up")
                            : challengeProgramProjection.stage3DeepResearchDelivery.caseRecords[0]?.internalStatus || "-"}
                        </span>
                      </>
                    )}
                  </div>
                ) : stageType === "knowledge_collection" && selectedSourceCollectionRun ? (
                  <div className={styles.researchStageCardMetrics}>
                    <span>{sourceCollectionRunLabel(selectedSourceCollectionRun.runId)}</span>
                    <span>{lang === "zh" ? `鍙悳绱?${sourceCollectionSearchOpenAssignmentCountText}` : `search ${sourceCollectionSearchOpenAssignmentCountText}`}</span>
                    <span>{lang === "zh" ? `鍚庣画 ${sourceCollectionDownstreamOpenAssignmentCountText}` : `next ${sourceCollectionDownstreamOpenAssignmentCountText}`}</span>
                    <span>{lang === "zh" ? `鍘熷 ${sourceCollectionCollectedCountText}` : `raw ${sourceCollectionCollectedCountText}`}</span>
                    <span>{lang === "zh" ? `鍊欓€?${sourceCollectionDisplayedCandidateCountText}` : `candidates ${sourceCollectionDisplayedCandidateCountText}`}</span>
                    <span>{lang === "zh" ? `鏌ヨ ${sourceCollectionQueryCountText}` : `queries ${sourceCollectionQueryCountText}`}</span>
                  </div>
                ) : stageType === "experiment" && experimentLifecycleProjection?.stage2 ? (
                  <>
                    <div className={styles.researchStageCardMetrics}>
                      <span>{lang === "zh" ? `鍐荤粨璁捐 v${experimentLifecycleProjection.stage2.frozenDesignRevision || "-"}` : `frozen v${experimentLifecycleProjection.stage2.frozenDesignRevision || "-"}`}</span>
                      <span title={experimentLifecycleProjection.stage2.activeDesignPlanId}>
                        {lang === "zh" ? "褰撳墠璁捐" : "design"} {experimentLifecycleProjection.stage2.activeDesignPlanId || "-"}
                      </span>
                      <span>{experimentLifecycleProjection.stage2.readyForExecution ? (lang === "zh" ? "鍙墽琛? : "executable") : (lang === "zh" ? "寰呭喕缁? : "not frozen")}</span>
                      <span title={experimentLifecycleProjection.stage2.memoryContextSummary?.missingEvidence.join(" / ") || ""}>
                        {lang === "zh" ? "鍥㈤槦璁板繂" : "memory"} {experimentLifecycleProjection.stage2.memoryContextSummary?.knowledgeItemCount ?? 0}
                        {" 路 "}{lang === "zh" ? "璐熷悜" : "negative"} {experimentLifecycleProjection.stage2.memoryContextSummary?.negativeExperimentCount ?? 0}
                      </span>
                    </div>
                    {renderResearchMemoryContextDetails(experimentLifecycleProjection.stage2.memoryContextSummary, "experiment")}
                  </>
                ) : stageType === "iteration" && experimentLifecycleProjection?.stage3 ? (
                  <>
                    <div className={styles.researchStageCardMetrics}>
                      <span title={experimentLifecycleProjection.stage3.bestCandidateId}>
                        {lang === "zh" ? "鏈€浣冲€欓€? : "best"} {experimentLifecycleProjection.stage3.bestCandidateId || "-"}
                      </span>
                      <span title={experimentLifecycleProjection.stage3.bestValidatedResultId}>
                        {lang === "zh" ? "鏈€浣崇粨鏋? : "result"} {experimentLifecycleProjection.stage3.bestValidatedResultId || "-"}
                      </span>
                      <span title={experimentLifecycleProjection.stage3.latestDiagnosticStatus.title}>
                        {lang === "zh" ? "鏈€杩戣瘖鏂? : "diagnostic"} {experimentLifecycleProjection.stage3.latestDiagnosticStatus.status || "-"}
                      </span>
                      <span title={experimentLifecycleProjection.stage3.memoryContextSummary?.missingEvidence.join(" / ") || ""}>
                        {lang === "zh" ? "宸茬敤璁板繂" : "memory used"} {experimentLifecycleProjection.stage3.memoryContextSummary?.knowledgeItemCount ?? 0}
                        {" 路 "}{lang === "zh" ? "绂侀噸" : "blocked repeats"} {experimentLifecycleProjection.stage3.memoryContextSummary?.forbiddenDuplicateExperimentCount ?? 0}
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
                        ? (lang === "zh" ? "鏌ョ湅瀹屾暣鏍蜂緥" : "View golden sample")
                        : stageType === "experiment"
                          ? (lang === "zh" ? "鏌ョ湅娴嬭瘯缁撴灉" : "View test results")
                          : (lang === "zh" ? "鏌ョ湅鍚庣画鑼冨洿" : "View post-MVP scope")}
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
                        ? (lang === "zh" ? "鎵嬪姩鎺у埗" : "Manual controls")
                        : (lang === "zh" ? "闃舵璇︽儏" : "Details")}
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
