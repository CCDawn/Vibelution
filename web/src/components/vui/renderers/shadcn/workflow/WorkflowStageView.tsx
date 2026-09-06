import { useLayoutEffect, useRef } from "react";
import type { ShadcnWorkflowCanvasProps } from "./ShadcnWorkflowCanvas";
import { resolveNodeStatusVisual } from "./workflowCanvasState";
import { cn } from "../../../lib/cn";
import { VNativeButton } from "../../../primitives/VNativeButton";

/** A readable projection of the SAME graph. Dependencies are explicit links,
 * never inferred from card order; cross-stage links retain their real target. */
export function WorkflowStageView(props: ShadcnWorkflowCanvasProps) {
  const host = useRef<HTMLDivElement>(null);
  const selected = props.graph.nodes.find((node) => node.nodeId === props.selectedNodeId);
  const current = props.graph.nodes.find((node) => props.runtimeCurrentNodeIds?.includes(node.nodeId));
  const stageId = selected?.stageId ?? current?.stageId ?? props.graph.stages[0]?.stageId;
  const stage = props.graph.stages.find((item) => item.stageId === stageId);
  const nodes = props.graph.nodes.filter((node) => node.stageId === stageId);
  useLayoutEffect(() => {
    host.current?.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: "nearest" });
  }, [props.selectedNodeId]);
  return <div ref={host} className={cn("h-full min-h-0 overflow-auto bg-[var(--vui-surface-canvas)] p-4", props.className)} style={{ height: props.height }} data-testid="workflow-stage-view">
    <header className="mb-4">
      <h2 className="text-base font-semibold">{stage?.label ?? "研究阶段"}</h2>
      <p className="mt-1 text-xs text-[var(--fg-secondary)]">选择节点查看详情，点击依赖入口前往关联任务。</p>
    </header>
    <div className="mx-auto grid max-w-[800px] gap-4" style={{gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 260px), 1fr))"}}>
      {nodes.map((node) => {
        const visual = resolveNodeStatusVisual(node.status);
        const isCurrent = props.runtimeCurrentNodeIds?.includes(node.nodeId) ?? false;
        const outgoing = props.graph.edges.filter((edge) => edge.fromNodeId === node.nodeId);
        return <article key={node.nodeId} className={cn("min-w-0 rounded-xl border bg-[var(--vui-surface-panel)]", visual.borderClass)} data-node-id={node.nodeId} data-node-status={node.status}>
          <VNativeButton type="button" aria-pressed={node.nodeId === props.selectedNodeId} onClick={() => props.onSelectNode?.(node.nodeId)}
            className="flex min-h-[122px] w-full flex-col gap-2 rounded-xl p-4 text-left outline-none hover:bg-[var(--vui-surface-row)] focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] aria-pressed:ring-2 aria-pressed:ring-[var(--accent-cool)]">
            <span className="flex w-full flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-[var(--fg-secondary)]">{isCurrent ? "当前任务" : node.actorKind === "human" ? "人工确认" : node.actorKind === "agent" ? "Agent 任务" : "系统任务"}</span>
              <span className={cn("rounded-full border px-2 py-0.5", visual.badgeClass)}>{visual.statusLabel}</span>
            </span>
            <span className="text-[15px] font-semibold leading-6">{node.label}</span>
            {node.description ? <span className="text-xs leading-5 text-[var(--fg-secondary)]">{node.description}</span> : null}
            {node.blockedReason ? <span className="text-xs text-[var(--state-warning)]">{node.blockedReason}</span> : null}
            {node.knowledgeBadge ? <span className="text-xs text-[var(--fg-secondary)]">知识子任务 {node.knowledgeBadge.total} · 进行中 {node.knowledgeBadge.running} · 待交接 {node.knowledgeBadge.awaitingHandoff}</span> : null}
          </VNativeButton>
          {outgoing.length ? <ul aria-label={`${node.label}的后续依赖`} className="space-y-1 border-t border-[var(--vui-border-subtle)] px-4 py-2">
            {outgoing.map((edge) => {
              const target = props.graph.nodes.find((item) => item.nodeId === edge.toNodeId);
              if (!target) return null;
              return <li key={edge.edgeId} data-edge-id={edge.edgeId} data-path-state={edge.pathState} className="text-xs">
                <VNativeButton type="button" onClick={() => props.onSelectNode?.(target.nodeId)} className="inline rounded py-1 text-left text-[var(--accent-cool)] underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2">
                  {edge.label ? `${edge.label} → ` : "→ "}{target.label}{target.stageId !== stageId ? "（跨阶段）" : ""}
                </VNativeButton>
              </li>;
            })}
          </ul> : null}
        </article>;
      })}
    </div>
    {!nodes.length ? <p role="status">此阶段没有可展示的节点。</p> : null}
  </div>;
}
