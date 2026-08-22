import { describe, expect, it } from "vitest";

import routeShellSource from "./TeamsRouteWorkbench.tsx?raw";
import routeModelSourceThin from "./useTeamsWorkbenchModel.tsx?raw";
import routeFoundationSource from "./useTeamsWorkbenchFoundation.tsx?raw";
import routeShellPhaseSource from "./useTeamsWorkbenchShellPhase.tsx?raw";
const routeModelSource = `${routeModelSourceThin}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
import mutationBundleSource from "./useTeamsMutationBundle.ts?raw";
const routeSource = `${routeShellSource}\n${routeModelSource}\n${routeFoundationSource}\n${routeShellPhaseSource}\n${mutationBundleSource}`;
import mutationsSource from "./useTeamShellMutations.ts?raw";

const mutationOwners = [
  "archiveTeamMutation",
  "saveCanvasMutation",
  "sendTeamMessageMutation",
  "revokeTeamMessageMutation",
  "syncTeamChatRoomMutation",
  "repairChallengeCupTeamAgentsMutation",
  "repairKnowledgeExpansionTeamAgentsMutation",
  "startTeamRoundMutation",
  "stopTeamRoundMutation",
] as const;

describe("team shell mutations contract", () => {
  it("owns the team shell write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(mutationOwners.length);
    mutationOwners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
      expect(mutationsSource).toContain(`${owner},`);
    });
  });

  it("stays free of streaming, local UI state, and navigation", () => {
    expect(mutationsSource).not.toMatch(/\bnew EventSource\b/);
    expect(mutationsSource).not.toContain("useState");
    expect(mutationsSource).not.toContain("useEffect");
    expect(mutationsSource).not.toContain("useNavigate");
    expect(mutationsSource).not.toContain("react-router-dom");
  });

  it("is wired from TeamsRoute while Route no longer defines those mutations inline", () => {
    // R2-g: model owns useTeamsMutationBundle; bundle owns useTeamShellMutations.
    expect(routeModelSource).toContain("useTeamsMutationBundle({");
    expect(mutationBundleSource).toContain("useTeamShellMutations({");
    mutationOwners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("preserves key shell write endpoints", () => {
    expect(mutationsSource).toContain("archiveTeam(");
    expect(mutationsSource).toContain("saveTeamCanvas(");
    expect(mutationsSource).toContain("sendTeamProjectBusMessage");
    expect(mutationsSource).toContain("revokeProjectAgentBusMessage");
    expect(mutationsSource).toContain("syncTeamChatRoom(");
    expect(mutationsSource).toContain("repairChallengeCupTeamAgents(");
    expect(mutationsSource).toContain("repairKnowledgeExpansionTeamAgents(");
    expect(mutationsSource).toContain("startChatRoomRound(");
    expect(mutationsSource).toContain("stopChatRoomRound(");
    expect(mutationsSource).toContain('source: "team_workspace"');
  });
});
