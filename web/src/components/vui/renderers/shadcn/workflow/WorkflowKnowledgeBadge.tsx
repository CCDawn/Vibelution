import type { WorkflowKnowledgeBadgeInput } from "../../../product/workflow/workflowCanvasTypes";

/**
 * Compact knowledge-sideflow invocation counters for a node card. Rendered
 * through the node chrome's existing `badge` slot — never a second chrome.
 * Segments (知识/运行/交接/回写/失败) come only from the snapshot's
 * invocationBadges aggregates; no count is inferred from UI state.
 */
export function WorkflowKnowledgeBadge(props: { badge: WorkflowKnowledgeBadgeInput | null | undefined }) {
  const badge = props.badge;
  if (!badge || badge.total <= 0) return null;
  const failed = badge.failed ?? 0;
  const segments: string[] = [`知识 ${badge.total}`];
  if (badge.running > 0) segments.push(`运行 ${badge.running}`);
  if (badge.awaitingHandoff > 0) segments.push(`交接 ${badge.awaitingHandoff}`);
  if (badge.absorbed > 0) segments.push(`回写 ${badge.absorbed}`);
  if (failed > 0) segments.push(`失败 ${failed}`);
  const attention = badge.awaitingHandoff > 0 || failed > 0;
  // SCI-049 O-02: the waiting segment quotes the server-vouched auto-accept
  // cadence so the tooltip never presents the gate as a silent human wait.
  const autoAcceptSeconds = badge.autoAccept?.pending && badge.awaitingHandoff > 0
    ? Math.max(1, Math.round(badge.autoAccept.intervalMs / 1000))
    : null;
  const title = [
    `知识请求 ${badge.total} 个`,
    badge.running > 0 ? `运行中 ${badge.running}` : null,
    badge.awaitingHandoff > 0
      ? (autoAcceptSeconds !== null
        ? `等待交接 ${badge.awaitingHandoff} · 约 ${autoAcceptSeconds}s 内自动接受`
        : `等待交接 ${badge.awaitingHandoff}`)
      : null,
    badge.absorbed > 0 ? `已回写 ${badge.absorbed}` : null,
    failed > 0 ? `失败 ${failed}` : null,
    badge.knowledgeChildRunId ? `子运行 ${badge.knowledgeChildRunId}` : null,
    badge.currentKnowledgeNodeId ? `当前知识节点 ${badge.currentKnowledgeNodeId}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span
      data-vui="workflow-knowledge-badge"
      title={title}
      className={
        attention
          ? "inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--state-warning)_35%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-1.5 py-0.5 text-[10px] font-semibold leading-none text-[var(--state-warning)]"
          : "inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] px-1.5 py-0.5 text-[10px] font-semibold leading-none text-[var(--accent-cool)]"
      }
    >
      {segments.map((segment) => (
        <span key={segment}>{segment}</span>
      ))}
    </span>
  );
}
