import { describe, expect, it } from "vitest";

import apiSource from "./diagnostics.ts?raw";
import hookSource from "../routes/config/useConfigWorkspaceQueries.ts?raw";

describe("diagnostics catalog API", () => {
  it("owns health diagnostics transport", () => {
    expect(apiSource).toContain("export function fetchHealthDiagnostics");
    expect(apiSource).toContain('"/api/diagnostics/health"');
  });

  it("keeps config workspace queries free of diagnostics paths", () => {
    expect(hookSource).toContain("fetchHealthDiagnostics(");
    expect(hookSource).not.toContain("/api/diagnostics/");
  });
});
