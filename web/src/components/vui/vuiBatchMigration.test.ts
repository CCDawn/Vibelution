import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import appShellStyles from "../../app/AppShell.styles";
import teamStyles from "../../routes/TeamsRoute.styles";

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

const cssModuleFreeTargets = [
  "components/preview/FilePreview.tsx",
  "components/preview/StructuredLogPreview.tsx",
  "routes/GitRoute.tsx",
  "routes/GitDiffView.tsx",
  "routes/KernelTaskCenterRoute.tsx",
  "routes/LauncherRoute.tsx",
  "routes/PetRoute.tsx",
  "routes/PromptTemplatesRoute.tsx",
  "routes/ResetRoute.tsx",
  "routes/SkillsRoute.tsx",
  "routes/SelfEvolutionTrack.tsx",
  "routes/SupervisedReviewRoute.tsx",
  "routes/SupervisedWorktreeReviewPanel.tsx",
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
    path: "routes/LauncherRoute.styles.ts",
    forbidden: [
      "--surface-page: var(--fg-primary)",
      "--surface-header: color-mix(in srgb, var(--fg-primary)",
    ],
  },
  {
    path: "routes/ChatCodingRoute.styles.ts",
    forbidden: ["border-left: 3px"],
  },
  {
    path: "routes/EvolutionRoute.styles.ts",
    forbidden: ["border-left: 3px"],
  },
  {
    path: "routes/AgentsRoute.styles.ts",
    forbidden: ["background: color-mix(in srgb, var(--accent-cool) 90%, var(--fg-primary))"],
  },
  {
    path: "routes/TeamsRoute.styles.ts",
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

describe("VUI batch migration", () => {
  it.each(migrationTargets)(
    "$path uses VUI controls instead of raw buttons",
    ({ path, expectedPrimitive }) => {
      const source = readTargetSource(path);

      expect(source).toContain(expectedPrimitive);
      expect(source).not.toContain("<button");
    },
  );

  it.each(cssModuleFreeTargets)("%s no longer imports a local CSS module", (path) => {
    const source = readTargetSource(path);

    expect(source).not.toContain(".module.css");
  });

  it("app/AppShell.styles.ts keeps VUI list button grid on internal slots", () => {
    expect(appShellStyles.utilityFileButton).toContain("[&_[data-slot=vui-button-content]]:w-full");
    expect(appShellStyles.utilityFileButton).toContain("[&_[data-slot=vui-button-label]]:grid");
    expect(appShellStyles.utilityFileButton).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(appShellStyles.utilityFileButtonActive).toContain("[&_[data-slot=vui-button-label]]:grid");
  });

  it("routes/SkillsRoute.tsx keeps VUI list button grid on internal slots", () => {
    const source = readTargetSource("routes/SkillsRoute.styles.ts");

    expect(source).toContain("skillButtonBaseClass");
    expect(source).toContain("[&_[data-slot=vui-button-content]]:w-full");
    expect(source).toContain("[&_[data-slot=vui-button-label]]:grid");
  });

  it("routes/PromptTemplatesRoute.tsx keeps VUI list button grid on internal slots", () => {
    const source = readTargetSource("routes/PromptTemplatesRoute.styles.ts");

    expect(source).toContain("templateButtonBaseClass");
    expect(source).toContain("[&_[data-slot=vui-button-content]]:w-full");
    expect(source).toContain("[&_[data-slot=vui-button-label]]:grid");
  });

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
    const source = readTargetSource("routes/TeamsRoute.styles.ts");

    expect(source).toContain("researchStageActions");
    expect(source).toContain("sourceCollectionStagePrimaryAction");
    expect(source).toContain("sourceCollectionPanelActions");
    expect(teamStyles.researchStageActions).toContain("flex");
    expect(teamStyles.researchStageActions).toContain("flex-wrap");
    expect(teamStyles.researchStageActions).not.toContain("grid-template-columns");
    expect(teamStyles.sourceCollectionStagePrimaryAction).toContain("w-fit");
    expect(teamStyles.sourceCollectionStagePrimaryAction).not.toMatch(/(^|\s)w-full(\s|$)/);
    expect(teamStyles.sourceCollectionPanelActions).toContain("flex");
    expect(teamStyles.sourceCollectionPanelActions).toContain("flex-wrap");
  });
});
