/**
 * Canonical single-canvas research process workspace.
 * One stage-navigation surface: VWorkflowCanvas. Selection is UI-only.
 *
 * Layout: VCanvasWorkbenchPage (shadcn/recipe fill) — canvas fills remaining height,
 * inspector is the right rail. Do not stack fixed-height canvas + flex-1 empty panels.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchResearchWorkflowNodeDetail, listResearchWorkflowRuns } from "../../../api/researchWorkflow";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import { WORKBENCH_LAYOUT_IDS } from "../../../components/layout/workbenchLayoutIds";
import {
  VButton,
  VCanvasWorkbenchPage,
  VEmptyState,
  VSelect,
  VStateSurface,
  VSurface,
  VWorkflowCanvas,
} from "../../../components/vui";
import { definitionToCanvasGraph, projectionToCanvasGraph } from "./researchProcessGraphModel";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { projectNodeOps } from "./nodeOpsProjection";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";

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
  const [nodeDetail, setNodeDetail] = useState<Record<string, unknown> | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [runOptions, setRunOptions] = useState<Array<{ runId: string; status: string }>>([]);

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
    if (!runId || !selectedNodeId) {
      setNodeDetail(null);
      return;
    }
    let cancelled = false;
    fetchResearchWorkflowNodeDetail(runId, selectedNodeId)
      .then((detail) => {
        if (!cancelled) setNodeDetail(detail);
      })
      .catch(() => {
        if (!cancelled) setNodeDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, selectedNodeId, run?.status, run?.humanTasks]);

  useEffect(() => {
    let cancelled = false;
    listResearchWorkflowRuns(CHALLENGE_CUP_WORKFLOW_ID)
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
  }, [runId, run?.status]);

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
      const pending = (run.humanTasks || []).find((t) => String(t.status) === "pending");
      const taskId = String(pending?.taskId || "");
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
    [runId, run, resolveHuman, replaceParams],
  );

  const jumpToRuntime = useCallback(() => {
    const current = projection?.run.runtimeCurrentNodeIds?.[0];
    if (current) replaceParams({ node: current, panel: "node" });
  }, [projection, replaceParams]);

  const onInspectorCommand = useCallback(
    (command: string, _adapter: NodeAdapterSpec) => {
      if (command === "accept_handoff") {
        void onResolveHuman(true);
        return;
      }
      if (command === "reject_handoff" || command === "revise") {
        void onResolveHuman(false);
        return;
      }
      setLocalError(`命令「${command}」尚未接入业务服务`);
    },
    [onResolveHuman],
  );

  const runtimeCurrent = Boolean(
    selectedNodeId && projection?.run.runtimeCurrentNodeIds?.includes(selectedNodeId),
  );

  const nodeOps = useMemo(
    () =>
      projectNodeOps({
        nodeId: selectedNodeId,
        run,
        runtimeCurrentNodeIds: projection?.run.runtimeCurrentNodeIds,
      }),
    [selectedNodeId, run, projection?.run.runtimeCurrentNodeIds],
  );

  const displayError = localError || error;

  const headerActions = (
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
  );

  const canvasBody = graph ? (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
      {displayError ? (
        <div
          className="shrink-0 border-b border-[var(--vui-border-subtle)] px-3 py-2 text-sm text-[var(--fg-primary)]"
          role="alert"
        >
          {displayError}
        </div>
      ) : null}
      <div className="min-h-0 min-w-0 flex-1">
        <VWorkflowCanvas
          graph={graph}
          selectedNodeId={selectedNodeId}
          runtimeCurrentNodeIds={projection?.run.runtimeCurrentNodeIds || []}
          onSelectNode={onSelectNode}
          height="100%"
          className="h-full min-h-0 border-0"
        />
      </div>
    </div>
  ) : (
    <VStateSurface tone="loading" title="加载流程定义" fill />
  );

  const inspectorBody =
    panel === "agents" ? (
      <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-sm">
        <strong>Agent 分工</strong>
        <ul className="m-0 list-none space-y-1 p-0">
          {(run?.bindingSnapshots || []).map((snap) => (
            <li
              key={String(snap.snapshotId || snap.nodeId)}
              className="rounded border border-[var(--border-subtle)] px-2 py-1"
            >
              <span className="font-medium">{String(snap.nodeId)}</span>
              {" · "}
              {String(snap.agentId || "未绑定")}
            </li>
          ))}
          {(run?.bindingSnapshots || []).length === 0 ? (
            <li className="text-[var(--fg-secondary)]">暂无绑定快照</li>
          ) : null}
        </ul>
      </VSurface>
    ) : panel === "timeline" ? (
      <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-sm">
        <strong>运行事件</strong>
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
        <strong>团队</strong>
        <p className="m-0 text-[var(--fg-secondary)]">团队组织与讨论在此面板打开；流程执行仍以画布为准。</p>
        <p className="m-0">团队 ID：{teamId || "—"}</p>
        <p className="m-0">运行：{runId || "未创建"}</p>
      </VSurface>
    ) : (
      <ResearchProcessNodeInspector
        nodeId={selectedNodeId}
        runtimeCurrent={runtimeCurrent || Boolean(nodeDetail?.runtimeCurrent)}
        actorKind={String(nodeDetail?.actorKind || "")}
        sessionAnchorDegraded={Boolean(nodeDetail?.sessionAnchorDegraded)}
        chatDeepLink={(nodeDetail?.chatDeepLink as string) || null}
        bindingLabel={String((nodeDetail?.bindingSnapshot as { agentId?: string } | undefined)?.agentId || "")}
        handoffPending={Boolean((run?.humanTasks || []).some((t) => String(t.status) === "pending"))}
        busy={busy}
        ops={nodeOps}
        onCommand={onInspectorCommand}
      />
    );

  return (
    <VCanvasWorkbenchPage
      data-vui="research-process-workspace"
      domainRecipe="research-process-workflow"
      ariaLabel="科研流程工作区"
      eyebrow={
        runId
          ? `${runId} · ${run?.status || projection?.run.status || ""}`
          : "创建运行后由工作流引擎驱动"
      }
      title="科研流程"
      actions={headerActions}
      layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}
      resize={{
        aside: {
          defaultWidth: 320,
          minWidth: 260,
          maxWidth: 480,
        },
      }}
      canvas={canvasBody}
      inspector={inspectorBody}
      canvasClassName="min-h-0 p-0"
      inspectorClassName="min-h-0"
      className="h-full min-h-0"
    />
  );
}
