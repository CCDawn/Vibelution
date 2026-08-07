/**
 * Canonical single-canvas research process workspace (Task 5).
 * One stage-navigation surface: VWorkflowCanvas. Selection is UI-only.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  createResearchWorkflowRun,
  fetchResearchWorkflowCanvas,
  fetchResearchWorkflowDefinition,
  fetchResearchWorkflowNodeDetail,
  resolveResearchWorkflowHumanTask,
  type WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VPanelHeader,
  VSurface,
  VWorkflowCanvas,
} from "../../../components/vui";
import { definitionToCanvasGraph, projectionToCanvasGraph } from "./researchProcessGraphModel";
import { buildCanonicalWorkflowSearch } from "./researchLegacyRouteResolver";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { projectNodeOps } from "./nodeOpsProjection";

type PanelKind = "node" | "agents" | "team" | "timeline";

export type ResearchProcessWorkspaceProps = {
  teamId?: string;
};

export function ResearchProcessWorkspace({ teamId = "" }: ResearchProcessWorkspaceProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("runId") || "";
  const selectedNodeId = searchParams.get("node") || null;
  const panel = (searchParams.get("panel") as PanelKind | null) || "node";

  const [projection, setProjection] = useState<WorkflowCanvasProjection | null>(null);
  const [run, setRun] = useState<WorkflowRunRecord | null>(null);
  const [nodeDetail, setNodeDetail] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  const loadDefinitionOnly = useCallback(async () => {
    const def = await fetchResearchWorkflowDefinition();
    setProjection({
      definition: def.definition,
      run: {
        runId: null,
        status: null,
        runtimeCurrentNodeIds: [],
        nodeRuns: {},
        pendingHumanTasks: [],
      },
    });
  }, []);

  const refreshRun = useCallback(async (id: string) => {
    const canvas = await fetchResearchWorkflowCanvas(id);
    setProjection(canvas);
    setRun({
      runId: id,
      workflowId: canvas.definition.workflowId,
      workflowVersionId: "",
      status: canvas.run.status || "",
      runtimeCurrentNodeIds: canvas.run.runtimeCurrentNodeIds,
      humanTasks: canvas.run.pendingHumanTasks as unknown as Array<Record<string, unknown>>,
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setError(null);
        if (runId) {
          await refreshRun(runId);
        } else {
          await loadDefinitionOnly();
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, refreshRun, loadDefinitionOnly]);

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
  }, [runId, selectedNodeId]);

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
    setBusy(true);
    setError(null);
    try {
      const created = await createResearchWorkflowRun({
        teamId,
        idempotencyKey: `ui-${teamId || "default"}-${Date.now()}`,
      });
      replaceParams({
        runId: created.runId,
        node: created.runtimeCurrentNodeIds?.[0] || "knowledge_handoff",
      });
      setRun(created);
      await refreshRun(created.runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [teamId, replaceParams, refreshRun]);

  const onResolveHuman = useCallback(
    async (accept: boolean) => {
      if (!runId || !run?.humanTasks?.length) return;
      const taskId = String(run.humanTasks[0].taskId || "");
      if (!taskId) return;
      setBusy(true);
      try {
        const next = await resolveResearchWorkflowHumanTask(runId, taskId, { accept });
        setRun(next);
        await refreshRun(runId);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [runId, run, refreshRun],
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
      // Other commands are adapter-declared slots; stage services wire in later Task 6 mounts.
      setError(null);
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

  return (
    <VSurface tone="workspace" className="flex min-h-0 flex-1 flex-col gap-3 p-3" data-vui="research-process-workspace">
      <VPanelHeader
        title="科研流程"
        eyebrow={
          runId
            ? `Run ${runId} · ${run?.status || projection?.run.status || ""}`
            : "固定模板 · 创建运行后由 LangGraph 驱动"
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <VButton type="button" variant="ghost" onClick={() => replaceParams({ panel: "agents" })}>
              Agent
            </VButton>
            <VButton type="button" variant="ghost" onClick={() => replaceParams({ panel: "timeline" })}>
              时间线
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

      {error ? (
        <div className="rounded-lg border border-vui-border bg-vui-surface-inset px-3 py-2 text-sm text-vui-fg" role="alert">
          {error}
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
        <div className="flex h-[440px] items-center justify-center rounded-xl border border-vui-border text-sm text-vui-muted">
          加载流程定义…
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div data-panel={panel}>
          {panel === "agents" ? (
            <VSurface tone="panel" className="min-h-[200px] space-y-2 p-3 text-sm">
              <strong>Agent 分工</strong>
              <p className="m-0 text-[var(--fg-secondary)]">绑定来自 run snapshot，不维护第二份数据。</p>
              <ul className="m-0 list-none space-y-1 p-0">
                {(run?.bindingSnapshots || []).map((snap) => (
                  <li key={String(snap.snapshotId || snap.nodeId)} className="rounded border border-[var(--border-subtle)] px-2 py-1">
                    <span className="font-medium">{String(snap.nodeId)}</span>
                    {" · "}
                    {String(snap.agentId || "未绑定")}
                    {" · "}
                    {String(snap.resolvedFrom || "")}
                  </li>
                ))}
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
              </ul>
            </VSurface>
          ) : (
            <ResearchProcessNodeInspector
              nodeId={selectedNodeId}
              runtimeCurrent={runtimeCurrent || Boolean(nodeDetail?.runtimeCurrent)}
              actorKind={String(nodeDetail?.actorKind || "")}
              sessionAnchorDegraded={Boolean(nodeDetail?.sessionAnchorDegraded)}
              chatDeepLink={(nodeDetail?.chatDeepLink as string) || null}
              bindingLabel={String((nodeDetail?.bindingSnapshot as { agentId?: string } | undefined)?.agentId || "")}
              handoffPending={run?.status === "waiting_human"}
              busy={busy}
              ops={nodeOps}
              onCommand={onInspectorCommand}
            />
          )}
        </div>

        <VSurface tone="inset" className="p-3 text-xs text-vui-muted">
          <div>canonical</div>
          <code className="mt-1 block break-all text-[11px] text-vui-fg">
            {buildCanonicalWorkflowSearch({
              teamId,
              runId: runId || undefined,
              node: selectedNodeId || undefined,
              panel: panel !== "node" ? panel : undefined,
            })}
          </code>
        </VSurface>
      </div>
    </VSurface>
  );
}
