/**
 * Canonical single-canvas research process workspace.
 * One stage-navigation surface: VWorkflowCanvas. Selection is UI-only.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchResearchWorkflowNodeDetail, listResearchWorkflowRuns } from "../../../api/researchWorkflow";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VPanelHeader,
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

  return (
    <VSurface tone="workspace" className="flex min-h-0 flex-1 flex-col gap-3 p-3" data-vui="research-process-workspace">
      <VPanelHeader
        title="科研流程"
        eyebrow={
          runId
            ? `${runId} · ${run?.status || projection?.run.status || ""}`
            : "创建运行后由工作流引擎驱动"
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {runOptions.length > 0 ? (
              <select
                className="rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1 text-xs"
                aria-label="运行切换"
                value={runId}
                onChange={(event) => {
                  const nextId = event.target.value;
                  replaceParams({ runId: nextId || null });
                  if (nextId) void refresh();
                }}
              >
                <option value="">选择运行</option>
                {runOptions.map((item) => (
                  <option key={item.runId} value={item.runId}>
                    {item.runId} · {item.status}
                  </option>
                ))}
              </select>
            ) : null}
            <VButton type="button" variant="ghost" onClick={() => replaceParams({ panel: "agents" })}>
              Agent
            </VButton>
            <VButton type="button" variant="ghost" onClick={() => replaceParams({ panel: "timeline" })}>
              时间线
            </VButton>
            <VButton type="button" variant="ghost" onClick={() => replaceParams({ panel: "team" })}>
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
        }
      />

      {displayError ? (
        <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2 text-sm" role="alert">
          {displayError}
        </div>
      ) : null}

      {graph ? (
        <VWorkflowCanvas
          graph={graph}
          selectedNodeId={selectedNodeId}
          runtimeCurrentNodeIds={projection?.run.runtimeCurrentNodeIds || []}
          onSelectNode={onSelectNode}
          height={440}
        />
      ) : (
        <div className="flex h-[440px] items-center justify-center rounded-xl border border-[var(--border-subtle)] text-sm">
          加载流程定义…
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div data-panel={panel}>
          {panel === "agents" ? (
            <VSurface tone="panel" className="min-h-[200px] space-y-2 p-3 text-sm">
              <strong>Agent 分工</strong>
              <ul className="m-0 list-none space-y-1 p-0">
                {(run?.bindingSnapshots || []).map((snap) => (
                  <li key={String(snap.snapshotId || snap.nodeId)} className="rounded border border-[var(--border-subtle)] px-2 py-1">
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
            <VSurface tone="panel" className="min-h-[200px] space-y-2 p-3 text-sm">
              <strong>运行事件</strong>
              <ul className="m-0 list-none space-y-1 p-0">
                {(run?.events || []).map((evt) => (
                  <li key={String(evt.eventId || evt.sequence)} className="rounded border border-[var(--border-subtle)] px-2 py-1">
                    #{String(evt.sequence)} {String(evt.type)} {String(evt.nodeId || "")}
                  </li>
                ))}
                {(run?.events || []).length === 0 ? (
                  <li className="text-[var(--fg-secondary)]">暂无事件</li>
                ) : null}
              </ul>
            </VSurface>
          ) : panel === "team" ? (
            <VSurface tone="panel" className="min-h-[200px] space-y-2 p-3 text-sm">
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
          )}
        </div>
      </div>
    </VSurface>
  );
}
