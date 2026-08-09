import { useCallback, useMemo } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import { VCanvasWorkbenchPage } from "../../../components/vui";
import { definitionToCanvasGraph, projectionToCanvasGraph } from "./researchProcessGraphModel";
import { ResearchProcessInspectorPane } from "./ResearchProcessInspectorPane";
import { ResearchWorkflowCanvasPane } from "./ResearchWorkflowCanvasPane";
import { ResearchWorkflowToolbar } from "./ResearchWorkflowToolbar";
import { useNodeDetailState } from "./useNodeDetailState";
import { useResearchWorkflowCatalog } from "./useResearchWorkflowCatalog";
import { useResearchWorkflowCommands } from "./useResearchWorkflowCommands";
import { useResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import { useResearchWorkflowProjectContext } from "./useResearchWorkflowProjectContext";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";
import { useResearchWorkflowWorkspace } from "./useResearchWorkflowWorkspace";
import styles from "./ResearchProcessWorkspace.styles";

export type ResearchProcessWorkspaceProps = {
  teamId: string;
  teamName?: string;
  linkedChatRoomId?: string;
};

export function ResearchProcessWorkspace({
  teamId,
  teamName = "",
  linkedChatRoomId = "",
}: ResearchProcessWorkspaceProps) {
  const location = useResearchWorkflowWorkspace(teamId);
  const runState = useResearchWorkflowRun(teamId, location.runId);
  const project = useResearchWorkflowProjectContext(teamId);
  const catalog = useResearchWorkflowCatalog(teamId, runState.run?.runVersion ?? null);
  const nodeDetail = useNodeDetailState(teamId, location.runId, location.selectedNodeId);
  const detail = nodeDetail.state.kind === "ready" ? nodeDetail.state.detail : null;
  const insights = useResearchWorkflowInsights(teamId, location.runId);
  const commands = useResearchWorkflowCommands({
    teamId,
    runId: location.runId,
    selectedNodeId: location.selectedNodeId,
    run: runState.run,
    nodeDetail: detail,
    createRun: runState.createRun,
    resolveHuman: runState.resolveHuman,
    refresh: runState.refresh,
    replaceParams: location.replaceParams,
  });

  const graph = useMemo(() => {
    if (!runState.projection) return null;
    if (location.runId) return projectionToCanvasGraph(runState.projection);
    return definitionToCanvasGraph(runState.projection.definition, {
      primaryAgentIdByNode: new Map(
        (catalog.effectiveBindings ?? [])
          .filter((binding) => Boolean(binding.agentId))
          .map((binding) => [binding.nodeId, binding.agentId]),
      ),
    });
  }, [catalog.effectiveBindings, location.runId, runState.projection]);

  const jumpToRuntime = useCallback(() => {
    const current = runState.projection?.run.runtimeCurrentNodeIds?.[0];
    if (current) location.replaceParams({ node: current, panel: "node" });
  }, [location, runState.projection]);

  const runtimeNodeId = runState.projection?.run.runtimeCurrentNodeIds?.[0] ?? "";
  const nextAction = runState.projection?.definition.nodes.find(
    (node) => node.nodeId === runtimeNodeId,
  )?.label ?? (location.runId ? "等待运行更新" : "创建运行");
  const displayError = commands.error || runState.error || catalog.error || project.error;
  const commandBusy = runState.busy || commands.busy;

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
            questionId={runState.run?.questionId || location.questionId}
            runId={location.runId}
            runStatus={runState.run?.status || runState.projection?.run.status || ""}
            activeProjectId={project.activeProjectId || ""}
            nextAction={nextAction}
            streamState={runState.streamState}
            runOptions={catalog.runOptions}
            panel={location.panel}
            hasRuntimeNode={Boolean(runtimeNodeId)}
            createDisabled={Boolean(runState.busy || project.loading || !project.activeProjectId)}
            createDisabledReason={project.error || (!project.activeProjectId ? "请先选择活动研究项目" : undefined)}
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
            runtimeCurrentNodeIds={runState.projection?.run.runtimeCurrentNodeIds ?? []}
            error={displayError}
            onSelectNode={location.selectNode}
          />
        )}
        inspector={(
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
              activeProjectId: project.activeProjectId || "",
              projectLoading: project.loading,
              nodeDetail: nodeDetail.state,
              insights,
              busy: commandBusy,
            }}
            actions={{
              replaceParams: location.replaceParams,
              retryNodeDetail: nodeDetail.retry,
              submitRun: commands.submitRun,
              pendingTaskId: commands.pendingTaskId,
              runCommand: commands.runInspectorCommand,
            }}
          />
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
