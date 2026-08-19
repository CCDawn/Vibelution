import type { EffectiveAgentBinding, ResearchBudgetProjection, WorkflowDefinition } from "../../../api/types/researchWorkflow";
import { VEmptyState, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { DefinitionNodeAgentSection } from "./DefinitionNodeAgentSection";
import { getNodeAdapter } from "./nodeAdapterModel";
import { researchStageLabel } from "./researchNodePresentation";
import styles from "./ResearchProcessDefinitionNodePanel.styles";

export type ResearchProcessDefinitionNodePanelProps = {
  teamId: string;
  nodeId: string;
  definition: WorkflowDefinition;
  effectiveBindings: EffectiveAgentBinding[] | null;
  budget?: ResearchBudgetProjection | null;
};

export function ResearchProcessDefinitionNodePanel({
  teamId,
  nodeId,
  definition,
  effectiveBindings,
  budget = null,
}: ResearchProcessDefinitionNodePanelProps) {
  const { lang } = useShellI18n();
  const node = definition.nodes.find((item) => item.nodeId === nodeId);
  if (!node) {
    return (
      <VEmptyState title={lang === "zh" ? "节点不存在" : "Node not found"}>
        {lang === "zh" ? "工作流定义中没有找到该节点。" : "The workflow definition does not include this node."}
      </VEmptyState>
    );
  }
  const adapter = getNodeAdapter(nodeId);
  const binding = effectiveBindings?.find((item) => item.nodeId === nodeId) ?? null;

  return (
    <VSurface tone="panel" className={styles.panel} data-vui="definition-node-detail">
      {node.actorKind === "agent" ? (
        <DefinitionNodeAgentSection
          teamId={teamId}
          nodeId={nodeId}
          stageId={adapter?.stageId || ""}
          stageLabel={researchStageLabel(adapter?.stageId || "")}
          title={node.label}
          binding={binding}
          effectiveBindings={effectiveBindings}
          budget={budget}
          lang={lang}
        />
      ) : (
        <header>
          <div className={styles.stage}>{researchStageLabel(adapter?.stageId || "")}</div>
          <h3 className={styles.title}>{node.label}</h3>
        </header>
      )}
      {node.description ? <p className={styles.description}>{node.description}</p> : null}
    </VSurface>
  );
}
