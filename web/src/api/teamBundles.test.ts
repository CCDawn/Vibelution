import { describe, expect, it } from "vitest";

import apiSource from "./teamBundles.ts?raw";
import toolbarSource from "../routes/teams/TeamBundleToolbarActions.tsx?raw";
import logicSource from "../routes/teams/useTeamBundleImportActions.ts?raw";

describe("team bundle API", () => {
  it("owns team bundle transports and paths", () => {
    expect(apiSource).toContain("export function fetchTeamBundle");
    expect(apiSource).toContain("export function importTeamBundle");
    expect(apiSource).toContain("/api/team-bundles/import");
    expect(apiSource).toContain("/api/teams/${encodeURIComponent(teamId)}/bundle");
  });

  it("keeps route surfaces free of team-bundle JSON paths", () => {
    for (const source of [toolbarSource, logicSource]) {
      expect(source).not.toMatch(/['"`]\/api\/team-bundles/);
      expect(source).not.toMatch(/['"`]\/api\/teams\/.+\/bundle/);
    }
    expect(toolbarSource).toContain("fetchTeamBundle(");
    expect(logicSource).toContain("importTeamBundle(");
  });
});
