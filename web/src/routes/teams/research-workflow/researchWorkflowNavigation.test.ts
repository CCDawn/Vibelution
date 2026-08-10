import { describe, expect, it } from "vitest";

import { CHALLENGE_CUP_NODE_IDS } from "../../../api/types/researchWorkflow";
import {
  researchWorkspaceStageRoute,
  teamWorkspaceRoute,
} from "../researchWorkspaceModel";
import { patchResearchProcessSearch } from "./researchProcessLocation";

describe("researchWorkflowNavigation", () => {
  it("emits teamId as the only team scope", () => {
    const href = teamWorkspaceRoute("research-team");
    expect(href).toContain("teamId=research-team");
    expect(href).not.toMatch(/[?&]team=/);
    expect(href).not.toContain("team_id=");
  });

  it("stage entry helpers target fixed nodes on the single workflow canvas", () => {
    expect(researchWorkspaceStageRoute("team-1", "knowledge_collection")).toContain(
      "node=source_finding",
    );
    expect(researchWorkspaceStageRoute("team-1", "experiment")).toContain(
      "node=hypothesis_design",
    );
    expect(researchWorkspaceStageRoute("team-1", "iteration")).toContain(
      "node=controlled_run",
    );
  });

  it("keeps every fixed workflow node addressable", () => {
    for (const node of CHALLENGE_CUP_NODE_IDS) {
      const params = patchResearchProcessSearch({
        current: new URLSearchParams(),
        teamId: "team-1",
        patch: { node },
      });
      expect(params.get("node")).toBe(node);
      expect(params.get("teamId")).toBe("team-1");
    }
  });

  it("fails instead of selecting a default team", () => {
    expect(() => teamWorkspaceRoute("")).toThrow("teamId 不能为空");
    expect(() => researchWorkspaceStageRoute("", "experiment")).toThrow("teamId 不能为空");
  });
});
