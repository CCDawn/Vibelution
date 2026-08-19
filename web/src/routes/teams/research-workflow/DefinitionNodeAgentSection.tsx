import type { EffectiveAgentBinding, ResearchBudgetProjection } from "../../../api/types/researchWorkflow";
import { NodeInspectorOpsSection } from "./NodeInspectorOpsSection";

export function DefinitionNodeAgentSection(props: {
  teamId: string;
  nodeId: string;
  stageId: string;
  stageLabel: string;
  title: string;
  binding: EffectiveAgentBinding | null;
  effectiveBindings: EffectiveAgentBinding[] | null;
  budget?: ResearchBudgetProjection | null;
  lang?: "zh" | "en";
}) {
  const agentId = String(props.binding?.agentId || "");
  return (
    <section data-vui="definition-node-agent-section">
      <NodeInspectorOpsSection
        teamId={props.teamId}
        nodeId={props.nodeId}
        stageId={props.stageId}
        stageLabel={props.stageLabel}
        title={props.title}
        agentId={agentId}
        agentName={String(props.binding?.displayName || agentId)}
        unbound={!agentId}
        canRebindAgent
        effectiveBindings={props.effectiveBindings}
        budget={props.budget ?? null}
        primaryOffer={null}
        busy={false}
        sessionHref={null}
        lang={props.lang}
      />
    </section>
  );
}
