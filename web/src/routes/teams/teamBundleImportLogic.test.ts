import { describe, expect, it } from "vitest";

import {
  initialTeamBundleImportState,
  reportNeedsSchemaConfirm,
  teamBundleImportReducer,
} from "./teamBundleImportLogic";
import type { TeamBundleImportReport } from "../../api/types";

function report(overrides?: Partial<TeamBundleImportReport>): TeamBundleImportReport {
  return {
    schemaVersion: 1,
    bundleSchemaVersion: 1,
    status: "ready",
    dryRun: true,
    team: { name: "团队", action: "create" },
    agents: { create: ["搜索"], overwrite: [] },
    dependencies: { missingProviders: [], missingModels: [], pendingCredentials: [] },
    warnings: [],
    ...overrides,
  };
}

describe("teamBundleImportReducer", () => {
  it("walks idle → parsing → preview → importing → done", () => {
    let state = teamBundleImportReducer(initialTeamBundleImportState(), { type: "load_started" });
    expect(state.phase).toBe("parsing");

    state = teamBundleImportReducer(state, {
      type: "load_succeeded",
      bundle: { kind: "vibelution-team-bundle", schemaVersion: 1, team: { name: "团队", members: [] }, agents: [] },
      report: report(),
    });
    expect(state.phase).toBe("preview");
    expect(state.bundle?.team.name).toBe("团队");

    state = teamBundleImportReducer(state, { type: "confirm_started" });
    expect(state.phase).toBe("importing");

    state = teamBundleImportReducer(state, {
      type: "confirm_succeeded",
      report: report({ status: "completed", dryRun: false }),
    });
    expect(state.phase).toBe("done");
  });

  it("keeps the preview report on confirm failure and surfaces the message", () => {
    let state = teamBundleImportReducer(initialTeamBundleImportState(), {
      type: "load_succeeded",
      bundle: { kind: "vibelution-team-bundle", schemaVersion: 1, team: { name: "团队", members: [] }, agents: [] },
      report: report(),
    });
    state = teamBundleImportReducer(state, { type: "confirm_failed", message: "boom" });
    expect(state.phase).toBe("error");
    expect(state.errorMessage).toBe("boom");
    expect(state.report?.team.name).toBe("团队");
  });

  it("resets to a clean idle state", () => {
    const state = teamBundleImportReducer(initialTeamBundleImportState(), { type: "load_failed", message: "x" });
    expect(teamBundleImportReducer(state, { type: "reset" })).toEqual(initialTeamBundleImportState());
  });

  it("flags pending reports as needing schema confirm", () => {
    expect(reportNeedsSchemaConfirm(report({ status: "pending" }))).toBe(true);
    expect(reportNeedsSchemaConfirm(report())).toBe(false);
    expect(reportNeedsSchemaConfirm(null)).toBe(false);
  });
});
