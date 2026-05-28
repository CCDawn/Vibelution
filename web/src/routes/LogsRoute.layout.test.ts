import { describe, expect, it } from "vitest";

import routeSource from "./LogsRoute.tsx?raw";

describe("LogsRoute layout contract", () => {
  it("keeps the raw file preview before the diagnostic summary in the main column", () => {
    const filePreviewIndex = routeSource.indexOf("<FilePreview");
    const diagnosticsIndex = routeSource.indexOf("{renderDiagnosticsPanel(contentQuery.data.diagnostics, lang)}");

    expect(filePreviewIndex).toBeGreaterThan(0);
    expect(diagnosticsIndex).toBeGreaterThan(filePreviewIndex);
  });

  it("renders diagnostics as a collapsed details row instead of a large leading panel", () => {
    expect(routeSource).toContain("<details className={styles.diagnosticsPanel}>");
    expect(routeSource).toContain("<summary className={styles.diagnosticsSummaryRow}>");
  });

  it("passes runtime scene deep-link parameters into the runtime scene pane", () => {
    expect(routeSource).toContain("const runtimeSceneQuery = useMemo(() => new URLSearchParams(location.search), [location.search])");
    expect(routeSource).toContain('runtimeSceneQuery.get("scene") ?? ""');
    expect(routeSource).toContain('runtimeSceneQuery.get("path") ?? ""');
    expect(routeSource).toContain("initialSceneId={initialRuntimeSceneId}");
    expect(routeSource).toContain("initialPath={initialRuntimeScenePath}");
  });
});
