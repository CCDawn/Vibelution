import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import { TeamSourceCollectionStageAgentsPanel } from "../source-collection/ui/TeamSourceCollectionStageAgentsPanel";
import { buildResearchAgentCard } from "./researchAgentCardModel";

export function NodeAgentSection({ detail }: { detail: ResearchWorkflowNodeDetail }) {
  const snapshot = detail.bindingSnapshot ?? {};
  const agentId = String(snapshot.agentId || "");
  const card = buildResearchAgentCard({
    nodeId: detail.nodeId,
    roleKey: detail.primaryRoleKey,
    roleLabel: detail.label,
    agentId,
    agentName: String(snapshot.displayName || agentId),
    resolvedFrom: String(snapshot.resolvedFrom || "unbound"),
    sessionBound: Boolean(detail.sessionBinding?.sessionId && detail.sessionBinding.status === "bound"),
  });
  return (
    <section data-vui="node-agent-section">
      <TeamSourceCollectionStageAgentsPanel lang="zh" agents={[card]} />
    </section>
  );
}
