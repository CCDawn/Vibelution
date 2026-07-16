import { describe, expect, it } from "vitest";

import styles from "./LogsRoute.styles";
import routeSource from "./LogsRoute.tsx?raw";

const logSurfaceKeys = [
  "diagnosticsPanel",
  "diagnosticsSummaryRow",
  "packageDiagnosisPanel",
  "packageDiagnosisSummaryRow",
  "packageFilesPanel",
  "panelSearch",
  "previewActions",
  "previewPane",
  "previewStateCard",
  "previewStateFlow",
  "previewStateSurface",
  "sceneCard",
  "sceneCardMeta",
  "sceneCardStatus",
  "sceneDetailSurface",
  "sceneRawPreview",
  "startupTracePanel",
  "packageWorkRunPanel",
] as const satisfies readonly (keyof typeof styles)[];

function hasClassToken(className: string, token: string) {
  return className.split(/\s+/).includes(token);
}

describe("LogsRoute layout contract", () => {
  it("routes Logs page controls through VUI primitives", () => {
    expect(routeSource).toContain("from \"../components/vui\"");
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VIconButton");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });

  it("uses VUI surfaces without changing the resizable logs contract", () => {
    expect(routeSource).toContain("VSurface");
    expect(routeSource).toContain("VStateSurface");
    expect(routeSource).toContain("VActionGroup");
    expect(routeSource).toContain("LOG_SIDEBAR_STORAGE_KEY");
    expect(routeSource).toContain("LOG_RIGHT_RAIL_STORAGE_KEY");
    expect(styles.resizableLayout).toContain("grid-cols-[var(--logs-sidebar-width)_auto_minmax(0,1fr)]");
    expect(styles.packageButtonPath).toContain("truncate");
    expect(styles.rootButtonPath).toContain("truncate");
    expect(styles.deleteButton).toContain("w-fit");
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

  it("uses VUI state surfaces for log index and preview loading or empty states", () => {
    expect(routeSource).toContain("function renderLogIndexState");
    expect(routeSource).toContain("function renderLogPreviewState");
    expect(routeSource).toContain("<VStateSurface");
    expect(routeSource).toContain('skeletonLines={tone === "loading" ? 2 : false}');
    expect(styles.stateSurface).toContain("min-w-0");
  });

  it("keeps log root guidance in hover text instead of a permanent card row", () => {
    expect(routeSource).toContain("logsCompactSubtitle");
    expect(routeSource).toContain("VTooltip");
    expect(routeSource).toContain('content={t("logsSubtitle")}');
    expect(routeSource).toContain("tooltip={`${root.summary.userGuide || root.path} · ${root.path} · ${latestLabel}`}");
    expect(routeSource).not.toContain('title={root.summary.userGuide || root.path}');
    expect(routeSource).not.toContain("rootButtonGuide");
  });

  it("keeps the resizable logs workspace as a three-column grid", () => {
    expect(styles.workspace).toContain("grid-cols-[minmax(0,1fr)_10px_minmax(220px,var(--logs-right-rail-width,250px))]");
    expect(styles.workspace).toContain("grid-rows-[minmax(0,1fr)]");
    expect(styles.workspace).toContain("overflow-hidden");
  });

  it("prevents the logs route and workspace from forcing horizontal page overflow", () => {
    for (const className of [styles.route, styles.workspace, styles.resizableLayout, styles.previewPane]) {
      expect(className).toContain("min-w-0");
      expect(className).toContain("max-w-full");
      expect(className).toContain("overflow-x-hidden");
    }
  });

  it("lets the three-column logs workspace converge to one column on mobile widths", () => {
    expect(styles.workspace).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.workspace).toContain("max-[760px]:overflow-y-auto");
    expect(styles.workspace).toContain("max-[760px]:overflow-x-hidden");
    expect(styles.resizableLayout).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.resizableLayout).toContain("max-[760px]:overflow-y-auto");
    expect(styles.resizableLayout).toContain("max-[760px]:overflow-x-hidden");
    expect(styles.sidebar).toContain("max-[760px]:max-h-[34vh]");
    expect(styles.rightRail).toContain("max-[760px]:max-h-[34vh]");
    expect(styles.resizeHandle).toContain("max-[760px]:hidden");
    expect(styles.previewStateFlow).toContain("max-[560px]:grid-cols-[repeat(2,minmax(0,1fr))]");
    expect(styles.stateFactRow).toContain("max-[560px]:grid-cols-[minmax(0,1fr)]");
  });

  it("keeps preview diagnostics and runtime evidence surfaces background-aware", () => {
    for (const key of logSurfaceKeys) {
      expect(styles[key]).toContain("border-[color-mix(in_srgb");
      expect(styles[key]).toContain("bg-[color-mix(in_srgb");
      expect(styles[key]).not.toContain("bg-[var(--vui-surface-glass)]");
      expect(styles[key]).not.toContain("shadow-[var(--vui-shadow");
    }
  });

  it("avoids adding another card shell around the actual log preview stack", () => {
    expect(styles.previewPane).toContain("grid-rows-[minmax(0,1fr)]");
    expect(styles.logPreviewStack).toContain("grid-rows-[auto_minmax(0,1fr)_auto]");
    expect(styles.logPreviewStack).not.toContain("rounded-[var(--radius-panel)]");
    expect(styles.logPreviewStack).not.toContain("border border-[color-mix(in_srgb");
    expect(styles.logPreviewStack).not.toContain("bg-[color-mix(in_srgb");
  });

  it("keeps Logs lists internally scrollable with bounded heights", () => {
    for (const key of ["packageList", "packageFileList", "rootNav"] as const) {
      expect(styles[key]).toContain("overflow-auto");
    }

    expect(styles.sidebar).toContain("grid-rows-[auto_auto_minmax(0,1fr)]");
    expect(styles.rightRail).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.packageFilesPanel).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.packageFileList).toContain("max-h-[min(190px,24vh)]");
    expect(styles.rootNav).toContain("max-[760px]:max-h-[34vh]");
  });

  it("keeps short toolbar and picker controls content-sized unless the whole row is the target", () => {
    for (const key of [
      "clearButton",
      "copyButton",
      "deleteButton",
      "filterButton",
      "packageWorkRunPathButton",
      "rawFileButton",
      "sceneCardButton",
      "toolbarButton",
    ] as const satisfies readonly (keyof typeof styles)[]) {
      expect(styles[key]).toContain("w-fit");
      expect(hasClassToken(styles[key], "w-full")).toBe(false);
    }

    for (const key of ["packageButton", "packageFileButton", "rootButton"] as const) {
      expect(hasClassToken(styles[key], "w-full")).toBe(true);
      expect(styles[key]).toContain("text-left");
    }

    expect(styles.packageSelectButton).toContain("w-[var(--vui-control-height-sm)]");
    expect(styles.packageSelectButton).toContain("h-[var(--vui-control-height-sm)]");
  });

  it("keeps nested diagnostic and runtime evidence details from becoming extra panel cards", () => {
    for (const key of [
      "diagnosticsSummary",
      "diagnosticsSummaryText",
      "packageDiagnosisSummary",
      "packageDiagnosisSummaryText",
      "previewStateHeader",
      "sceneCardTop",
    ] as const satisfies readonly (keyof typeof styles)[]) {
      expect(styles[key]).not.toContain("rounded-[var(--radius-panel)]");
      expect(styles[key]).not.toContain("bg-[color-mix(in_srgb,var(--surface-card)");
    }
  });

  it("keeps list and evidence row targets compact and background-aware", () => {
    for (const key of [
      "packageButton",
      "packageFileRow",
      "rootButton",
      "sceneCardMeta",
      "sceneCardStatus",
      "sceneCardSummary",
    ] as const satisfies readonly (keyof typeof styles)[]) {
      expect(styles[key]).toContain("bg-[color-mix(in_srgb,var(--vui-surface-row)");
      expect(styles[key]).not.toContain("bg-[var(--vui-control-muted)]");
      expect(styles[key]).not.toContain("shadow-[var(--vui-shadow");
    }
  });

  it("allocates the remaining route height to the logs workspace", () => {
    expect(styles.route).toContain("h-full");
    expect(styles.route).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.route).toContain("overflow-hidden");
    expect(styles.workspace).toContain("h-full");
    expect(styles.workspace).toContain("min-h-0");
    expect(styles.workspace).toContain("grid-rows-[minmax(0,1fr)]");
    expect(styles.workspace).toContain("overflow-hidden");
    expect(styles.resizableLayout).toContain("h-full");
    expect(styles.resizableLayout).toContain("overflow-hidden");
  });
});
