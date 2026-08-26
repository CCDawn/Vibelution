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
      inspectorOpen: true,
    });
    expect(parseResearchProcessLocation(new URLSearchParams("panel=iteration"))).toMatchObject({
      panel: "node",
      inspectorOpen: true,
    });
  });

  it("opens node and team deep links unless the URL records an explicit close", () => {
    expect(parseResearchProcessLocation(new URLSearchParams("panel=node&node=source_finding")))
      .toMatchObject({ panel: "node", inspectorOpen: true });
    expect(parseResearchProcessLocation(new URLSearchParams("panel=team")))
      .toMatchObject({ panel: "team", inspectorOpen: true });
    expect(parseResearchProcessLocation(new URLSearchParams("panel=node&inspector=closed")))
      .toMatchObject({ panel: "node", inspectorOpen: false });
  });

  it("clears the close marker on explicit panel or node navigation", () => {
    const switchedPanel = patchResearchProcessSearch({
      current: new URLSearchParams("panel=node&inspector=closed"),
      teamId: "research-team",
      patch: { panel: "team" },
    });
    expect(switchedPanel.has("inspector")).toBe(false);

    const selectedNode = patchResearchProcessSearch({
      current: new URLSearchParams("panel=team&inspector=closed"),
      teamId: "research-team",
      patch: { node: "source_finding", panel: "node" },
    });
    expect(selectedNode.has("inspector")).toBe(false);
  });

  it("preserves the close marker when React Flow clears an empty selection", () => {
    const next = patchResearchProcessSearch({
      current: new URLSearchParams("panel=node&inspector=closed&node=source_finding"),
      teamId: "research-team",
      patch: { node: null, panel: "node" },
    });
    expect(next.get("inspector")).toBe("closed");
    expect(next.has("node")).toBe(false);
  });
});
