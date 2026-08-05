import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const bundleSource = readFileSync(new URL("./useTeamsMutationBundle.ts", import.meta.url), "utf8");
const bindingsSource = readFileSync(new URL("./researchStageAgentBindings.ts", import.meta.url), "utf8");

describe("useTeamsMutationBundle R2-g contract", () => {
  it("wires shell, workflow-start, experiment-loop, and SC write mutations", () => {
    expect(bundleSource).toContain("export function useTeamsMutationBundle");
    expect(bundleSource).toContain("useTeamShellMutations({");
    expect(bundleSource).toContain("useTeamWorkflowStartMutations({");
    expect(bundleSource).toContain("useTeamExperimentLoopMutations({");
    expect(bundleSource).toContain("useTeamSourceCollectionMutations({");
    expect(bundleSource).toContain("function saveCanvas(");
  });

  it("is consumed by the workbench model without re-declaring mutation hooks", () => {
    expect(routeModelSource).toContain("useTeamsMutationBundle({");
    expect(routeModelSource).not.toContain("} = useTeamShellMutations({");
    expect(routeModelSource).not.toContain("} = useTeamWorkflowStartMutations({");
    expect(routeModelSource).not.toContain("} = useTeamExperimentLoopMutations({");
    expect(routeModelSource).not.toContain("} = useTeamSourceCollectionMutations({");
  });
});

describe("buildResearchStageAgentBindingsByStage extract", () => {
  it("owns pure binding table construction", () => {
    expect(bindingsSource).toContain("export function buildResearchStageAgentBindingsByStage");
    expect(routeModelSource).toContain("buildResearchStageAgentBindingsByStage({");
    expect(routeModelSource).not.toContain("const roleBindings = new Map<string, { agentId: string; label: string; source: \"canvas\"");
  });
});

describe("createTeamsResearchNavigation R2-h extract", () => {
  it("owns workspace/team/shell navigation helpers", () => {
    const navSource = readFileSync(new URL("./createTeamsResearchNavigation.ts", import.meta.url), "utf8");
    expect(navSource).toContain("export function createTeamsResearchNavigation");
    expect(navSource).toContain("function selectResearchWorkspaceView");
    expect(navSource).toContain("function selectTeamRecord");
    expect(navSource).toContain("function selectTeamShellMode");
    expect(routeModelSource).toContain("createTeamsResearchNavigation({");
    expect(routeModelSource).not.toContain("function selectResearchWorkspaceView(view: ResearchWorkspaceView)");
    expect(routeModelSource).not.toContain("function selectTeamRecord(team: Team)");
    expect(routeModelSource).not.toContain("function selectTeamShellMode(mode: TeamShellMode)");
  });
});

describe("R2-i/j launch + stage agent helpers + experiment pending flags", () => {
  it("owns research stage launch handlers with late-bound SC guards", () => {
    const launchSource = readFileSync(new URL("./createResearchStageLaunchHandlers.ts", import.meta.url), "utf8");
    expect(launchSource).toContain("export function createResearchStageLaunchHandlers");
    expect(launchSource).toContain("getSelectedTeamStartResearchStagePending");
    expect(launchSource).toContain("getResearchStageCanLaunch");
    expect(routeModelSource).toContain("createResearchStageLaunchHandlers({");
    expect(routeModelSource).not.toContain("async function launchResearchStage(");
  });

  it("owns SC stage agent helpers", () => {
    const helpersSource = readFileSync(new URL("./createSourceCollectionStageAgentHelpers.ts", import.meta.url), "utf8");
    expect(helpersSource).toContain("export function createSourceCollectionStageAgentHelpers");
    expect(helpersSource).toContain("openSourceCollectionStageAgentChat");
    expect(routeModelSource).toContain("createSourceCollectionStageAgentHelpers({");
  });

  it("owns experiment workspace pending flag pure helper", () => {
    const pendingSource = readFileSync(new URL("./buildExperimentWorkspacePendingFlags.ts", import.meta.url), "utf8");
    expect(pendingSource).toContain("export function buildExperimentWorkspacePendingFlags");
    expect(routeModelSource).toContain("buildExperimentWorkspacePendingFlags({");
    expect(routeModelSource).not.toContain("createExperimentPlanPending:\n      createExperimentPlanMutation.isPending");
  });
});
