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
            <VButton type="button" variant="ghost" size="sm" onClick={() => replaceParams({ panel: "agents" })}>
              Agent
            </VButton>
            <VButton type="button" variant="ghost" size="sm" onClick={() => replaceParams({ panel: "timeline" })}>
              时间线
            </VButton>
            {projection?.run.runtimeCurrentNodeIds?.length ? (
              <VButton type="button" variant="ghost" size="sm" onClick={jumpToRuntime}>
                当前节点
              </VButton>
            ) : null}
            {!runId ? (
              <VButton type="button" size="sm" onClick={onCreateRun} disabled={busy}>
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
        <VSurface tone="panel" className="min-h-[200px] p-3" data-panel={panel}>
          {panel === "agents" ? (
            <div className="space-y-2 text-sm">
              <strong>Agent 分工</strong>
              <p className="text-vui-muted">绑定解析来自 run snapshot，不维护第二份配置表。</p>
              <ul className="space-y-1">
                {(run?.bindingSnapshots || []).map((snap) => (
                  <li key={String(snap.snapshotId || snap.nodeId)} className="rounded border border-vui-border px-2 py-1">
                    <span className="font-medium">{String(snap.nodeId)}</span>
                    {" · "}
                    {String(snap.agentId || "未绑定")}
                    {" · "}
                    {String(snap.resolvedFrom || "")}
                  </li>
                ))}
              </ul>
            </div>
          ) : panel === "timeline" ? (
            <div className="space-y-2 text-sm">
              <strong>运行事件</strong>
              <ul className="space-y-1">
                {(run?.events || []).map((evt) => (
                  <li key={String(evt.eventId || evt.sequence)} className="rounded border border-vui-border px-2 py-1">
                    #{String(evt.sequence)} {String(evt.type)} {String(evt.nodeId || "")}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="space-y-3 text-sm">
              <strong>{selectedNodeId || "未选中节点"}</strong>
              {nodeDetail ? (
                <dl className="grid grid-cols-[100px_1fr] gap-1">
                  <dt className="text-vui-muted">actor</dt>
                  <dd>{String(nodeDetail.actorKind || "")}</dd>
                  <dt className="text-vui-muted">runtime</dt>
                  <dd>{nodeDetail.runtimeCurrent ? "当前" : "非当前"}</dd>
                  <dt className="text-vui-muted">会话锚点</dt>
                  <dd>
                    {nodeDetail.sessionAnchorDegraded
                      ? "不可用（degraded）"
                      : String((nodeDetail.chatDeepLink as string) || "—")}
                  </dd>
                </dl>
              ) : (
                <p className="text-vui-muted">选择节点查看检查器。</p>
              )}
              {run?.status === "waiting_human" && run.humanTasks?.length ? (
                <div className="flex gap-2">
                  <VButton type="button" size="sm" onClick={() => onResolveHuman(true)} disabled={busy}>
                    接受交接
                  </VButton>
                  <VButton type="button" size="sm" variant="ghost" onClick={() => onResolveHuman(false)} disabled={busy}>
                    拒绝
                  </VButton>
                </div>
              ) : null}
            </div>
          )}
        </VSurface>

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
