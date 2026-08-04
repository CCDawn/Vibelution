import { describe, expect, it } from "vitest";

import routeSource from "../ConfigRoute.tsx?raw";
import actionsSource from "./useConfigMigrationActions.ts?raw";

describe("useConfigMigrationActions contract", () => {
  it("owns migration preview/apply network paths", () => {
    expect(actionsSource).toContain("export function useConfigMigrationActions");
    expect(actionsSource).toContain("/api/config/migration/llm-v2/preview");
    expect(actionsSource).toContain("/api/config/migration/llm-v2/apply");
    expect(actionsSource).toContain("shouldResetMigrationPreview");
  });

  it("is wired from ConfigRoute", () => {
    expect(routeSource).toContain("useConfigMigrationActions(");
    expect(routeSource).toContain("handlePreviewMigration");
    expect(routeSource).toContain("handleApplyMigration");
    expect(routeSource).not.toContain('"/api/config/migration/llm-v2/preview"');
  });
});
