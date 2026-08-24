import { useCallback, useMemo, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import { VButton, VCanvasWorkbenchPage } from "../../../components/vui";
import {
  buildHypothesisFirstCanvasRegion,
  hypothesisFirstSemanticNodeId,
  isHypothesisReviewRetryAttempt,
  summarizeHypothesisReviewMeetings,
} from "./hypothesisFirstCanvasRegion";
import { ResearchCommandPalette } from "./ResearchCommandPalette";
import { ResearchCurrentTaskInspector } from "./ResearchCurrentTaskInspector";
import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";
import {
  isHypothesisFirstDiscussionActive,
  meetingsForHypothesisFirstQuestion,
  resolveHypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import {
  buildExperimentChromeIdentity,
  buildExperimentSwitchOptions,
  resolveExperimentSwitch,
} from "./researchExperimentSwitchModel";
import {
  composeHypothesisFirstGraph,
  definitionToCanvasGraph,
  projectionToCanvasGraph,
} from "./researchProcessGraphModel";
import { shouldShowResearchProcessInspector } from "./researchProcessPanelSelection";
import { ResearchProcessInspectorPane } from "./ResearchProcessInspectorPane";
import { ResearchWorkflowCanvasPane } from "./ResearchWorkflowCanvasPane";
import {
  buildResearchWorkflowStageNavigatorModel,
  ResearchWorkflowStageNavigator,
} from "./ResearchWorkflowStageNavigator";
import { ResearchWorkflowToolbar } from "./ResearchWorkflowToolbar";
import { buildResearchWorkflowContext } from "./researchWorkflowContextModel";
import { buildResearchWorkflowWorkspaceModel } from "./researchWorkflowWorkspaceModel";
import { buildResearchRunInput } from "./researchRunLaunchContract";
import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";
import { buildScopedDiscussionModel } from "./scopedDiscussionModel";
import type { ScopedDiscussionModel } from "./scopedDiscussionModel";
import {
  useHypothesisFirstChain,
  useHypothesisFirstChainInvalidation,
} from "./useHypothesisFirstChain";
import { useNodeDetailState } from "./useNodeDetailState";
import { useResearchWorkflowCatalog } from "./useResearchWorkflowCatalog";
import { useResearchWorkflowCommand } from "./useResearchWorkflowCommand";
import { useResearchWorkflowCommands } from "./useResearchWorkflowCommands";
import { useResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import { useResearchProcessAutofocus } from "./useResearchProcessAutofocus";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";
import { useResearchWorkflowWorkspace } from "./useResearchWorkflowWorkspace";
import styles from "./ResearchProcessWorkspace.styles";

export type ResearchProcessWorkspaceProps = {
  teamId: string;
  lang: "zh" | "en";
  teamName?: string;
  linkedChatRoomId?: string;
  /** Team switcher rendered in the process toolbar so chrome stays a single row. */
  toolbarLeading?: ReactNode;
  /** Opens the shared team communication surface without duplicating its mutations. */
  onOpenTeamCommunication?: () => void;
};

// Stable identity so the memoized canvas pane does not re-render when no run
// projection is loaded yet.
const EMPTY_RUNTIME_NODE_IDS: string[] = [];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * Read only the server's explicit activeDiscussionAnchor envelope. The formal
 * snapshot/projection and hypothesis-first chain can arrive through different
 * route adapters, so the same exact field is checked at their boundaries.
 * No linkedChatRoomId or sibling room is ever considered.
 */
function findActiveDiscussionAnchor(value: unknown): { found: boolean; value: unknown } {
  if (!isRecord(value)) return { found: false, value: undefined };
  if (Object.prototype.hasOwnProperty.call(value, "activeDiscussionAnchor")) {
    return { found: true, value: value.activeDiscussionAnchor };
  }
  for (const key of ["launchContext", "formalSnapshot", "run", "projection", "state"]) {
    const nested = findActiveDiscussionAnchor(value[key]);
    if (nested.found) return nested;
  }
  return { found: false, value: undefined };
}

function freshRetryIdempotencyKey(baseKey: string): string {
  const random = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `${baseKey}:fresh:${random}`;
}

export function ResearchProcessWorkspace({
  teamId,
  lang,
  teamName = "",
  linkedChatRoomId = "",
  toolbarLeading,
  onOpenTeamCommunication,
}: ResearchProcessWorkspaceProps) {
  const isZh = lang === "zh";
  const navigate = useNavigate();
  const location = useResearchWorkflowWorkspace(teamId);
  const runState = useResearchWorkflowRun(teamId, location.runId);
  const catalog = useResearchWorkflowCatalog(teamId, runState.run?.runVersion ?? null);
  const chainQuestionId = location.questionId || runState.run?.questionId || "";
  const hypothesisFirstChain = useHypothesisFirstChain(teamId, chainQuestionId);
  useHypothesisFirstChainInvalidation(teamId, chainQuestionId, runState.lastSequence);
  const activeDiscussionAnchor = useMemo(() => {
    for (const source of [
      runState.snapshot,
      runState.projection,
      runState.run,
      hypothesisFirstChain.chainState,
    ]) {
      const result = findActiveDiscussionAnchor(source);
      if (result.found) return result.value;
    }
    return undefined;
  }, [
    hypothesisFirstChain.chainState,
    runState.projection,
    runState.run,
    runState.snapshot,
  ]);
  const scopedDiscussionModel = useMemo<ScopedDiscussionModel>(
    () => buildScopedDiscussionModel({ anchor: activeDiscussionAnchor }),
    [activeDiscussionAnchor],
  );
  const navigateToDiscussion = useCallback((deepLink: string) => {
    if (!deepLink || scopedDiscussionModel.status !== "ready") return;
    navigate(deepLink);
  }, [navigate, scopedDiscussionModel.status]);
  const nodeDetail = useNodeDetailState(
    teamId,
    location.runId,
    location.selectedNodeId,
    runState.run?.runVersion ?? null,
  );
  const detail = nodeDetail.state.kind === "ready" ? nodeDetail.state.detail : null;
  const insights = useResearchWorkflowInsights(teamId, location.runId);
  const formalCommand = useResearchWorkflowCommand(
    teamId,
    location.runId,
    location.selectedNodeId,
  );
  const commands = useResearchWorkflowCommands({
    teamId,
    runId: location.runId,
    selectedNodeId: location.selectedNodeId,
    run: runState.run,
    nodeDetail: detail,
    commandOffers: runState.commandOffers,
    submitFormalOffer: formalCommand.submit,
    createRun: runState.createRun,
    refresh: runState.refresh,
    replaceParams: location.replaceParams,
  });

  const graph = useMemo(() => {
    if (!runState.projection) return null;
    const primaryAgentIdByNode = new Map(
      (catalog.effectiveBindings ?? [])
        .filter((binding) => Boolean(binding.agentId))
        .map((binding) => [binding.nodeId, binding.agentId]),
    );
    const base = location.runId
      ? projectionToCanvasGraph(runState.projection, { primaryAgentIdByNode })
      : definitionToCanvasGraph(runState.projection.definition, {
          primaryAgentIdByNode,
        });
    const region = buildHypothesisFirstCanvasRegion({
      chainState: hypothesisFirstChain.chainState,
      meetings: hypothesisFirstChain.meetings,
      collectionRequests: hypothesisFirstChain.collectionRequests,
      reviewRoundLinks: hypothesisFirstChain.reviewRoundLinks,
      selection: hypothesisFirstChain.selection,
    });
    return composeHypothesisFirstGraph(base, region, {
      demotePipelineStages: isHypothesisFirstDiscussionActive(
        meetingsForHypothesisFirstQuestion(hypothesisFirstChain.meetings, chainQuestionId),
      ),
    });
  }, [
    catalog.effectiveBindings,
    location.runId,
    runState.projection,
    hypothesisFirstChain.chainState,
    hypothesisFirstChain.meetings,
    hypothesisFirstChain.collectionRequests,
    hypothesisFirstChain.reviewRoundLinks,
    hypothesisFirstChain.selection,
    chainQuestionId,
  ]);

  const experimentIdentity = buildExperimentChromeIdentity({
    questionId: chainQuestionId,
    title: catalog.questions.find(
      (question) => question.questionId.toUpperCase() === chainQuestionId.toUpperCase(),
    )?.title ?? chainQuestionId,
    selectedCandidateIds: hypothesisFirstChain.selection?.selectedCandidateIds,
    chain: hypothesisFirstChain.chainState,
  });
  const experimentOptions = useMemo(() => {
    const currentRun = runState.run;
    if (!chainQuestionId) {
      return buildExperimentSwitchOptions({ questions: catalog.questions });
    }
    const currentNodeId = currentRun?.runtimeCurrentNodeIds?.[0] ?? "";
    const currentTitle = catalog.questions.find(
      (question) => question.questionId.toUpperCase() === chainQuestionId.toUpperCase(),
    )?.title;
    return buildExperimentSwitchOptions({
      questions: catalog.questions,
      current: {
        questionId: chainQuestionId,
        title: currentTitle,
        runId: currentRun?.runId ?? "",
        currentNodeId,
        selectedCandidateIds: hypothesisFirstChain.selection?.selectedCandidateIds,
        chain: hypothesisFirstChain.chainState,
      },
    });
  }, [
    catalog.questions,
    chainQuestionId,
    hypothesisFirstChain.chainState,
    hypothesisFirstChain.selection?.selectedCandidateIds,
    runState.run,
  ]);
  const selectExperiment = useCallback((questionId: string) => {
    const patch = resolveExperimentSwitch(experimentOptions, questionId);
    if (!patch) return;
    if (patch.panel !== "node") {
      location.replaceParams(patch);
      return;
    }
    void fetchHypothesisFirstFocusNode(teamId, patch.questionId).then((node) => {
      location.replaceParams({ ...patch, node });
    });
  }, [experimentOptions, location, teamId]);


  const formalRuntimeActive = Boolean(
    runState.snapshot?.run?.runId === location.runId && location.runId
  ) || Boolean(hypothesisFirstChain.chainState?.hypothesisConverged);
  const formalRuntimeCurrentNodeIds = formalRuntimeActive
    ? (runState.projection?.run.runtimeCurrentNodeIds ?? EMPTY_RUNTIME_NODE_IDS)
    : EMPTY_RUNTIME_NODE_IDS;
  // Hypothesis-first work can be started and progressed from a question deep
  // link before the formal 16-node workflow run exists. Keep this separate
  // from location.runId: the latter must remain the real run id.
  const workflowActive = Boolean(
    location.runId
    || hypothesisFirstChain.chainState
    || hypothesisFirstChain.selection
    || meetingsForHypothesisFirstQuestion(hypothesisFirstChain.meetings, chainQuestionId).length > 0
    || hypothesisFirstChain.collectionRequests.length > 0,
  );
  const hypothesisFirstReady = !hypothesisFirstChain.loading && !hypothesisFirstChain.scopeMismatch;
  // A hypothesis-first collection request owns its child-run status. Do not
  // let a formal pipeline node status mask an orphaned request recovery.
  const collectionChildStatus = hypothesisFirstChain.collectionRequests.length > 0
    ? null
    : (runState.projection?.run.nodeRuns.source_finding?.status ?? null);

  const nextAction = useMemo(() => resolveHypothesisFirstNextAction({
    run: runState.run
      ? {
          runId: runState.run.runId,
          runtimeCurrentNodeIds: formalRuntimeCurrentNodeIds,
        }
      : null,
    workflowActive,
    questionId: chainQuestionId,
    chainState: hypothesisFirstChain.chainState,
    meetings: hypothesisFirstChain.meetings,
    reviewRoundLinks: hypothesisFirstChain.reviewRoundLinks,
    selection: hypothesisFirstChain.selection,
    collectionRequests: hypothesisFirstChain.collectionRequests,
    collectionChildStatus,
    selectedNodeId: location.selectedNodeId,
  }), [
    hypothesisFirstChain.chainState,
    hypothesisFirstChain.collectionRequests,
    hypothesisFirstChain.meetings,
    hypothesisFirstChain.reviewRoundLinks,
    hypothesisFirstChain.selection,
    chainQuestionId,
    location.selectedNodeId,
    formalRuntimeCurrentNodeIds,
    collectionChildStatus,
    runState.run,
    workflowActive,
  ]);
  const safeNextAction = useMemo(() => {
    if (!hypothesisFirstChain.scopeMismatch) return nextAction;
    return {
      stage: "blocked" as const,
      targetNodeId: null,
      navigationLabel: "等待题目切换",
      disabledReason: "正在切换题目，旧任务和操作已隐藏",
      statusMessage: "正在切换题目",
      recovery: null,
    };
  }, [hypothesisFirstChain.scopeMismatch, nextAction]);
  // A formal run may already be staged while an unresolved hypothesis gate is
  // still the only visible/operable task. Use question-scoped evidence and the
  // resolved next action as the authority: meeting gates deliberately outrank
  // both an early convergence projection and ancillary queries that are still
  // loading. Otherwise a pending candidate confirmation is replaced by a
  // hidden formal node and cannot be located.
  const hypothesisFirstOwnsCurrentTask = !hypothesisFirstChain.scopeMismatch
    && safeNextAction.stage !== "converged"
    && Boolean(
      hypothesisFirstChain.chainState
      || hypothesisFirstChain.selection
      || meetingsForHypothesisFirstQuestion(hypothesisFirstChain.meetings, chainQuestionId).length > 0
      || hypothesisFirstChain.collectionRequests.length > 0,
    );
  const semanticSelectedNodeId = hypothesisFirstSemanticNodeId(location.selectedNodeId);
  const prospectiveCurrentTaskNodeId = runState.snapshot?.currentTask?.nodeId
    ?? safeNextAction.targetNodeId;
  const semanticProspectiveCurrentTaskNodeId = hypothesisFirstSemanticNodeId(
    prospectiveCurrentTaskNodeId,
  );
  const workspaceSelectedNodeId = location.panel === "node"
    && semanticSelectedNodeId
    && semanticSelectedNodeId === semanticProspectiveCurrentTaskNodeId
    ? prospectiveCurrentTaskNodeId
    : location.selectedNodeId;
  const displayError =
    commands.error
    || formalCommand.commandError
    || runState.error
    || catalog.error
    || hypothesisFirstChain.error;
  const commandBusy = runState.busy || commands.busy || formalCommand.busy;
  const workspaceModel = useMemo(() => buildResearchWorkflowWorkspaceModel({
    scope: {
      teamId,
      workflowId: CHALLENGE_CUP_WORKFLOW_ID,
      questionId: chainQuestionId || null,
      runId: hypothesisFirstOwnsCurrentTask ? null : location.runId || null,
      runVersion: hypothesisFirstOwnsCurrentTask
        ? null
        : runState.snapshot?.run.runVersion ?? runState.run?.runVersion ?? null,
    },
    snapshot: runState.snapshot,
    commandOffers: runState.commandOffers,
    legacyNextAction: safeNextAction,
    selectedNodeId: workspaceSelectedNodeId,
    panel: location.panel,
    loading: !hypothesisFirstReady || (!runState.projection && !displayError),
    error: displayError,
    resyncRequired: runState.resyncRequired,
  }), [
    chainQuestionId,
    displayError,
    hypothesisFirstReady,
    hypothesisFirstOwnsCurrentTask,
    location.panel,
    location.runId,
    workspaceSelectedNodeId,
    runState.commandOffers,
    runState.projection,
    runState.run?.runVersion,
    runState.resyncRequired,
    runState.snapshot,
    safeNextAction,
    teamId,
  ]);
  const workspaceNextAction = workspaceModel.source === "formal_runtime"
    ? undefined
    : workspaceModel.legacyNextAction || safeNextAction;
  const stageNavigatorModel = useMemo(() => buildResearchWorkflowStageNavigatorModel({
    graph,
    progress: workspaceModel.progress,
    currentTaskNodeId: workspaceModel.currentTask?.source === "formal_runtime"
      ? workspaceModel.currentTask.nodeId
      : workspaceModel.currentTask?.source === "hypothesis_first"
        ? workspaceModel.currentTask.targetNodeId
        : null,
    loadState: workspaceModel.loadState,
    scopeMismatch: workspaceModel.scopeMismatch,
    error: workspaceModel.error,
  }), [graph, workspaceModel]);
  const formalWritesPaused = workspaceModel.source === "formal_runtime" && (
    workspaceModel.resyncRequired
    || workspaceModel.loadState === "loading"
    || workspaceModel.loadState === "error"
    || !workspaceModel.currentTask
  );
  const workspaceNavigationAction = workspaceModel.source === "formal_runtime"
    ? {
        stage: "converged" as const,
        targetNodeId: !formalWritesPaused && workspaceModel.currentTask?.source === "formal_runtime"
          ? workspaceModel.currentTask.nodeId
          : null,
        navigationLabel: workspaceModel.currentTask?.source === "formal_runtime"
          ? workspaceModel.currentTask.label
          : "正在读取正式任务",
        statusMessage: undefined,
        recovery: null,
      }
    : safeNextAction;
  const semanticCurrentTaskNodeId = hypothesisFirstSemanticNodeId(
    workspaceNavigationAction.targetNodeId,
  );
  const navigateToCurrentTask = useCallback(() => {
    if (scopedDiscussionModel.status === "ready" && scopedDiscussionModel.deepLink) {
      navigateToDiscussion(scopedDiscussionModel.deepLink);
      return;
    }
    if (semanticCurrentTaskNodeId) {
      location.replaceParams({ node: semanticCurrentTaskNodeId, panel: "node" });
    }
  }, [
    location,
    navigateToDiscussion,
    scopedDiscussionModel.deepLink,
    scopedDiscussionModel.status,
    semanticCurrentTaskNodeId,
  ]);
  const replaceParamsForInspector = useCallback((patch: Record<string, string | null | undefined>) => {
    const requestedNode = typeof patch.node === "string" ? patch.node.trim() : "";
    const requestedSemanticNode = hypothesisFirstSemanticNodeId(requestedNode);
    if (
      patch.panel === "node"
      && requestedSemanticNode
      && requestedSemanticNode === semanticCurrentTaskNodeId
      && scopedDiscussionModel.status === "ready"
      && scopedDiscussionModel.deepLink
    ) {
      navigateToDiscussion(scopedDiscussionModel.deepLink);
      return;
    }
    location.replaceParams(patch);
  }, [
    location,
    navigateToDiscussion,
    scopedDiscussionModel.deepLink,
    scopedDiscussionModel.status,
    semanticCurrentTaskNodeId,
  ]);
  const archiveOpen = location.panel === "question";
  const scopedReviewMeetings = useMemo(() => hypothesisFirstChain.meetings
    .filter((meeting) => (
      meeting.meetingType === "hypothesis_review"
      && (!chainQuestionId
        || meeting.question.trim().toUpperCase() === chainQuestionId.trim().toUpperCase())
    ))
    .sort((left, right) => (left.roundIndex ?? 0) - (right.roundIndex ?? 0)), [
    chainQuestionId,
    hypothesisFirstChain.meetings,
  ]);
  const reviewSummary = useMemo(
    () => summarizeHypothesisReviewMeetings(scopedReviewMeetings),
    [scopedReviewMeetings],
  );
  const reviewHistory = useMemo(() => {
    const effectiveMeetings = scopedReviewMeetings.filter(
      (meeting) => !isHypothesisReviewRetryAttempt(meeting),
    );
    return effectiveMeetings.map((meeting, index) => {
      const round = meeting.roundIndex ?? index + 1;
      const previousRound = index > 0
        ? (effectiveMeetings[index - 1]?.roundIndex ?? index)
        : 0;
      return {
        id: meeting.meetingRoundId,
        round,
        status: meeting.status,
        digestAvailable: Boolean(meeting.digestId || meeting.digestRef),
        retryAttempts: scopedReviewMeetings.filter((candidate) => {
          const candidateRound = candidate.roundIndex ?? 0;
          return isHypothesisReviewRetryAttempt(candidate)
            && candidateRound > previousRound
            && candidateRound < round;
        }).length,
      };
    });
  }, [scopedReviewMeetings]);
  const archiveSummary = useMemo(() => ({
    selectedHypotheses: hypothesisFirstChain.selection?.selectedCandidateIds.length,
    effectiveReviews: reviewSummary.effectiveRounds,
    retryAttempts: reviewSummary.retryAttempts,
    collectionRequests: hypothesisFirstChain.collectionRequests.filter((request) => (
      !chainQuestionId
      || String(request.questionId ?? "").trim().toUpperCase() === chainQuestionId.trim().toUpperCase()
    )).length,
    reviewHistory,
  }), [
    chainQuestionId,
    hypothesisFirstChain.collectionRequests,
    hypothesisFirstChain.selection?.selectedCandidateIds.length,
    reviewHistory,
    reviewSummary,
  ]);
  const workflowContext = useMemo(() => buildResearchWorkflowContext({
    teamId,
    workflowId: CHALLENGE_CUP_WORKFLOW_ID,
    questionId: chainQuestionId,
    runId: location.runId,
    runVersion: runState.run?.runVersion ?? null,
    dataTeamId: runState.projection?.run.teamId ?? teamId,
    dataWorkflowId: runState.run?.workflowId ?? CHALLENGE_CUP_WORKFLOW_ID,
    dataQuestionId: hypothesisFirstChain.questionId,
    dataRunId: runState.run?.runId ?? null,
    dataRunVersion: runState.run?.runVersion ?? null,
    dataScopeReady: hypothesisFirstReady && Boolean(runState.projection),
    runStatus: runState.run?.status ?? runState.projection?.run.status ?? null,
    runTerminalReason: runState.run?.terminalReason ?? null,
    nodeRuns: runState.projection?.run.nodeRuns ?? null,
    scopeMismatch: hypothesisFirstChain.scopeMismatch,
    loading: !hypothesisFirstReady || (!runState.projection && !displayError),
    error: displayError,
    nextAction: workspaceNextAction,
    workspaceModel,
    selectedNodeId: location.selectedNodeId,
    panel: location.panel,
    roundProgress: hypothesisFirstChain.chainState
      ? {
          current: hypothesisFirstChain.chainState.meetingCount ?? 0,
          total: hypothesisFirstChain.chainState.roundBudget ?? 3,
        }
      : null,
  }), [
    chainQuestionId,
    displayError,
    hypothesisFirstChain.chainState,
    hypothesisFirstChain.questionId,
    hypothesisFirstChain.scopeMismatch,
    hypothesisFirstReady,
    location.panel,
    location.runId,
    location.selectedNodeId,
    runState.projection,
    runState.run,
    safeNextAction,
    workspaceModel,
    workspaceNextAction,
    teamId,
  ]);
  const retryDispatch = useCallback(() => {
    if (
      workflowContext.currentTask?.status !== "never_started"
      && workflowContext.currentTask?.status !== "failed_to_dispatch"
    ) return;
    const questionId = chainQuestionId.trim();
    if (!questionId) return;
    const input = buildResearchRunInput({
      teamId,
      questionId,
      safetyBudget: createResearchRunSafetyBudget(),
    });
    void commands.submitRun({
      ...input,
      idempotencyKey: freshRetryIdempotencyKey(input.idempotencyKey),
    }).catch(() => undefined);
  }, [chainQuestionId, commands.submitRun, teamId, workflowContext.currentTask?.status]);
  useResearchProcessAutofocus({
    panel: location.panel,
    selectedNodeId: location.selectedNodeId,
    nextTarget: hypothesisFirstReady
      ? hypothesisFirstSemanticNodeId(workflowContext.currentTask?.targetNodeId)
      : null,
    replaceParams: location.replaceParams,
  });

  const showInspector = workflowContext.loadState !== "scope_mismatch" && shouldShowResearchProcessInspector({
    panel: location.panel,
    selectedNodeId: location.selectedNodeId,
    nextTarget: workflowContext.currentTask?.targetNodeId,
  });
  const currentTaskActionsReady = workspaceModel.loadState === "ready"
    && !workspaceModel.scopeMismatch
    && !workspaceModel.resyncRequired;
  const atCurrentTask = Boolean(
    workflowActive && (workflowContext.view.selectedIsCurrentTask || formalWritesPaused),
  );
  const formalPrimaryAction = workspaceModel.primaryAction;
  const visibleFormalPrimaryAction = currentTaskActionsReady ? formalPrimaryAction : null;
  const currentTaskCommand = workflowContext.currentTask?.commandAction;
  const collectionRecoveryAction = currentTaskActionsReady
    && workspaceModel.source === "hypothesis_first"
    && workflowContext.currentTask?.collectionRequestId
    && (currentTaskCommand?.command === "retry_collection"
      || currentTaskCommand?.command === "continue_collection")
    ? {
        label: currentTaskCommand.label,
        requestId: workflowContext.currentTask.collectionRequestId,
      }
    : null;

  const inspectorPane = showInspector && (currentTaskActionsReady || location.panel === "question") ? (
    <ResearchProcessInspectorPane
      scope={{
        teamId,
        teamName,
        linkedChatRoomId,
        runId: location.runId,
        selectedNodeId: location.selectedNodeId,
        questionId: location.questionId,
        panel: location.panel,
      }}
      state={{
        run: runState.run,
        projection: runState.projection,
        effectiveBindings: catalog.effectiveBindings,
        nodeDetail: nodeDetail.state,
        insights,
        busy: commandBusy,
      }}
      actions={{
        replaceParams: replaceParamsForInspector,
        retryNodeDetail: nodeDetail.retry,
        submitRun: commands.submitRun,
        pendingTaskId: commands.pendingTaskId,
        submitOffer: commands.submitOffer,
      }}
      nextAction={workspaceNavigationAction}
      discussionModel={scopedDiscussionModel}
      onRecoverCollection={currentTaskActionsReady ? hypothesisFirstChain.recoverCollection : undefined}
      collectionRecoveryBusy={currentTaskActionsReady && hypothesisFirstChain.recoveryBusy}
      collectionRecoveryError={currentTaskActionsReady ? hypothesisFirstChain.recoveryError : null}
      primaryActionOwnedByWorkspace={workspaceModel.source === "formal_runtime"}
      archiveSummary={archiveSummary}
    />
  ) : null;

  return (
    <div data-fill="true" data-vui="research-process-workspace-host" className={styles.host}>
      <ResearchCommandPalette
        questions={catalog.questions}
        nextAction={workspaceNavigationAction}
        workflowActive={workflowActive && hypothesisFirstReady}
        onSelectExperiment={selectExperiment}
        onOpenPanel={(panel) => location.openPanel(panel)}
        onNavigateNode={(nodeId) => location.replaceParams({ node: hypothesisFirstSemanticNodeId(nodeId) ?? nodeId, panel: "node" })}
        discussionModel={scopedDiscussionModel}
        onNavigateDiscussion={navigateToDiscussion}
      />
      <VCanvasWorkbenchPage
        data-vui="research-process-workspace"
        domainRecipe="research-process-workflow"
        ariaLabel={isZh ? "科研流程工作区" : "Research workflow workspace"}
        title={isZh ? "科研流程" : "Research workflow"}
        hideHeader
        toolbarClassName={styles.toolbar}
        toolbar={(
          <ResearchWorkflowToolbar
            leading={toolbarLeading}
            onOpenTeamCommunication={onOpenTeamCommunication}
            identity={experimentIdentity}
            runId={location.runId}
            runStatus={runState.run?.status || runState.projection?.run.status || ""}
            experimentOptions={experimentOptions}
            panel={location.panel}
            workflowActive={workflowActive}
            onSelectExperiment={selectExperiment}
            onOpenPanel={location.openPanel}
            navigationLabel={workflowActive && hypothesisFirstReady ? workspaceNavigationAction.navigationLabel : undefined}
            nextActionStage={workflowActive && hypothesisFirstReady ? workspaceNavigationAction.stage : undefined}
            scopeMismatch={hypothesisFirstChain.scopeMismatch || workspaceModel.scopeMismatch}
            statusMessage={hypothesisFirstChain.scopeMismatch ? safeNextAction.statusMessage : undefined}
            chainRound={
              workflowActive && !formalRuntimeActive && hypothesisFirstChain.chainState
                ? {
                    current: hypothesisFirstChain.chainState.meetingCount ?? 0,
                    budget: hypothesisFirstChain.chainState.roundBudget ?? 3,
                  }
                : null
            }
            runtimeCurrentNodeIds={formalRuntimeCurrentNodeIds}
            formalRuntimeActive={formalRuntimeActive}
            atCurrentTask={atCurrentTask}
            onNavigateCurrent={
              hypothesisFirstReady && semanticCurrentTaskNodeId
                ? navigateToCurrentTask
                : undefined
            }
          />
        )}
        layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}
        resize={{
          sidebar: { id: "stages", defaultWidth: 220, minWidth: 180, maxWidth: 300 },
          aside: { id: "inspector", defaultWidth: 360, minWidth: 300, maxWidth: 520 },
        }}
        responsive={{
          enabled: true,
          rail: { label: "研究阶段" },
          inspector: { label: "当前任务" },
        }}
        rail={archiveOpen ? null : (
          <div className={styles.stageNavigator}>
            <ResearchWorkflowStageNavigator
              lang={lang}
              model={stageNavigatorModel}
              onNavigateNode={(nodeId) => location.replaceParams({ node: nodeId, panel: "node" })}
            />
          </div>
        )}
        canvas={archiveOpen ? (
          <div className={styles.archive} data-vui="research-question-archive-canvas">
            {inspectorPane}
          </div>
        ) : (
          <ResearchWorkflowCanvasPane
            graph={graph}
            selectedNodeId={location.selectedNodeId}
            runtimeCurrentNodeIds={formalRuntimeCurrentNodeIds}
            currentTaskNodeId={semanticCurrentTaskNodeId}
            error={displayError}
            onSelectNode={location.selectNode}
          />
        )}
        inspector={archiveOpen ? null : (
          <ResearchCurrentTaskInspector
            context={workflowContext}
            footer={visibleFormalPrimaryAction ? (
              <VButton
                type="button"
                variant="primary"
                isPending={commandBusy}
                isDisabled={commandBusy}
                onClick={() => {
                  if (commandBusy) return;
                  if (!visibleFormalPrimaryAction || !formalPrimaryAction) return;
                  void commands.submitOffer(formalPrimaryAction.offer).catch(() => undefined);
                }}
              >
                {visibleFormalPrimaryAction.offer.label}
              </VButton>
            ) : collectionRecoveryAction ? (
              <>
                <VButton
                  type="button"
                  variant="primary"
                  isPending={hypothesisFirstChain.recoveryBusy}
                  isDisabled={hypothesisFirstChain.recoveryBusy}
                  onClick={() => {
                    if (hypothesisFirstChain.recoveryBusy) return;
                    void hypothesisFirstChain.recoverCollection(collectionRecoveryAction.requestId);
                  }}
                >
                  {collectionRecoveryAction.label}
                </VButton>
                {hypothesisFirstChain.recoveryError ? (
                  <div
                    className="mt-2 [font-size:var(--vui-font-xs)] leading-4 text-[var(--fg-danger)]"
                    role="alert"
                  >
                    恢复搜集失败：{hypothesisFirstChain.recoveryError}
                  </div>
                ) : null}
              </>
            ) : undefined}
            onRetryDispatch={visibleFormalPrimaryAction || collectionRecoveryAction || !currentTaskActionsReady ? undefined : retryDispatch}
            retryPending={commandBusy}
            onReturnCurrentTask={
              semanticCurrentTaskNodeId
                ? navigateToCurrentTask
                : undefined
            }
          >
            {inspectorPane}
          </ResearchCurrentTaskInspector>
        )}
        canvasClassName={styles.canvas}
        inspectorClassName={styles.inspector}
        className={styles.page}
        shellTestId="research-process-workspace-shell"
        shellMode="board"
      />
    </div>
  );
}
