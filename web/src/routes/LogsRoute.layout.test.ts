import { describe, expect, it } from "vitest";

import routeSource from "./LogsRoute.tsx?raw";

describe("LogsRoute layout contract", () => {
  it("routes Logs page controls through VUI primitives", () => {
    expect(routeSource).toContain("from \"../components/vui\"");
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VIconButton");
    expect(routeSource).not.toMatch(/<button\b/);
  });

  it("keeps the raw file preview before the diagnostic summary in the main column", () => {
    const filePreviewIndex = routeSource.indexOf("<LazyFilePreview");
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

  it("uses dense structured states for log index and preview loading or empty states", () => {
    expect(routeSource).toContain("function renderLogIndexState");
    expect(routeSource).toContain("function renderLogPreviewState");
    expect(routeSource).toContain("styles.stateSkeletonStack");
    expect(routeSource).toContain("styles.previewStateFlow");
    expect(routeSource).not.toContain('<div className={styles.emptySurface}>{t("loadingLogs")}</div>');
  });

  it("keeps log root guidance in hover text instead of a permanent card row", () => {
    expect(routeSource).toContain("logsCompactSubtitle");
    expect(routeSource).toContain('title={t("logsSubtitle")}');
    expect(routeSource).toContain("title={root.summary.userGuide || root.path}");
    expect(routeSource).not.toContain("rootButtonGuide");
  });
});
