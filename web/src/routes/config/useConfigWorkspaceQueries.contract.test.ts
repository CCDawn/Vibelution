import { describe, expect, it } from "vitest";

import routeSource from "../ConfigRoute.tsx?raw";
import queriesSource from "./useConfigWorkspaceQueries.ts?raw";

describe("config workspace queries contract", () => {
  it("owns config workspace and health diagnostics reads", () => {
    expect(queriesSource).toContain("queryKeys.configWorkspace()");
    expect(queriesSource).toContain("queryKeys.diagnosticsHealth()");
    expect(queriesSource.match(/\buseQuery\(/g) ?? []).toHaveLength(2);
  });

  it("is wired from ConfigRoute without inline workspace useQuery", () => {
    expect(routeSource).toContain("useConfigWorkspaceQueries(");
    expect(routeSource).not.toContain("const workspaceQuery = useQuery({");
    expect(routeSource).not.toContain("const healthDiagnosticsQuery = useQuery({");
    expect(routeSource).toContain("workspaceQuery");
    expect(routeSource).toContain("healthDiagnosticsQuery");
  });
});
