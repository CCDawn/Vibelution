import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = resolve(import.meta.dirname, "../app");
const routeRoot = import.meta.dirname;

const MEMORY_STYLE_FILES = readdirSync(routeRoot)
  .filter((filename) => /^Memory.*\.styles\.ts$/.test(filename))
  .map((filename) => resolve(routeRoot, filename));

const WORKBENCH_BASE_STYLE_FILES = [
  resolve(appRoot, "AppShell.styles.ts"),
  resolve(appRoot, "AppShellStatusGuidePanel.styles.ts"),
  resolve(appRoot, "AppShellUtilityMenu.styles.ts"),
  resolve(routeRoot, "ChatCodingRoute.styles.ts"),
  resolve(routeRoot, "MemoryRoute.styles.ts"),
] as const;

const WORKBENCH_MAINLINE_STYLE_FILES = Array.from(
  new Set([...WORKBENCH_BASE_STYLE_FILES, ...MEMORY_STYLE_FILES]),
);

const SPECIAL_ROUTE_STYLE_FILES = [
  resolve(routeRoot, "ToolsRoute.styles.ts"),
  resolve(routeRoot, "LogsRoute.styles.ts"),
  resolve(routeRoot, "ResearchRoute.styles.ts"),
  resolve(routeRoot, "ResetRoute.styles.ts"),
  resolve(routeRoot, "KernelTaskCenterRoute.styles.ts"),
] as const;

const NON_HOT_ROUTE_HOVER_STYLE_FILES = [
  resolve(routeRoot, "ToolsRoute.styles.ts"),
  resolve(routeRoot, "RuntimeScenesPane.styles.ts"),
  resolve(routeRoot, "ResearchRoute.styles.ts"),
  resolve(routeRoot, "LogsRoute.styles.ts"),
  resolve(routeRoot, "ResearchFlowCanvasRoute.styles.ts"),
  resolve(routeRoot, "TeamsRoute.styles.ts"),
] as const;

const MEMORY_ROUTE_HOVER_STYLE_FILES = MEMORY_STYLE_FILES;

const CHAT_ROUTE_HOVER_STYLE_FILES = [
  resolve(routeRoot, "AgentSessionTabStrip.styles.ts"),
  resolve(routeRoot, "ChatCodingRoute.styles.ts"),
  resolve(routeRoot, "chat/ChatFileWorkspaceTabs.styles.ts"),
  resolve(routeRoot, "DirectSessionIndexItem.styles.ts"),
  resolve(routeRoot, "SessionContextMenu.styles.ts"),
] as const;

const LEGACY_LOUD_HOVER_RECIPE =
  "hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)]";

const SHARED_QUIET_HOVER_TOKENS = [
  "hover:border-[var(--vui-control-hover-border)]",
  "hover:bg-[var(--vui-control-hover-bg)]",
  "hover:text-[var(--vui-control-hover-fg)]",
] as const;

const HEADER_CHROME_KEYS = [
  "activeWorkDetailHeader",
  "cacheDetailHeader",
  "cacheDetailSegmentHeader",
  "detailHeader",
  "detailMeta",
  "panelEyebrow",
  "panelHeader",
  "ragPreviewHeader",
  "statusGuideCardHeader",
  "utilityPanelHeader",
] as const;

const SPECIAL_ROUTE_LAYOUT_ONLY_KEYS = [
  "detailActions",
  "detailHeader",
  "packageButton",
  "packageKeyEntryButton",
  "packageSelectButton",
  "panelEyebrow",
  "panelHeader",
  "panelLead",
  "sceneCardButton",
  "sceneCardHeader",
  "sceneCardHeaderRow",
  "sceneDetailTitle",
] as const;

const SPECIAL_ROUTE_ROW_KEYS = [
  "taskRowClass",
] as const;

const SPECIAL_ROUTE_GRID_KEYS = [
  "permissionSummaryCards",
  "permissionSummaryGrid",
  "summaryGrid",
  "workspaceScopePanel",
] as const;

const BUTTON_CHROME_KEYS = [
  "detailActionButton",
  "matrixCardButton",
] as const;

function readSource(file: string) {
  return readFileSync(file, "utf-8");
}

function extractStyleValue(source: string, key: string) {
  const pattern = new RegExp(`${key}:\\s*\\r?\\n?\\s*"([^"]*)"`);
  const objectValue = source.match(pattern)?.[1];
  if (objectValue !== undefined) {
    return objectValue;
  }

  const constPattern = new RegExp(`const\\s+${key}\\s*=\\s*"([^"]*)"`);
  return source.match(constPattern)?.[1] ?? "";
}

function collectValues(keys: readonly string[]) {
  return WORKBENCH_MAINLINE_STYLE_FILES.flatMap((file) => {
    const source = readSource(file);
    return keys
      .map((key) => ({ file, key, value: extractStyleValue(source, key) }))
      .filter((entry) => entry.value.length > 0);
  });
}

function collectValuesFromFiles(files: readonly string[], keys: readonly string[]) {
  return files.flatMap((file) => {
    const source = readSource(file);
    return keys
      .map((key) => ({ file, key, value: extractStyleValue(source, key) }))
      .filter((entry) => entry.value.length > 0);
  });
}

function formatViolation(entry: { file: string; key: string }) {
  return `${entry.file.split(/[/\\]/).pop()}:${entry.key}`;
}

function countOccurrences(source: string, token: string) {
  return source.split(token).length - 1;
}

describe("route aesthetic contract", () => {
  it("keeps header and eyebrow style keys layout-only instead of card-like", () => {
    const violations = collectValues(HEADER_CHROME_KEYS)
      .filter(
        (entry) =>
          entry.value.includes("bg-[var(--vui-surface-glass)]") ||
          entry.value.includes("shadow-[var(--vui-shadow-hairline)]") ||
          entry.value.includes("rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]"),
      )
      .map((entry) => `${entry.file.split(/[/\\\\]/).pop()}:${entry.key}`);

    expect(violations).toEqual([]);
  });

  it("keeps button style keys from also carrying panel chrome", () => {
    const violations = collectValues(BUTTON_CHROME_KEYS)
      .filter(
        (entry) =>
          entry.value.includes("bg-[var(--vui-surface-glass)]") ||
          entry.value.includes("shadow-[var(--vui-shadow-hairline)]") ||
          entry.value.includes("rounded-[var(--radius-panel)]"),
      )
      .map((entry) => `${entry.file.split(/[/\\\\]/).pop()}:${entry.key}`);

    expect(violations).toEqual([]);
  });

  it("keeps repeated active accent tone classes from becoming the design language", () => {
    const offenders = WORKBENCH_MAINLINE_STYLE_FILES.flatMap((file) => {
      const source = readSource(file);
      return [
        "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]",
        "bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)]",
        "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]",
        "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
      ]
        .filter((token) => countOccurrences(source, token) > 28)
        .map((token) => `${file.split(/[/\\\\]/).pop()}:${token}`);
    });

    expect(offenders).toEqual([]);
  });

  it("keeps Workbench routes from owning full-page opaque surface-page wrappers", () => {
    const offenders = Array.from(new Set([
      resolve(routeRoot, "ChatCodingRoute.styles.ts"),
      resolve(routeRoot, "MemoryRoute.styles.ts"),
      resolve(routeRoot, "ResearchFlowCanvasRoute.styles.ts"),
      resolve(routeRoot, "TeamsRoute.styles.ts"),
      ...MEMORY_STYLE_FILES,
    ]))
      .flatMap((file) => {
        const source = readSource(file);
        return ["route", "canvasShell", "graphCanvasShell", "cacheDonutShell", "cacheDetailDonutShell"]
          .map((key) => ({ file, key, value: extractStyleValue(source, key) }))
          .filter((entry) => entry.value.includes("bg-[var(--surface-page)]"))
          .map((entry) => `${entry.file.split(/[/\\\\]/).pop()}:${entry.key}`);
      });

    expect(offenders).toEqual([]);
  });

  it("keeps special operational routes background-aware at the route root", () => {
    const offenders = collectValuesFromFiles(SPECIAL_ROUTE_STYLE_FILES, ["route", "routeClass"])
      .filter((entry) => entry.value.includes("bg-[var(--surface-page)]"))
      .map(formatViolation);

    expect(offenders).toEqual([]);
  });

  it("keeps special route headers, leads, and scene controls layout-only", () => {
    const offenders = collectValuesFromFiles(SPECIAL_ROUTE_STYLE_FILES, SPECIAL_ROUTE_LAYOUT_ONLY_KEYS)
      .filter(
        (entry) =>
          entry.value.includes("bg-[var(--vui-surface-glass)]") ||
          entry.value.includes("shadow-[var(--vui-shadow-hairline)]") ||
          entry.value.includes("rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]"),
      )
      .map(formatViolation);

    expect(offenders).toEqual([]);
  });

  it("keeps special route grid wrappers from becoming extra cards", () => {
    const offenders = collectValuesFromFiles(SPECIAL_ROUTE_STYLE_FILES, SPECIAL_ROUTE_GRID_KEYS)
      .filter(
        (entry) =>
          entry.value.includes("bg-[var(--vui-surface-glass)]") ||
          entry.value.includes("shadow-[var(--vui-shadow-hairline)]") ||
          entry.value.includes("rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]"),
      )
      .map(formatViolation);

    expect(offenders).toEqual([]);
  });

  it("keeps special route row controls from becoming giant card-buttons", () => {
    const offenders = collectValuesFromFiles(SPECIAL_ROUTE_STYLE_FILES, SPECIAL_ROUTE_ROW_KEYS)
      .filter(
        (entry) =>
          entry.value.includes("!min-h-[112px]") ||
          entry.value.includes("bg-[var(--vui-surface-glass)]") ||
          entry.value.includes("shadow-[var(--vui-shadow-hairline)]"),
      )
      .map(formatViolation);

    expect(offenders).toEqual([]);
  });

  it("routes non-hot route hover states through shared quiet hover tokens", () => {
    const offenders = NON_HOT_ROUTE_HOVER_STYLE_FILES.flatMap((file) => {
      const source = readSource(file);
      const filename = file.split(/[/\\]/).pop();
      const violations = [];

      if (source.includes(LEGACY_LOUD_HOVER_RECIPE)) {
        violations.push(`${filename}:legacy-loud-hover`);
      }

      for (const token of SHARED_QUIET_HOVER_TOKENS) {
        if (!source.includes(token)) {
          violations.push(`${filename}:missing:${token}`);
        }
      }

      return violations;
    });

    expect(offenders).toEqual([]);
  });

  it("routes Memory hover states through shared quiet hover tokens", () => {
    const offenders = MEMORY_ROUTE_HOVER_STYLE_FILES.flatMap((file) => {
      const source = readSource(file);
      const filename = file.split(/[/\\]/).pop();
      const violations = [];

      if (!source.includes(LEGACY_LOUD_HOVER_RECIPE)) {
        return violations;
      }

      violations.push(`${filename}:legacy-loud-hover`);

      for (const token of SHARED_QUIET_HOVER_TOKENS) {
        if (!source.includes(token)) {
          violations.push(`${filename}:missing:${token}`);
        }
      }

      return violations;
    });

    expect(offenders).toEqual([]);
  });

  it("routes chat route hover states through shared quiet hover tokens", () => {
    const offenders = CHAT_ROUTE_HOVER_STYLE_FILES.flatMap((file) => {
      const source = readSource(file);
      const filename = file.split(/[/\\]/).pop();
      const violations = [];

      if (!source.includes(LEGACY_LOUD_HOVER_RECIPE)) {
        return violations;
      }

      violations.push(`${filename}:legacy-loud-hover`);

      for (const token of SHARED_QUIET_HOVER_TOKENS) {
        if (!source.includes(token)) {
          violations.push(`${filename}:missing:${token}`);
        }
      }

      return violations;
    });

    expect(offenders).toEqual([]);
  });
});
