import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const hookSource = readFileSync(new URL("./useTeamsCatalogQueries.ts", import.meta.url), "utf8");

describe("useTeamsCatalogQueries R2-d contract", () => {
  it("owns teams list, agent summary, project bus, and picker derivation", () => {
    expect(hookSource).toContain("export function useTeamsCatalogQueries");
    expect(hookSource).toContain('fetchJson<TeamListPayload>("/api/teams"');
    expect(hookSource).toContain("listAgentSummaries<AgentConfigWorkspaceAgent>({ signal })");
    expect(hookSource).toContain("queryKeys.agentSummary(false)");
    expect(hookSource).toContain("listProjectAgentBusTimeline");
    expect(hookSource).toContain("TEAM_PICKER_TEAM_IDS");
    expect(hookSource).toContain("agentTeamMembership");
    expect(hookSource).toContain("fallbackVisibleTeamId");
  });

  it("is consumed by the workbench model without re-declaring catalog list queries", () => {
    expect(routeModelSource).toContain("useTeamsCatalogQueries({");
    expect(routeModelSource).not.toContain("const teamsQuery = useQuery({");
    expect(routeModelSource).not.toContain('fetchJson<AgentConfigWorkspaceAgent[]>("/api/agents?detail=summary"');
    expect(routeModelSource).not.toContain("listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT");
  });
});
