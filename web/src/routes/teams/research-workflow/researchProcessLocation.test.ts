import { describe, expect, it } from "vitest";

import {
  parseResearchProcessLocation,
  patchResearchProcessSearch,
} from "./researchProcessLocation";

describe("research process location", () => {
  it("writes only canonical teamId and removes legacy team aliases", () => {
    const next = patchResearchProcessSearch({
      current: new URLSearchParams("team=legacy&team_id=legacy-2&panel=agents"),
      teamId: " team-1 ",
      patch: { runId: "run-1", node: "source_finding" },
    });
    expect(next.get("teamId")).toBe("team-1");
    expect(next.has("team")).toBe(false);
    expect(next.has("team_id")).toBe(false);
    expect(next.get("researchView")).toBe("workflow");
    expect(next.get("workflowId")).toBe("challenge-cup-research");
    expect(next.get("runId")).toBe("run-1");
  });

  it("fails visibly when teamId is missing", () => {
    expect(() =>
      patchResearchProcessSearch({
        current: new URLSearchParams(),
        teamId: "",
        patch: {},
      }),
    ).toThrow("teamId 不能为空");
  });

  it("accepts only current panels and never maps legacy stage panels", () => {
    expect(parseResearchProcessLocation(new URLSearchParams("panel=launch"))).toMatchObject({
      panel: "launch",
    });
    expect(parseResearchProcessLocation(new URLSearchParams("panel=iteration"))).toMatchObject({
      panel: "node",
    });
  });
});
