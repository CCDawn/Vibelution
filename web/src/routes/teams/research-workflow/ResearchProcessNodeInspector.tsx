/**
 * Node inspector — single-canvas node detail surface.
 *
 * Renders the BACKEND node detail: binding snapshot (source / agent name /
 * role), session anchor status, handoff state, attempt, blocked reason,
 * artifacts and the backend-declared command capabilities. Commands are only
 * clickable when the backend reports them available; everything else renders
 * as a disabled button with the explicit reason (no fake buttons).
 */
import { VButton, VEmptyState, VSurface } from "../../../components/vui";
import type {
  NodeCommandCapability,
  ResearchWorkflowNodeDetail,
} from "../../../api/types/researchWorkflow";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { commandLabel } from "./nodeCommandAdapter";

export type ResearchProcessNodeInspectorProps = {
  nodeId: string | null;
  adapter: NodeAdapterSpec | null;
  detail: ResearchWorkflowNodeDetail | null;
  handoffPending: boolean;
  busy: boolean;
  onCommand: (command: string) => void;
  /** Opens a stage drawer panel (experiment/knowledge) from the node. */
  onOpenPanel?: (panel: "experiment" | "knowledge") => void;
};

const DRAWER_PANEL_LABELS: Record<"experiment" | "knowledge", { zh: string; en: string }> = {
  experiment: { zh: "打开实验设计面板", en: "Open experiment design" },
  knowledge: { zh: "打开知识搜集面板", en: "Open knowledge collection" },
};

function bindingSourceLabel(source: string | undefined): string {
  const labels: Record<string, string> = {
    workflow_default: "团队/工作流默认",
    stage_override: "阶段覆盖",
    node_override: "节点覆盖",
    rebind: "运行内换绑",
    unbound: "未绑定",
  };
  return labels[source ?? ""] ?? source ?? "—";
}

function commandDisabledTitle(capability: NodeCommandCapability): string {
  if (!capability.available) {
    return capability.reason || "该操作当前不可用";
  }
  if (capability.command === "build_package" || capability.command === "open_evidence_graph") {
    return "该服务尚未接入后端";
  }
  return "";
}

export function ResearchProcessNodeInspector({
  nodeId,
  adapter,
  detail,
  handoffPending,
  busy,
  onCommand,
  onOpenPanel,
}: ResearchProcessNodeInspectorProps) {
  if (!adapter) {
    return (
      <div
        className="flex h-full min-h-0 flex-col items-stretch justify-center p-3"
        data-vui="node-inspector-empty"
      >
        <VEmptyState title="选择流程节点" className="h-auto w-full border-0 bg-transparent">
          在画布上点击任务节点，查看绑定、会话与运行命令。
        </VEmptyState>
      </div>
    );
  }

  const snapshot = detail?.bindingSnapshot ?? {};
  const sessionBinding = detail?.sessionBinding ?? null;
  const agentName =
    String(snapshot.displayName || "") || String(snapshot.agentId || "") || "";
  const isAgent = adapter.actorKind === "agent";
  const capabilities = detail?.commands ?? [];

  return (
    <VSurface
      tone="panel"
      className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3"
      data-vui="node-inspector"
    >
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]">
            {adapter.stageId.replace(/_/g, " ")}
          </div>
          <h3 className="m-0 text-base font-semibold text-[var(--fg-primary)]">
            {detail?.label || adapter.label}
          </h3>
          <div className="mt-1 text-xs text-[var(--fg-secondary)]">
            {adapter.actorKind}
            {detail?.runtimeCurrent ? " · 运行当前" : ""}
            {detail?.nodeAttempt ? ` · 第 ${detail.nodeAttempt} 次尝试` : ""}
          </div>
        </div>
      </header>

      {detail?.blockedReason ? (
        <div
          className="rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]"
          role="status"
        >
          阻塞原因：{detail.blockedReason}
        </div>
      ) : null}

      <dl className="m-0 grid grid-cols-[88px_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="text-[var(--fg-tertiary)]">角色</dt>
        <dd className="m-0 text-[var(--fg-primary)]">{detail?.primaryRoleKey || adapter.slot}</dd>
        <dt className="text-[var(--fg-tertiary)]">绑定 Agent</dt>
        <dd className="m-0 min-w-0 text-[var(--fg-primary)]">
          {isAgent ? (agentName || "未绑定") : "非 Agent 节点"}
        </dd>
        <dt className="text-[var(--fg-tertiary)]">绑定来源</dt>
        <dd className="m-0 text-[var(--fg-primary)]">
          {bindingSourceLabel(String(snapshot.resolvedFrom || ""))}
        </dd>
        <dt className="text-[var(--fg-tertiary)]">Agent ID</dt>
        <dd className="m-0 break-all text-[var(--fg-primary)]">
          {String(snapshot.agentId || "—")}
        </dd>
        <dt className="text-[var(--fg-tertiary)]">会话</dt>
        <dd className="m-0 text-[var(--fg-primary)]">
          {!isAgent
            ? "非 Agent 节点"
            : detail?.sessionAnchorDegraded
              ? "会话锚点不可用"
              : detail?.chatDeepLink
                ? "已绑定精确会话"
                : "未绑定会话"}
        </dd>
        <dt className="text-[var(--fg-tertiary)]">交接</dt>
        <dd className="m-0 text-[var(--fg-primary)]">{handoffPending ? "等待人工" : "—"}</dd>
      </dl>

      {sessionBinding && sessionBinding.sessionId ? (
        <div className="rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]" data-vui="session-anchor">
          <div className="break-all">会话：{sessionBinding.sessionId}</div>
          <div className="break-all">任务：{sessionBinding.taskId}</div>
          <div className="break-all">轮次：{sessionBinding.turnId}</div>
        </div>
      ) : null}

      {Object.keys(detail?.artifacts ?? {}).length > 0 ? (
        <div data-vui="node-artifacts">
          <div className="text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]">
            产物
          </div>
          <ul className="m-0 list-none p-0 text-xs text-[var(--fg-primary)]">
            {Object.entries(detail!.artifacts).map(([key, value]) => (
              <li key={key} className="break-all">
                {key}: {typeof value === "string" ? value : JSON.stringify(value)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2" data-vui="node-commands">
        {adapter.drawerPanel && onOpenPanel ? (
          <VButton
            type="button"
            variant="secondary"
            onClick={() => onOpenPanel(adapter.drawerPanel!)}
            title={DRAWER_PANEL_LABELS[adapter.drawerPanel].zh}
          >
            {DRAWER_PANEL_LABELS[adapter.drawerPanel].zh}
          </VButton>
        ) : null}
        {capabilities.map((capability) => {
          const disabledTitle = commandDisabledTitle(capability);
          if (capability.command === "open_session") {
            const canOpen = Boolean(detail?.chatDeepLink) && !detail?.sessionAnchorDegraded;
            if (canOpen) {
              return (
                <a key={capability.command} href={detail!.chatDeepLink!} className="inline-flex">
                  <VButton type="button" variant="ghost">
                    {commandLabel(capability.command)}
                  </VButton>
                </a>
              );
            }
            return (
              <VButton
                key={capability.command}
                type="button"
                variant="ghost"
                isDisabled
                title={disabledTitle || "会话锚点不可用"}
              >
                {commandLabel(capability.command)}
              </VButton>
            );
          }
          return (
            <VButton
              key={capability.command}
              type="button"
              variant={capability.command.startsWith("accept") ? "primary" : "ghost"}
              isDisabled={Boolean(busy) || Boolean(disabledTitle)}
              title={disabledTitle || undefined}
              onClick={() => onCommand(capability.command)}
            >
              {commandLabel(capability.command)}
            </VButton>
          );
        })}
      </div>
    </VSurface>
  );
}
