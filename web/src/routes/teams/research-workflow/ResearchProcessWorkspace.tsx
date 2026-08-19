import { useCallback, useMemo } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import { VCanvasWorkbenchPage } from "../../../components/vui";
import { buildHypothesisFirstCanvasRegion } from "./hypothesisFirstCanvasRegion";
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
    return composeHypothesisFirstGraph(base, region);
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

  const jumpToRuntime = useCallback(() => {
    const current = runState.projection?.run.runtimeCurrentNodeIds?.[0];
    if (current) location.replaceParams({ node: current, panel: "node" });
  }, [location, runState.projection]);

  const runtimeNodeId = runState.projection?.run.runtimeCurrentNodeIds?.[0] ?? "";
  const nextAction = runState.projection?.definition.nodes.find(
    (node) => node.nodeId === runtimeNodeId,
  )?.label ?? (location.runId ? "等待运行更新" : "创建运行");
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
            teamName={teamName || teamId}
            questionId={runState.run?.questionId || ""}
            runId={location.runId}
            runStatus={runState.run?.status || runState.projection?.run.status || ""}
            nextAction={nextAction}
            streamState={runState.streamState}
            runOptions={catalog.runOptions}
            panel={location.panel}
            hasRuntimeNode={Boolean(runtimeNodeId)}
            createDisabled={runState.busy}
            onSelectRun={(runId) => location.replaceParams({ runId: runId || null, node: null, panel: "node" })}
            onOpenPanel={location.openPanel}
            onJumpToRuntime={jumpToRuntime}
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
