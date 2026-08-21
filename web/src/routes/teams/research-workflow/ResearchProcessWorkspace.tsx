import { useCallback, useMemo, type ReactNode } from "react";

import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import { VCanvasWorkbenchPage } from "../../../components/vui";
import { buildHypothesisFirstCanvasRegion } from "./hypothesisFirstCanvasRegion";
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
import { ResearchWorkflowToolbar } from "./ResearchWorkflowToolbar";
import { buildResearchWorkflowContext } from "./researchWorkflowContextModel";
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

export function ResearchProcessWorkspace({
  teamId,
  lang,
  teamName = "",
  linkedChatRoomId = "",
  toolbarLeading,
  onOpenTeamCommunication,
}: ResearchProcessWorkspaceProps) {
  const isZh = lang === "zh";
  const location = useResearchWorkflowWorkspace(teamId);
  const runState = useResearchWorkflowRun(teamId, location.runId);
  const catalog = useResearchWorkflowCatalog(teamId, runState.run?.runVersion ?? null);
  const chainQuestionId = location.questionId || runState.run?.questionId || "";
  const hypothesisFirstChain = useHypothesisFirstChain(teamId, chainQuestionId);
  useHypothesisFirstChainInvalidation(teamId, chainQuestionId, runState.lastSequence);
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


  const formalRuntimeActive = Boolean(hypothesisFirstChain.chainState?.hypothesisConverged);
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
    collectionChildStatus: runState.projection?.run.nodeRuns.source_finding?.status ?? null,
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
    runState.projection?.run.nodeRuns.source_finding?.status,
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
  const retryCollectionOffer = (runState.commandOffers ?? []).find((offer) => (
    offer.command === "retry_node" && (offer.nodeId === "source_finding" || !offer.nodeId)
  )) ?? null;

  const displayError =
    commands.error
    || formalCommand.commandError
    || runState.error
    || catalog.error
    || hypothesisFirstChain.error;
  const commandBusy = runState.busy || commands.busy || formalCommand.busy;
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
    scopeMismatch: hypothesisFirstChain.scopeMismatch,
    loading: !hypothesisFirstReady || (!runState.projection && !displayError),
    error: displayError,
    nextAction: safeNextAction,
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
    teamId,
  ]);
  useResearchProcessAutofocus({
    panel: location.panel,
    selectedNodeId: location.selectedNodeId,
    nextTarget: hypothesisFirstReady ? safeNextAction.targetNodeId : null,
    replaceParams: location.replaceParams,
  });

  const showInspector = workflowContext.loadState !== "scope_mismatch" && shouldShowResearchProcessInspector({
    panel: location.panel,
    selectedNodeId: location.selectedNodeId,
    nextTarget: safeNextAction.targetNodeId,
  });
  const atCurrentTask = Boolean(workflowActive && workflowContext.view.selectedIsCurrentTask);

  const inspectorPane = showInspector ? (
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
        replaceParams: location.replaceParams,
        retryNodeDetail: nodeDetail.retry,
        submitRun: commands.submitRun,
        pendingTaskId: commands.pendingTaskId,
        submitOffer: commands.submitOffer,
      }}
      nextAction={safeNextAction}
      retryCollectionOffer={retryCollectionOffer}
    />
  ) : null;
  const archiveOpen = location.panel === "question";

  return (
    <div data-fill="true" data-vui="research-process-workspace-host" className={styles.host}>
      <ResearchCommandPalette
        questions={catalog.questions}
        nextAction={safeNextAction}
        workflowActive={workflowActive && hypothesisFirstReady}
        onSelectExperiment={selectExperiment}
        onOpenPanel={(panel) => location.openPanel(panel)}
        onNavigateNode={(nodeId) => location.replaceParams({ node: nodeId, panel: "node" })}
      />
      <VCanvasWorkbenchPage
        data-vui="research-process-workspace"
        domainRecipe="research-process-workflow"
        ariaLabel={isZh ? "科研流程工作区" : "Research workflow workspace"}
        title={isZh ? "科研流程" : "Research workflow"}
        hideHeader
        toolbarClassName="!flex-nowrap overflow-hidden"
        toolbar={(
          <ResearchWorkflowToolbar
            leading={toolbarLeading}
            onOpenTeamCommunication={onOpenTeamCommunication}
            identity={experimentIdentity}
            runId={location.runId}
            runStatus={runState.run?.status || runState.projection?.run.status || ""}
            experimentOptions={experimentOptions}
            panel={location.panel}
            createDisabled={runState.busy}
            workflowActive={workflowActive}
            onSelectExperiment={selectExperiment}
            onOpenPanel={location.openPanel}
            navigationLabel={workflowActive && hypothesisFirstReady ? safeNextAction.navigationLabel : undefined}
            nextActionStage={workflowActive && hypothesisFirstReady ? safeNextAction.stage : undefined}
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
              hypothesisFirstReady && safeNextAction.targetNodeId
                ? () => location.replaceParams({ node: safeNextAction.targetNodeId, panel: "node" })
                : undefined
            }
          />
        )}
        layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}
        resize={{
          aside: { id: "inspector", defaultWidth: 360, minWidth: 300, maxWidth: 520 },
        }}
        canvas={archiveOpen && inspectorPane ? (
          <div className={styles.archive} data-vui="research-question-archive-workspace">
            {inspectorPane}
          </div>
        ) : (
          <ResearchWorkflowCanvasPane
            graph={graph}
            selectedNodeId={location.selectedNodeId}
            runtimeCurrentNodeIds={formalRuntimeCurrentNodeIds}
            currentTaskNodeId={workflowContext.currentTask?.targetNodeId}
            error={displayError}
            onSelectNode={location.selectNode}
          />
        )}
        inspector={!archiveOpen && inspectorPane ? (
          location.panel === "node" ? (
            <ResearchCurrentTaskInspector
              context={workflowContext}
              onReturnCurrentTask={
                workflowContext.currentTask?.targetNodeId
                  ? () => location.replaceParams({ node: workflowContext.currentTask?.targetNodeId, panel: "node" })
                  : undefined
              }
            >
              {inspectorPane}
            </ResearchCurrentTaskInspector>
          ) : inspectorPane
        ) : undefined}
        canvasClassName={styles.canvas}
        inspectorClassName={styles.inspector}
        className={styles.page}
        shellTestId="research-process-workspace-shell"
        shellMode="board"
      />
    </div>
  );
}
