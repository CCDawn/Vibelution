import { useCallback, useMemo } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import { VCanvasWorkbenchPage } from "../../../components/vui";
import { buildHypothesisFirstCanvasRegion } from "./hypothesisFirstCanvasRegion";
import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";
import {
  isHypothesisFirstDiscussionActive,
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
import {
  useHypothesisFirstChain,
  useHypothesisFirstChainInvalidation,
} from "./useHypothesisFirstChain";
import { useNodeDetailState } from "./useNodeDetailState";
import { useResearchWorkflowCatalog } from "./useResearchWorkflowCatalog";
import { useResearchWorkflowCommand } from "./useResearchWorkflowCommand";
import { useResearchWorkflowCommands } from "./useResearchWorkflowCommands";
import { useResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";
import { useResearchWorkflowWorkspace } from "./useResearchWorkflowWorkspace";
import styles from "./ResearchProcessWorkspace.styles";

export type ResearchProcessWorkspaceProps = {
  teamId: string;
  teamName?: string;
  linkedChatRoomId?: string;
};

// Stable identity so the memoized canvas pane does not re-render when no run
// projection is loaded yet.
const EMPTY_RUNTIME_NODE_IDS: string[] = [];

export function ResearchProcessWorkspace({
  teamId,
  teamName = "",
  linkedChatRoomId = "",
}: ResearchProcessWorkspaceProps) {
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
      demotePipelineStages: isHypothesisFirstDiscussionActive(hypothesisFirstChain.meetings),
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
    if (!currentRun) {
      return buildExperimentSwitchOptions({ questions: catalog.questions });
    }
    const currentNodeId = currentRun.runtimeCurrentNodeIds?.[0] ?? "";
    const currentTitle = catalog.questions.find(
      (question) => question.questionId.toUpperCase() === currentRun.questionId.toUpperCase(),
    )?.title;
    return buildExperimentSwitchOptions({
      questions: catalog.questions,
      current: {
        questionId: currentRun.questionId,
        title: currentTitle,
        runId: currentRun.runId,
        currentNodeId,
        selectedCandidateIds: hypothesisFirstChain.selection?.selectedCandidateIds,
      },
    });
  }, [catalog.questions, hypothesisFirstChain.selection?.selectedCandidateIds, runState.run]);
  const selectExperiment = useCallback((questionId: string) => {
    const patch = resolveExperimentSwitch(experimentOptions, questionId);
    if (!patch) return;
    void fetchHypothesisFirstFocusNode(teamId, patch.questionId).then((node) => {
      location.replaceParams({ ...patch, node });
    });
  }, [experimentOptions, location, teamId]);

  const nextAction = useMemo(() => resolveHypothesisFirstNextAction({
    run: runState.run,
    chainState: hypothesisFirstChain.chainState,
    meetings: hypothesisFirstChain.meetings,
    selection: hypothesisFirstChain.selection,
    collectionRequests: hypothesisFirstChain.collectionRequests,
    collectionChildStatus: runState.projection?.run.nodeRuns.source_finding?.status ?? null,
    selectedNodeId: location.selectedNodeId,
  }), [
    hypothesisFirstChain.chainState,
    hypothesisFirstChain.collectionRequests,
    hypothesisFirstChain.meetings,
    hypothesisFirstChain.selection,
    location.selectedNodeId,
    runState.projection?.run.nodeRuns.source_finding?.status,
    runState.run,
  ]);
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
  const showInspector = shouldShowResearchProcessInspector({
    panel: location.panel,
    selectedNodeId: location.selectedNodeId,
  });

  return (
    <div data-fill="true" data-vui="research-process-workspace-host" className={styles.host}>
      <VCanvasWorkbenchPage
        data-vui="research-process-workspace"
        domainRecipe="research-process-workflow"
        ariaLabel="科研流程工作区"
        title="科研流程"
        hideHeader
        toolbar={(
          <ResearchWorkflowToolbar
            identity={experimentIdentity}
            runId={location.runId}
            runStatus={runState.run?.status || runState.projection?.run.status || ""}
            experimentOptions={experimentOptions}
            panel={location.panel}
            createDisabled={runState.busy}
            onSelectExperiment={selectExperiment}
            onOpenPanel={location.openPanel}
            navigationLabel={location.runId ? nextAction.navigationLabel : undefined}
            onNavigateCurrent={
              nextAction.targetNodeId
                ? () => location.replaceParams({ node: nextAction.targetNodeId, panel: "node" })
                : undefined
            }
          />
        )}
        layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}
        resize={{ aside: { id: "inspector", defaultWidth: 360, minWidth: 300, maxWidth: 520 } }}
        canvas={(
          <ResearchWorkflowCanvasPane
            graph={graph}
            selectedNodeId={location.selectedNodeId}
            runtimeCurrentNodeIds={runState.projection?.run.runtimeCurrentNodeIds ?? EMPTY_RUNTIME_NODE_IDS}
            error={displayError}
            onSelectNode={location.selectNode}
          />
        )}
        inspector={
          showInspector ? (
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
              nextAction={nextAction}
              retryCollectionOffer={retryCollectionOffer}
            />
          ) : undefined
        }
        canvasClassName={styles.canvas}
        inspectorClassName={styles.inspector}
        className={styles.page}
        shellTestId="research-process-workspace-shell"
        shellMode="board"
      />
    </div>
  );
}
