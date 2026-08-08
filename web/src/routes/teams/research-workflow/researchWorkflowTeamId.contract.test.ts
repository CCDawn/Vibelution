import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "../../../api/client";
import {
  createResearchWorkflowRun,
  fetchEffectiveAgentBindings,
  listResearchWorkflowRuns,
  putResearchWorkflowAgentBindings,
} from "../../../api/researchWorkflow";

vi.mock("../../../api/client", () => ({
  fetchJson: vi.fn(),
}));

const mockedFetchJson = vi.mocked(fetchJson);

describe("researchWorkflow teamId contract", () => {
  beforeEach(() => {
    mockedFetchJson.mockReset();
  });

  it("uses canonical teamId for every team-scoped read", async () => {
    mockedFetchJson.mockResolvedValue({ workflowId: "challenge-cup-research", runs: [] });
    await listResearchWorkflowRuns("challenge-cup-research", { teamId: "research-team" });
    expect(mockedFetchJson).toHaveBeenCalledWith(
      "/api/research/workflows/challenge-cup-research/runs?teamId=research-team",
    );

    mockedFetchJson.mockResolvedValue({
      workflowId: "challenge-cup-research",
      workflowVersionId: "v1",
      teamId: "research-team",
      bindings: [],
    });
    await fetchEffectiveAgentBindings("challenge-cup-research", { teamId: "research-team" });
    expect(mockedFetchJson).toHaveBeenLastCalledWith(
      "/api/research/workflows/challenge-cup-research/agent-bindings/effective?teamId=research-team",
    );
  });

  it("fails before issuing an unscoped or blank-team request", async () => {
    await expect(
      listResearchWorkflowRuns("challenge-cup-research", { teamId: "  " }),
    ).rejects.toThrow("teamId is required");
    await expect(
      fetchEffectiveAgentBindings("challenge-cup-research", { teamId: "" }),
    ).rejects.toThrow("teamId is required");
    await expect(createResearchWorkflowRun({ teamId: "\t" })).rejects.toThrow("teamId is required");
    await expect(
      putResearchWorkflowAgentBindings("challenge-cup-research", {
        teamId: " ",
        workflowDefaults: {},
      }),
    ).rejects.toThrow("teamId is required");
    expect(mockedFetchJson).not.toHaveBeenCalled();
  });
});
