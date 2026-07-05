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

const BUTTON_CHROME_KEYS = [
  "detailActionButton",
  "matrixCardButton",
] as const;

function readSource(file: string) {
  return readFileSync(file, "utf-8");
}

function extractStyleValue(source: string, key: string) {
  const pattern = new RegExp(`${key}:\\s*\\r?\\n?\\s*"([^"]*)"`);
  return source.match(pattern)?.[1] ?? "";
}

function collectValues(keys: readonly string[]) {
  return WORKBENCH_MAINLINE_STYLE_FILES.flatMap((file) => {
    const source = readSource(file);
    return keys
      .map((key) => ({ file, key, value: extractStyleValue(source, key) }))
      .filter((entry) => entry.value.length > 0);
  });
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
      ...MEMORY_STYLE_FILES,
    ]))
      .flatMap((file) => {
        const source = readSource(file);
        return ["route", "graphCanvasShell", "cacheDonutShell", "cacheDetailDonutShell"]
          .map((key) => ({ file, key, value: extractStyleValue(source, key) }))
          .filter((entry) => entry.value.includes("bg-[var(--surface-page)]"))
          .map((entry) => `${entry.file.split(/[/\\\\]/).pop()}:${entry.key}`);
      });

    expect(offenders).toEqual([]);
  });
});
