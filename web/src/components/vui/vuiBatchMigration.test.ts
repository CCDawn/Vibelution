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
  {
    path: "routes/ChatCodingRoute.module.css",
    forbidden: ["border-left: 3px"],
  },
  {
    path: "routes/EvolutionRoute.module.css",
    forbidden: ["border-left: 3px"],
  },
  {
    path: "routes/AgentsRoute.module.css",
    forbidden: ["background: color-mix(in srgb, var(--accent-cool) 90%, var(--fg-primary))"],
  },
  {
    path: "routes/TeamsRoute.module.css",
    forbidden: [
      "background: color-mix(in srgb, var(--fg-primary) 78%, transparent)",
      "border-left-width: 4px",
      "color-mix(in srgb, var(--surface-panel-strong) 96%, var(--fg-primary) 4%)",
      "color-mix(in srgb, var(--surface-card) 96%, var(--fg-primary) 4%)",
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

  it("keeps Teams source-collection stage actions compact by default", () => {
    const source = readTargetSource("routes/TeamsRoute.module.css");
    const routeBlock = readStyleBlock(source, ".route");
    const researchActionsBlock = readStyleBlock(source, ".researchStageActions");
    const researchActionButtonBlock = readStyleBlock(source, ".researchStageActions button,\n.researchStageActions a");
    const actionBlock = readStyleBlock(source, ".sourceCollectionStagePrimaryAction,\n.sourceCollectionStageSecondaryAction");
    const panelBlock = readStyleBlock(source, ".sourceCollectionPanelActions");

    expect(routeBlock).toContain("--fg-muted: var(--fg-tertiary);");
    expect(routeBlock).toContain("--accent-primary: var(--accent-cool);");
    expect(routeBlock).toContain("--accent-success: var(--state-success);");
    expect(routeBlock).toContain("--accent-danger: var(--state-error);");
    expect(researchActionsBlock).toContain("display: flex;");
    expect(researchActionsBlock).toContain("flex-wrap: wrap;");
    expect(researchActionsBlock).not.toContain("grid-template-columns");
    expect(researchActionButtonBlock).toContain("width: fit-content;");
    expect(researchActionButtonBlock).not.toMatch(/^\s*width:\s*100%;/m);
    expect(actionBlock).toContain("width: fit-content;");
    expect(actionBlock).not.toMatch(/^\s*width:\s*100%;/m);
    expect(panelBlock).toContain("display: flex;");
    expect(panelBlock).toContain("flex-wrap: wrap;");
  });
});
