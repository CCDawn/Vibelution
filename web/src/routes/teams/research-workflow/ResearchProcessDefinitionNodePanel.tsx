import type { EffectiveAgentBinding, WorkflowDefinition } from "../../../api/types/researchWorkflow";
import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";

export type ResearchProcessDefinitionNodePanelProps = {
  nodeId: string;
  definition: WorkflowDefinition;
  effectiveBindings: EffectiveAgentBinding[] | null;
};

export function ResearchProcessDefinitionNodePanel({
  nodeId,
  definition,
  effectiveBindings,
}: ResearchProcessDefinitionNodePanelProps) {
  const node = definition.nodes.find((item) => item.nodeId === nodeId);
  if (!node) {
    return <VEmptyState title="节点不存在">工作流定义中没有找到该节点。</VEmptyState>;
  }
  const binding = effectiveBindings?.find((item) => item.nodeId === nodeId) ?? null;
  const agentId = binding?.agentId || "未绑定";

  return (
    <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3" data-vui="definition-node-detail">
      <VPanelHeader title={node.label} headingLevel={3} />
      <dl className="m-0 grid grid-cols-[88px_1fr] gap-x-2 gap-y-2 text-sm">
        <dt className="text-[var(--fg-tertiary)]">执行者</dt>
        <dd className="m-0 text-[var(--fg-primary)]">{node.actorKind}</dd>
        <dt className="text-[var(--fg-tertiary)]">角色</dt>
        <dd className="m-0 text-[var(--fg-primary)]">{node.primaryRoleKey}</dd>
        <dt className="text-[var(--fg-tertiary)]">Agent</dt>
        <dd className="m-0 break-all text-[var(--fg-primary)]">{agentId}</dd>
      </dl>
      {node.description ? <p className="m-0 text-sm text-[var(--fg-secondary)]">{node.description}</p> : null}
    </VSurface>
  );
}
