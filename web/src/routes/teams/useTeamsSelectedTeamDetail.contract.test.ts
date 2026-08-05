import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const hookSource = readFileSync(new URL("./useTeamsSelectedTeamDetail.ts", import.meta.url), "utf8");
const chromeSource = readFileSync(new URL("./teamsWorkbenchChrome.ts", import.meta.url), "utf8");
const demandSource = readFileSync(new URL("./teamWorkflowResourceDemand.ts", import.meta.url), "utf8");

describe("useTeamsSelectedTeamDetail R2-e contract", () => {
  it("owns team detail query, kind flags, and SC workspace selection", () => {
    expect(hookSource).toContain("export function useTeamsSelectedTeamDetail");
    expect(hookSource).toContain("queryKeys.team(effectiveTeamId, teamDetailLoadMode)");
    expect(hookSource).toContain("isResearchWorkflowTeam(selectedTeam)");
    expect(hookSource).toContain("sourceCollectionWorkspaceSelected");
    expect(hookSource).toContain("useResearchProjectAgentTasks");
  });

  it("is consumed by the workbench model without re-declaring team detail query", () => {
    expect(routeModelSource).toContain("useTeamsSelectedTeamDetail({");
    expect(routeModelSource).not.toContain("const teamDetailQuery = useQuery<Team>({");
    expect(routeModelSource).not.toContain("const researchWorkflowTeamSelected = isResearchWorkflowTeam(selectedTeam)");
  });
});

describe("teamsWorkbenchChrome + resource demand extract", () => {
  it("moves styles panes and tone helpers out of the workbench model", () => {
    expect(chromeSource).toContain("export const teamsWorkbenchStyles");
    expect(chromeSource).toContain("export const TEAMS_RAIL_PANE");
    expect(chromeSource).toContain("export function roleBadgeTone");
    expect(routeModelSource).toContain('teamsWorkbenchStyles as styles');
    expect(routeModelSource).not.toContain("...shellStyles");
  });

  it("moves workflow resource demand gates to a pure helper", () => {
    expect(demandSource).toContain("export function resolveTeamWorkflowResourceDemand");
    expect(routeModelSource).toContain("resolveTeamWorkflowResourceDemand({");
    expect(routeModelSource).not.toContain("const teamWorkflowCandidateListEnabled = Boolean(");
  });
});
