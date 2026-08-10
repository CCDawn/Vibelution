import type { EffectiveAgentBinding, WorkflowDefinition } from "../../../api/types/researchWorkflow";
import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";
import { DefinitionNodeAgentSection } from "./DefinitionNodeAgentSection";
import styles from "./ResearchProcessDefinitionNodePanel.styles";

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

  return (
    <VSurface tone="panel" className={styles.panel} data-vui="definition-node-detail">
      <VPanelHeader title={node.label} headingLevel={3} />
      <dl className={styles.detailGrid}>
        <dt className={styles.dt}>执行者</dt>
        <dd className={styles.dd}>{node.actorKind}</dd>
        <dt className={styles.dt}>角色</dt>
        <dd className={styles.dd}>{node.primaryRoleKey}</dd>
      </dl>
      {node.actorKind === "agent" ? <DefinitionNodeAgentSection binding={binding} /> : null}
      {node.description ? <p className={styles.description}>{node.description}</p> : null}
    </VSurface>
  );
}
