/**
 * Task 6: Node inspector — adapter slots + runtime commands.
 * Does not embed full legacy stage pages as nested workbenches.
 */
import { VButton, VSurface } from "../../../components/vui";
import {
  commandLabel,
  getNodeAdapter,
  type NodeAdapterSpec,
} from "./nodeAdapterModel";

import type { NodeOpsProjection } from "./nodeOpsProjection";

export type ResearchProcessNodeInspectorProps = {
  nodeId: string | null;
  runtimeCurrent: boolean;
  actorKind?: string;
  sessionAnchorDegraded?: boolean;
  chatDeepLink?: string | null;
  bindingLabel?: string;
  handoffPending?: boolean;
  busy?: boolean;
  ops?: NodeOpsProjection | null;
  onCommand?: (command: string, adapter: NodeAdapterSpec) => void;
};

export function ResearchProcessNodeInspector({
  nodeId,
  runtimeCurrent,
  actorKind,
  sessionAnchorDegraded,
  chatDeepLink,
  bindingLabel,
  handoffPending,
  busy,
  ops,
  onCommand,
}: ResearchProcessNodeInspectorProps) {
  const adapter = getNodeAdapter(nodeId);

  if (!adapter) {
    return (
      <VSurface tone="panel" className="min-h-[200px] p-3" data-vui="node-inspector-empty">
        <p className="m-0 text-sm text-[var(--fg-secondary)]">选择流程节点</p>
      </VSurface>
    );
  }

  return (
    <VSurface tone="panel" className="flex min-h-[200px] flex-col gap-3 p-3" data-vui="node-inspector">
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]">
            {adapter.stageId.replace(/_/g, " ")}
          </div>
          <h3 className="m-0 text-base font-semibold text-[var(--fg-primary)]">{adapter.label}</h3>
          <div className="mt-1 text-xs text-[var(--fg-secondary)]">
            {actorKind || adapter.actorKind}
            {runtimeCurrent ? " · 运行当前" : ""}
            {bindingLabel ? ` · ${bindingLabel}` : ""}
          </div>
        </div>
      </header>

      {ops?.blockedReason ? (
        <div className="rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]" role="status">
          {ops.blockedReason}
        </div>
      ) : null}

      <dl className="m-0 grid grid-cols-[88px_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="text-[var(--fg-tertiary)]">插槽</dt>
        <dd className="m-0 text-[var(--fg-primary)]">{adapter.slot}</dd>
        <dt className="text-[var(--fg-tertiary)]">会话</dt>
        <dd className="m-0 text-[var(--fg-primary)]">
          {adapter.actorKind !== "agent"
            ? "非 Agent 节点"
            : sessionAnchorDegraded
              ? "锚点不可用"
              : chatDeepLink
                ? "可打开精确会话"
                : "未绑定"}
        </dd>
        <dt className="text-[var(--fg-tertiary)]">交接</dt>
        <dd className="m-0 text-[var(--fg-primary)]">{handoffPending ? "等待人工" : "—"}</dd>
        {(ops?.facts || []).map((fact) => (
          <div key={fact.label} className="contents">
            <dt className="text-[var(--fg-tertiary)]">{fact.label}</dt>
            <dd className="m-0 text-[var(--fg-primary)]">{fact.value}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap gap-2">
        {adapter.commands.map((command) => {
          if (command === "open_session" && chatDeepLink && !sessionAnchorDegraded) {
            return (
              <a key={command} href={chatDeepLink} className="inline-flex">
                <VButton type="button" variant="ghost">
                  {commandLabel(command)}
                </VButton>
              </a>
            );
          }
          return (
            <VButton
              key={command}
              type="button"

              variant={command.startsWith("accept") ? "primary" : "ghost"}
              isDisabled={Boolean(busy)}
              onClick={() => onCommand?.(command, adapter)}
            >
              {commandLabel(command)}
            </VButton>
          );
        })}
      </div>

    </VSurface>
  );
}
