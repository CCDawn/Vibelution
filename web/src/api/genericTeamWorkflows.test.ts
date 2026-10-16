import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TeamFlow, TeamFlowRun } from "./types/genericTeamWorkflow";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ fetchJson: transport }));
import { commandTeamFlowRun, listTeamFlowArtifacts, listTeamFlows, saveTeamFlow, startTeamFlowRun, teamFlowKeys } from "./genericTeamWorkflows";

const flow: TeamFlow = { id: "flow-1", name: "My flow", description: "", fields: [], steps: [], revision: 3, updatedAt: "" };

describe("team-scoped user workflow transport", () => {
  beforeEach(() => transport.mockReset());
  it("sends saved revisions and keeps workflow/run identities separate", async () => {
    await saveTeamFlow("team-a", flow);
    const [url, request] = transport.mock.calls[0];
    expect(url).toBe("/api/teams/team-a/workflows/flow-1");
    expect(JSON.parse(request.body)).toEqual({ flow, expectedRevision: 3 });
    await startTeamFlowRun("team-a", flow, { custom: "value" }, "stable-submit");
    expect(JSON.parse(transport.mock.calls[1][1].body)).toEqual({ values: { custom: "value" }, expectedRevision: 3, idempotencyKey: "stable-submit" });
  });
  it("uses exact run revision for commands and scopes artifact reads to the team", async () => {
    await commandTeamFlowRun("team-b", { id: "run-2", revision: 7 } as TeamFlowRun, "stop");
    expect(transport.mock.calls[0][0]).toBe("/api/teams/team-b/workflow-runs/run-2/commands");
    expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual({ action: "stop", expectedRevision: 7 });
    await listTeamFlowArtifacts("team-b", "run-2");
    expect(transport.mock.calls[1][0]).toBe("/api/teams/team-b/workflow-runs/run-2/artifacts");
    expect(teamFlowKeys.runs("team-a")).not.toEqual(teamFlowKeys.runs("team-b"));
  });
  it("rejects empty team scope before transport", () => {
    expect(() => listTeamFlows("")).toThrow("请先选择团队");
    expect(transport).not.toHaveBeenCalled();
  });
});
