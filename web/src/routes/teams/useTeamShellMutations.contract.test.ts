import { describe, expect, it } from "vitest";

import routeSource from "../TeamsRoute.tsx?raw";
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
    expect(routeSource).toContain("useTeamShellMutations({");
    mutationOwners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("preserves key shell write endpoints", () => {
    expect(mutationsSource).toContain('method: "DELETE"');
    expect(mutationsSource).toContain("/canvas");
    expect(mutationsSource).toContain("sendTeamProjectBusMessage");
    expect(mutationsSource).toContain("revokeProjectAgentBusMessage");
    expect(mutationsSource).toContain("/chat-room/sync");
    expect(mutationsSource).toContain("/challenge-cup-agents/repair");
    expect(mutationsSource).toContain("/knowledge-expansion-agents/repair");
    expect(mutationsSource).toContain("/rounds");
    expect(mutationsSource).toContain('source: "team_workspace"');
  });
});
