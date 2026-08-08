/**
 * Canonical single-canvas research process workspace.
 * Selection is UI-only (URL node); runtime current is server-owned.
 *
 * Layout follows TeamsCanvasComposer + VCanvasWorkbenchPage (not hand-rolled columns):
 * - shell already provides team chrome → hideHeader
 * - actions live in recipe toolbar
 * - canvas host is flex-1 min-h-0; React Flow fills via absolute inset host
 * - inspector is recipe aside (WORKBENCH_LAYOUT_IDS.researchFlow)
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  fetchEffectiveAgentBindings,
  listResearchWorkflowRuns,
} from "../../../api/researchWorkflow";
import type { EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import {
  VButton,
  VCanvasWorkbenchPage,
  VEmptyState,
  VPanelHeader,
  VSelect,
  VStateSurface,
  VSurface,
  VWorkflowCanvas,
} from "../../../components/vui";
import { definitionToCanvasGraph, projectionToCanvasGraph } from "./researchProcessGraphModel";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import { getNodeAdapter } from "./nodeAdapterModel";
import { executeNodeCommand } from "./nodeCommandAdapter";
import { useNodeDetailState } from "./useNodeDetailState";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";
import { ResearchAgentBindingPanel } from "./ResearchAgentBindingPanel";

type PanelKind = "node" | "agents" | "team" | "timeline";

export type ResearchProcessWorkspaceProps = {
  teamId?: string;
};

export function ResearchProcessWorkspace({ teamId = "" }: ResearchProcessWorkspaceProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("runId") || "";
  const selectedNodeId = searchParams.get("node") || null;
  const panel = (searchParams.get("panel") as PanelKind | null) || "node";

  const { projection, run, error, busy, createRun, resolveHuman, refresh } = useResearchWorkflowRun(runId);
  const [localError, setLocalError] = useState<string | null>(null);
  const [runOptions, setRunOptions] = useState<Array<{ runId: string; status: string }>>([]);
  const [effectiveBindings, setEffectiveBindings] = useState<EffectiveAgentBinding[] | null>(null);
  const [commandBusy, setCommandBusy] = useState(false);
  const nodeDetailState = useNodeDetailState(runId, selectedNodeId);
  const nodeDetail = nodeDetailState.state.kind === "ready" ? nodeDetailState.state.detail : null;

  const replaceParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams);
      next.set("researchView", "workflow");
      next.set("workflowId", CHALLENGE_CUP_WORKFLOW_ID);
      if (teamId) next.set("team", teamId);
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, value);
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams, teamId],
  );

  useEffect(() => {
    let cancelled = false;
    listResearchWorkflowRuns(CHALLENGE_CUP_WORKFLOW_ID, { teamId })
      .then((payload) => {
        if (cancelled) return;
        setRunOptions(
          (payload.runs || []).map((item) => ({
            runId: item.runId,
            status: item.status,
          })),
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [teamId, runId, run?.status]);

  useEffect(() => {
    if (!teamId) {
      setEffectiveBindings(null);
      return;
    }
    let cancelled = false;
    fetchEffectiveAgentBindings(CHALLENGE_CUP_WORKFLOW_ID, { teamId })
      .then((payload) => {
        if (!cancelled) setEffectiveBindings(payload.bindings);
      })
      .catch(() => {
        if (!cancelled) setEffectiveBindings(null);
      });
    return () => {
      cancelled = true;
    };
  }, [teamId]);

  const graph = useMemo(() => {
    if (!projection) return null;
    return runId ? projectionToCanvasGraph(projection) : definitionToCanvasGraph(projection.definition);
  }, [projection, runId]);

  const onSelectNode = useCallback(
    (nodeId: string | null) => {
      replaceParams({ node: nodeId, panel: "node" });
    },
    [replaceParams],
  );

  const onCreateRun = useCallback(async () => {
    setLocalError(null);
    try {
      const created = await createRun(teamId);
      replaceParams({
        runId: created.runId,
        node: created.runtimeCurrentNodeIds?.[0] || "knowledge_handoff",
      });
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    }
  }, [teamId, replaceParams, createRun]);

  const onResolveHuman = useCallback(
    async (accept: boolean) => {
      if (!runId || !run?.humanTasks?.length) return;
      // Node-scoped: only the CURRENT selected node's pending task may be
      // resolved — never the global first pending task (multi-gate safety).
      const pending = (run.humanTasks || []).find(
        (t) =>
          String(t.status) === "pending" &&
          (!selectedNodeId || String(t.nodeId) === selectedNodeId),
      );
      if (!pending) {
        setLocalError("当前节点没有待处理的人工任务");
        return;
      }
      const taskId = String(pending.taskId || "");
      if (!taskId) {
        setLocalError("没有待处理的人工任务");
        return;
      }
      setLocalError(null);
      try {
        const next = await resolveHuman(taskId, accept);
        const nextPending = (next.humanTasks || []).find((t) => String(t.status) === "pending");
        if (nextPending?.nodeId) {
          replaceParams({ node: String(nextPending.nodeId), panel: "node" });
        }
      } catch (err) {
        setLocalError(err instanceof Error ? err.message : String(err));
      }
    },
    [runId, run, selectedNodeId, resolveHuman, replaceParams],
  );

  const jumpToRuntime = useCallback(() => {
    const current = projection?.run.runtimeCurrentNodeIds?.[0];
    if (current) replaceParams({ node: current, panel: "node" });
  }, [projection, replaceParams]);

  const currentPendingTaskId = useCallback(
    (nodeId: string): string | null => {
      const pending = (run?.humanTasks || []).find(
        (t) => String(t.status) === "pending" && String(t.nodeId) === nodeId,
      );
      return pending ? String(pending.taskId || "") || null : null;
    },
    [run],
  );

  const onInspectorCommand = useCallback(
    (command: string) => {
      if (command === "accept_handoff") {
        void onResolveHuman(true);
        return;
      }
      if (command === "reject_handoff" || command === "revise") {
        void onResolveHuman(false);
        return;
      }
      if (!runId || !selectedNodeId) return;
      const capability = nodeDetail?.commands.find((c) => c.command === command);
      if (!capability) {
        setLocalError(`命令「${command}」后端未声明能力`);
        return;
      }
      setCommandBusy(true);
      setLocalError(null);
      executeNodeCommand(
        {
          runId,
          nodeId: selectedNodeId,
          teamId,
          pendingHumanTaskId: currentPendingTaskId(selectedNodeId) || undefined,
        },
        capability,
      )
        .then(() => void refresh())
        .catch((err: unknown) => {
          setLocalError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => setCommandBusy(false));
    },
    [runId, selectedNodeId, teamId, nodeDetail, onResolveHuman, refresh, currentPendingTaskId],
  );

  const displayError = localError || error;

  // Canvas cell: flex column fill; React Flow absolute-fills the remaining host.
  const canvasBody = (
    <div
      className="relative flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden"
      data-testid="research-process-canvas-host"
      data-composer="research-process-canvas"
    >
      {displayError ? (
        <div
          className="shrink-0 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2 text-sm"
          role="alert"
        >
          {displayError}
        </div>
      ) : null}
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
        {graph ? (
          <VWorkflowCanvas
            graph={graph}
            selectedNodeId={selectedNodeId}
            runtimeCurrentNodeIds={projection?.run.runtimeCurrentNodeIds || []}
            onSelectNode={onSelectNode}
            height="100%"
            className="!absolute !inset-0 h-full min-h-0 !rounded-none !border-0"
          />
        ) : (
          <VStateSurface tone="loading" title="加载流程定义" fill className="h-full min-h-0" />
        )}
      </div>
    </div>
  );

  const toolbar = (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
      <div className="min-w-0 text-xs text-[var(--fg-secondary)]">
        {runId
          ? `${runId} · ${run?.status || projection?.run.status || ""}`
          : "创建运行后由工作流引擎驱动"}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {runOptions.length > 0 ? (
          <VSelect
            density="compact"
            className="min-w-[12rem]"
            aria-label="运行切换"
            placeholder="选择运行"
            selectedKey={runId || null}
            options={[
              { id: "", label: "选择运行" },
              ...runOptions.map((item) => ({
                id: item.runId,
                label: `${item.runId} · ${item.status}`,
              })),
            ]}
            onSelectionChange={(key) => {
              const nextId = key == null ? "" : String(key);
              replaceParams({ runId: nextId || null });
              if (nextId) void refresh();
            }}
          />
        ) : null}
        <VButton
          type="button"
          variant={panel === "agents" ? "secondary" : "ghost"}
          onClick={() => replaceParams({ panel: "agents" })}
        >
          Agent
        </VButton>
        <VButton
          type="button"
          variant={panel === "timeline" ? "secondary" : "ghost"}
          onClick={() => replaceParams({ panel: "timeline" })}
        >
          时间线
        </VButton>
        <VButton
          type="button"
          variant={panel === "team" ? "secondary" : "ghost"}
          onClick={() => replaceParams({ panel: "team" })}
        >
          团队
        </VButton>
        {projection?.run.runtimeCurrentNodeIds?.length ? (
          <VButton type="button" variant="ghost" onClick={jumpToRuntime}>
            当前节点
          </VButton>
        ) : null}
        {!runId ? (
          <VButton type="button" onClick={onCreateRun} isDisabled={busy}>
            创建运行
          </VButton>
        ) : null}
      </div>
    </div>
  );

  const inspectorBody =
    panel === "agents" ? (
      <ResearchAgentBindingPanel
        teamId={teamId}
        run={run}
        effectiveBindings={effectiveBindings}
        lang="zh"
      />
    ) : panel === "timeline" ? (
      <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-sm">
        <VPanelHeader title="运行事件" headingLevel={3} />
        <ul className="m-0 list-none space-y-1 p-0">
          {(run?.events || []).map((evt) => (
            <li
              key={String(evt.eventId || evt.sequence)}
              className="rounded border border-[var(--border-subtle)] px-2 py-1"
            >
              #{String(evt.sequence)} {String(evt.type)} {String(evt.nodeId || "")}
            </li>
          ))}
          {(run?.events || []).length === 0 ? (
            <li className="text-[var(--fg-secondary)]">暂无事件</li>
          ) : null}
        </ul>
      </VSurface>
    ) : panel === "team" ? (
      <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-sm">
        <VPanelHeader title="团队" headingLevel={3} />
        <p className="m-0 text-[var(--fg-secondary)]">团队组织与讨论在此面板打开；流程执行仍以画布为准。</p>
        <p className="m-0">团队 ID：{teamId || "—"}</p>
        <p className="m-0">运行：{runId || "未创建"}</p>
      </VSurface>
    ) : selectedNodeId ? (
      nodeDetailState.state.kind === "loading" ? (
        <VStateSurface tone="loading" title="加载节点详情" fill className="h-full min-h-0" />
      ) : nodeDetailState.state.kind === "error" ? (
        <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3" data-vui="node-detail-error">
          <div className="rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]" role="alert">
            节点详情加载失败：{nodeDetailState.state.message}
          </div>
          <div className="flex flex-wrap gap-2">
            <VButton type="button" onClick={nodeDetailState.retry}>
              重试
            </VButton>
          </div>
        </VSurface>
      ) : nodeDetailState.state.kind === "empty" ? (
        <VSurface tone="panel" className="flex h-full min-h-0 flex-col overflow-auto p-3">
          <VEmptyState title="暂无节点详情" className="h-auto w-full border-0 bg-transparent">
            该节点尚未产生运行数据。
          </VEmptyState>
        </VSurface>
      ) : (
        <ResearchProcessNodeInspector
          nodeId={selectedNodeId}
          adapter={getNodeAdapter(selectedNodeId)}
          detail={nodeDetail}
          handoffPending={Boolean(currentPendingTaskId(selectedNodeId))}
          busy={Boolean(busy) || commandBusy}
          onCommand={onInspectorCommand}
        />
      )
    ) : (
      <div className="flex h-full min-h-0 flex-col items-stretch justify-center p-3">
        <VEmptyState title="选择流程节点" className="h-auto w-full border-0 bg-transparent">
          在画布上点击任务节点，查看绑定、交接与运行命令。
        </VEmptyState>
      </div>
    );

  // Fill the board primary cell end-to-end (parent already absolute-pins overview).
  // VCanvasWorkbenchPage owns toolbar + canvas/inspector split; no second outer grid.
  return (
    <div
      data-fill="true"
      data-vui="research-process-workspace-host"
      className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden"
    >
      <VCanvasWorkbenchPage
        data-vui="research-process-workspace"
        domainRecipe="research-process-workflow"
        ariaLabel="科研流程工作区"
        title="科研流程"
        hideHeader
        toolbar={toolbar}
        layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}
        resize={{
          aside: {
            id: "inspector",
            defaultWidth: 320,
            minWidth: 260,
            maxWidth: 480,
          },
        }}
        canvas={canvasBody}
        inspector={inspectorBody}
        canvasClassName="!border-0 !rounded-none !h-full min-h-0"
        inspectorClassName="!border-0 !rounded-none !h-full min-h-0"
        className="h-full min-h-0 w-full flex-1"
        shellTestId="research-process-workspace-shell"
        shellMode="board"
      />
    </div>
  );
}
