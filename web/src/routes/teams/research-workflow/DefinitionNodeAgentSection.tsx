import type { EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import { TeamSourceCollectionStageAgentsPanel } from "../source-collection/ui/TeamSourceCollectionStageAgentsPanel";
import { buildResearchAgentCard } from "./researchAgentCardModel";

export function DefinitionNodeAgentSection({
  binding,
}: {
  binding: EffectiveAgentBinding | null;
}) {
  if (!binding) return null;

  const card = buildResearchAgentCard({
    nodeId: binding.nodeId,
    roleKey: binding.roleKey,
    agentId: binding.agentId,
    agentName: binding.displayName || binding.agentId,
    resolvedFrom: binding.resolvedFrom,
    sessionBound: false,
  });

  return (
    <section data-vui="definition-node-agent-section">
      <TeamSourceCollectionStageAgentsPanel lang="zh" agents={[card]} layout="stacked" />
    </section>
  );
}
