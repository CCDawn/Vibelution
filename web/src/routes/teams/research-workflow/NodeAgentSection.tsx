import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { TeamSourceCollectionStageAgentsPanel } from "../source-collection/ui/TeamSourceCollectionStageAgentsPanel";
import { buildResearchAgentCard } from "./researchAgentCardModel";

export function NodeAgentSection({ detail }: { detail: ResearchWorkflowNodeDetail }) {
  const agentId = String(detail.agentId || "");
  const card = buildResearchAgentCard({
    nodeId: detail.nodeId,
    roleKey: detail.primaryRoleKey,
    roleLabel: detail.label,
    agentId,
    agentName: String(detail.displayName || agentId),
    resolvedFrom: String(detail.resolvedFrom || "unbound"),
    sessionBound: Boolean(detail.sessionId && !detail.sessionAnchorDegraded),
  });
  return (
    <section data-vui="node-agent-section">
      <TeamSourceCollectionStageAgentsPanel lang="zh" agents={[card]} />
    </section>
  );
}
