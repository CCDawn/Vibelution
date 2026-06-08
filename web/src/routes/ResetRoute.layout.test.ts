import { describe, expect, it } from "vitest";

import routeSource from "./ResetRoute.tsx?raw";

describe("ResetRoute layout contract", () => {
  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("keeps reset inventory and guarded mutations on the reset API", () => {
    expect(routeSource).toContain("queryKeys.resetSummary()");
    expect(routeSource).toContain('fetchJson<ResetSummary>("/api/reset/summary")');
    expect(routeSource).toContain('fetchJson<ResetPreviewResponse>("/api/reset/preview"');
    expect(routeSource).toContain('fetchJson<ResetExecuteResponse>("/api/reset/execute"');
    expect(routeSource).toContain('method: "POST"');
  });
});
