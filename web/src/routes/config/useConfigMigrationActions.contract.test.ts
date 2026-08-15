import { describe, expect, it } from "vitest";

import configApiSource from "../../api/config.ts?raw";
import routeSource from "../ConfigRoute.tsx?raw";
import actionsSource from "./useConfigMigrationActions.ts?raw";

describe("useConfigMigrationActions contract", () => {
  it("owns migration preview/apply network paths", () => {
    expect(actionsSource).toContain("export function useConfigMigrationActions");
    expect(actionsSource).toContain("previewLlmV2Migration(");
    expect(actionsSource).toContain("applyLlmV2Migration(");
    expect(actionsSource).toContain("shouldResetMigrationPreview");
    expect(configApiSource).toContain("/api/config/migration/llm-v2/preview");
    expect(configApiSource).toContain("/api/config/migration/llm-v2/apply");
  });

  it("is wired from ConfigRoute", () => {
    expect(routeSource).toContain("useConfigMigrationActions(");
    expect(routeSource).toContain("handlePreviewMigration");
    expect(routeSource).toContain("handleApplyMigration");
    expect(routeSource).not.toContain('"/api/config/migration/llm-v2/preview"');
  });
});
