/**
 * Wave 8Q+8R: replace inline shell/start mutations in TeamsRoute with hooks.
 * Usage (from web/): node scripts/wire-team-shell-start-mutations.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
let src = readFileSync(routePath, "utf8");

const start = src.indexOf("  const archiveTeamMutation = useMutation({");
const end = src.indexOf("  const {\n    createExperimentPlanMutation,");
if (start < 0 || end <= start) {
  console.error("markers not found", start, end);
  process.exit(1);
}

const hookBlock = `  const {
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairChallengeCupTeamAgentsMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
  } = useTeamShellMutations({
    selectedTeamId,
    setSelectedTeamId,
    setSelectedNodeId,
    clearTeamSearchParams: () => setSearchParams({}),
    setTeamMessage,
    setTeamTaskTopic,
    chatWorkspaceCache,
  });

  const {
    seedSourceCollectionAgentSessionContextMutation,
    startSourceCollectionStageSessionTaskMutation,
    startAiSearchRunMutation,
    startSourceCollectionRunMutation,
    startResearchStageRoundMutation,
  } = useTeamWorkflowStartMutations({
    selectedTeam,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionOwnerAgentId,
    sourceCollectionAgentIds,
    sourceCollectionStandalone,
    chatWorkspaceCache,
    setSelectedSourceCollectionRunId,
    setSourceCollectionStageSyncUntilMs,
    setSourceCollectionPendingStageTaskIds,
    setSourceCollectionOutputDraft,
    setResearchWorkspaceView,
    navigateToSourceCollection: (teamId) => navigate(researchSourceCollectionRoute(teamId)),
  });

`;

src = src.slice(0, start) + hookBlock + src.slice(end);

// Imports
if (!src.includes('useTeamShellMutations')) {
  src = src.replace(
    'import { useTeamSourceCollectionMutations } from "./teams/useTeamSourceCollectionMutations";',
    `import { useTeamSourceCollectionMutations } from "./teams/useTeamSourceCollectionMutations";
import { useTeamShellMutations } from "./teams/useTeamShellMutations";
import { useTeamWorkflowStartMutations } from "./teams/useTeamWorkflowStartMutations";
import type { ResearchStageRoundStartPayload } from "./teams/workflowStartMutationModel";`,
  );
}

// Remove local ResearchStageRoundStartPayload type
const typeStart = src.indexOf("type ResearchStageRoundStartPayload = {");
if (typeStart >= 0) {
  const typeEnd = src.indexOf("\n\ntype NodeDragState", typeStart);
  if (typeEnd > typeStart) {
    src = src.slice(0, typeStart) + src.slice(typeEnd + 2);
  }
}

// Remove unused bus imports if only used by mutations - check still used in route body
// sendTeamProjectBusMessage / revoke - might only be in hooks now

writeFileSync(routePath, src);
console.log("wired shell+start mutations, delta", src.length);
