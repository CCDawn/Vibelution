import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const sourceRoot = resolve(import.meta.dirname, "../..");

const migrationTargets = [
  {
    path: "app/AppShellUtilityMenu.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "components/layout/PaneCollapseHandle.tsx",
    expectedPrimitive: "VIconButton",
  },
  {
    path: "components/preview/FilePreview.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "components/preview/StructuredLogPreview.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "routes/SkillsRoute.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "routes/PromptTemplatesRoute.tsx",
    expectedPrimitive: "VButton",
  },
] as const;

const slottedListStyleTargets = [
  {
    path: "app/AppShell.module.css",
    outerSelector: ".utilityFileButton",
    contentSlot: '.utilityFileButton [data-slot="vui-button-content"]',
    labelSlot: '.utilityFileButton [data-slot="vui-button-label"]',
  },
  {
    path: "routes/SkillsRoute.module.css",
    outerSelector: ".skillButton,\n.skillButtonActive",
    contentSlot: '.skillButton [data-slot="vui-button-content"]',
    labelSlot: '.skillButton [data-slot="vui-button-label"]',
  },
  {
    path: "routes/PromptTemplatesRoute.module.css",
    outerSelector: ".templateButton,\n.templateButtonActive",
    contentSlot: '.templateButton [data-slot="vui-button-content"]',
    labelSlot: '.templateButton [data-slot="vui-button-label"]',
  },
] as const;

const routeShellTargets = [
  {
    path: "routes/LauncherRoute.tsx",
    expected: ["VRouteHeader"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/MemoryRoute.tsx",
    expected: ["VRouteHeader"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/ResearchFlowCanvasRoute.tsx",
    expected: ["VRouteHeader"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/ResearchRoute.tsx",
    expected: ["VRouteHeader"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/GitRoute.tsx",
    expected: ["VRouteHeader", "VIconButton"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/KernelTaskCenterRoute.tsx",
    expected: ["VRouteHeader", "VSelect", "VIconButton"],
    forbidden: ["<header className={styles.header}", "<select value={status}"],
  },
  {
    path: "routes/LogsRoute.tsx",
    expected: ["VRouteHeader", "VStatusStrip"],
    forbidden: ["<header className={styles.header}", "<span className={styles.metaPill}>{t(\"readonlyPreview\")}</span>"],
  },
  {
    path: "routes/PromptTemplatesRoute.tsx",
    expected: ["VRouteHeader", "VIconButton"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/ResetRoute.tsx",
    expected: ["VRouteHeader"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/SkillsRoute.tsx",
    expected: ["VRouteHeader", "VIconButton"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/ToolsRoute.tsx",
    expected: ["VRouteHeader", "VIconButton"],
    forbidden: ["<header className={styles.header}"],
  },
] as const;

const routeStyleTargets = [
  {
    path: "routes/LauncherRoute.module.css",
    forbidden: [
      "--surface-page: var(--fg-primary)",
      "--surface-header: color-mix(in srgb, var(--fg-primary)",
    ],
  },
] as const;

function readTargetSource(path: string): string {
  return readFileSync(resolve(sourceRoot, path), "utf8");
}

function readStyleBlock(source: string, selector: string): string {
  const start = source.indexOf(selector);
  expect(start).toBeGreaterThanOrEqual(0);
  const end = source.indexOf("}", start);
  expect(end).toBeGreaterThan(start);
  return source.slice(start, end + 1);
}

describe("VUI batch migration", () => {
  it.each(migrationTargets)(
    "$path uses VUI controls instead of raw buttons",
    ({ path, expectedPrimitive }) => {
      const source = readTargetSource(path);

      expect(source).toContain(expectedPrimitive);
      expect(source).not.toContain("<button");
    },
  );

  it.each(slottedListStyleTargets)(
    "$path keeps VUI list button grid on internal slots",
    ({ path, outerSelector, contentSlot, labelSlot }) => {
      const source = readTargetSource(path);
      const outerBlock = readStyleBlock(source, outerSelector);

      expect(outerBlock).toContain("display: block;");
      expect(source).toContain(contentSlot);
      expect(source).toContain(labelSlot);
    },
  );

  it.each(routeShellTargets)(
    "$path uses VUI route shell controls",
    ({ path, expected, forbidden }) => {
      const source = readTargetSource(path);

      for (const primitive of expected) {
        expect(source).toContain(primitive);
      }
      for (const rawPattern of forbidden) {
        expect(source).not.toContain(rawPattern);
      }
    },
  );

  it.each(routeStyleTargets)(
    "$path keeps route surfaces on theme tokens",
    ({ path, forbidden }) => {
      const source = readTargetSource(path);

      for (const rawPattern of forbidden) {
        expect(source).not.toContain(rawPattern);
      }
    },
  );
});
