import { describe, expect, it } from "vitest";

import hookSource from "./useTeamBundleImportActions.ts?raw";
import logicSource from "./teamBundleImportLogic.ts?raw";
import dialogSource from "./TeamBundleImportDialog.tsx?raw";

describe("team bundle import orchestration contract", () => {
  it("keeps network orchestration in the hook, not the dialog", () => {
    expect(hookSource).toContain("importTeamBundle(");
    expect(hookSource).toContain("queryKeys.teams()");
    expect(dialogSource).not.toContain("importTeamBundle(");
    expect(dialogSource).not.toContain("fetchJson");
    expect(dialogSource).not.toContain("api/client");
  });

  it("reuses the shared reducer instead of inlining state transitions", () => {
    expect(hookSource).toContain("teamBundleImportReducer");
    expect(dialogSource).toContain("TeamBundleImportState");
  });

  it("keeps the reducer pure (no network imports)", () => {
    expect(logicSource).not.toContain("fetchJson");
    expect(logicSource).not.toContain("importTeamBundle");
  });
});
