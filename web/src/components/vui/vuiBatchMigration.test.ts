import { readdirSync, readFileSync } from "node:fs";
import { relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import utilityMenuStyles from "../../app/AppShellUtilityMenu.styles";
import agentStyles from "../../routes/AgentsRoute.styles";
import evolutionStyles from "../../routes/EvolutionRoute.styles";
import evolutionRunRecordsStyles from "../../routes/EvolutionRunRecordsPanel.styles";
import petStyles from "../../routes/PetRoute.styles";
import teamSourceCollectionActiveStagePanelStyles from "../../routes/TeamSourceCollectionActiveStagePanel.styles";
import teamSourceCollectionScreeningPanelStyles from "../../routes/TeamSourceCollectionScreeningPanel.styles";
import teamStyles from "../../routes/TeamsRoute.styles";

const sourceRoot = resolve(import.meta.dirname, "../..");
const rawControlPattern = /<(button|input|select|textarea)\b/;
const configFileInputPattern = /<input\s+type="file"\s+accept="image\/png,image\/jpeg,image\/webp"\s+disabled=\{disabled \|\| imageUploading\}[\s\S]*?\/>/g;
const configFileInputContexts = [
  /styles\.themeBackgroundDropButton[\s\S]{0,1200}<input\s+type="file"/,
  /styles\.themeBackgroundImageActions[\s\S]{0,1200}<input\s+type="file"/,
  /styles\.avatarImageDropButton[\s\S]{0,1200}<input\s+type="file"/,
  /styles\.avatarImageActions[\s\S]{0,1200}<input\s+type="file"/,
] as const;

const rawControlAllowedFiles = new Set([
  "components/vui/forms/VNativeInput.tsx",
  "components/vui/forms/VNativeSelect.tsx",
  "components/vui/forms/VNativeTextarea.tsx",
  "components/vui/primitives/VNativeButton.tsx",
  // Path B Wave R: shadcn-style native controls are VUI renderers, not page controls.
  "components/vui/renderers/shadcn/ShadcnButton.tsx",
  "components/vui/renderers/shadcn/ShadcnInput.tsx",
  "components/vui/renderers/shadcn/ShadcnTextarea.tsx",
  "components/vui/renderers/shadcn/ShadcnSelect.tsx",
  "components/vui/renderers/shadcn/ShadcnCheckbox.tsx",
]);

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

const nativeControlTargets = [
  {
    path: "routes/AgentBulkOperationsPanel.tsx",
    expected: ["VNativeSelect"],
    forbidden: ["<button", "<input", "<select", "<textarea"],
  },
  {
    path: "routes/AgentDetailHeaderPanel.tsx",
    expected: ["VNativeButton"],
    forbidden: ["<button", "<input", "<select", "<textarea"],
  },
  {
    path: "routes/AgentCoreConfigPanel.tsx",
    expected: ["VNativeInput", "VNativeSelect"],
    forbidden: ["<button", "<input", "<select", "<textarea"],
  },
  {
    path: "routes/EvolutionRoute.tsx",
    expected: ["VButton", "VInput", "VStringSelect", "VTextarea"],
    forbidden: ["<button", "<input", "<select", "<textarea"],
  },
  {
    path: "routes/ConfigRoute.tsx",
    expected: ["VButton", "VInput", "VStringSelect", "VTextarea"],
    forbidden: ["<button", "<select", "<textarea"],
  },
  {
    path: "components/vui/product/agent-management/AgentDenseList.tsx",
    expected: ["VNativeButton", "VNativeInput"],
    forbidden: ["<button", "<input"],
  },
  {
    path: "components/vui/product/agent-management/AgentFilterRail.tsx",
    expected: ["VNativeButton", "VNativeInput"],
    forbidden: ["<button", "<input"],
  },
] as const;

const cssModuleFreeTargets = [
  "components/preview/FilePreview.tsx",
  "components/preview/StructuredLogPreview.tsx",
  "routes/AgentsRoute.tsx",
  "routes/ConfigRoute.tsx",
  "routes/EvolutionRoute.tsx",
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
    expected: ["VDenseOpsPage", "VIconButton"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/KernelTaskCenterRoute.tsx",
    expected: ["VListDetailPage", "VSelect", "VIconButton"],
    forbidden: ["<header className={styles.header}", "<select value={status}"],
  },
  {
    path: "routes/LogsRoute.tsx",
    expected: ["VDenseOpsPage", "VStatusStrip"],
    forbidden: ["<header className={styles.header}", "<span className={styles.metaPill}>{t(\"readonlyPreview\")}</span>"],
  },
  {
    path: "routes/PromptTemplatesRoute.tsx",
    expected: ["VListDetailPage", "VIconButton"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/ResetRoute.tsx",
    expected: ["VDenseOpsPage"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/SkillsRoute.tsx",
    expected: ["VListDetailPage", "VIconButton"],
    forbidden: ["<header className={styles.header}"],
  },
  {
    path: "routes/ToolsRoute.tsx",
    expected: ["VDenseOpsPage", "VIconButton"],
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

const staticInlineStyleCleanupTargets = [
  {
    path: "components/editor/LazyJsonCodeMirror.tsx",
    forbidden: 'style={{ minHeight: "100%" }}',
  },
  {
    path: "components/vui/VuiProvider.tsx",
    forbidden: 'style={{ display: "contents" }}',
  },
] as const;

function readTargetSource(path: string): string {
  return readFileSync(resolve(sourceRoot, path), "utf8");
}

function toSourceRelativePath(path: string): string {
  return relative(sourceRoot, path).replaceAll("\\", "/");
}

function listSourceTsxFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = resolve(root, entry.name);
    if (entry.isDirectory()) {
      return listSourceTsxFiles(fullPath);
    }
    return entry.isFile() && entry.name.endsWith(".tsx") ? [toSourceRelativePath(fullPath)] : [];
  });
}

function isRawControlGuardExempt(path: string): boolean {
  return rawControlAllowedFiles.has(path) || /\.test\.tsx$/.test(path) || /\.spec\.tsx$/.test(path);
}

function sourceHasRawControlOutsideAllowedExceptions(path: string, source: string): boolean {
  if (path === "routes/ConfigRoute.tsx") {
    const allowedFileInputs = source.match(configFileInputPattern) ?? [];
    const hasExpectedFileInputExceptions = allowedFileInputs.length === configFileInputContexts.length
      && allowedFileInputs.every((input) => input.includes("onChange={async"))
      && configFileInputContexts.every((context) => context.test(source));
    if (!hasExpectedFileInputExceptions) {
      return true;
    }
    return rawControlPattern.test(source.replaceAll(configFileInputPattern, ""));
  }
  return rawControlPattern.test(source);
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

  it.each(nativeControlTargets)(
    "$path uses VUI native controls instead of raw form/action elements",
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

  it("keeps business TSX sources raw-control free outside VUI primitives and tests", () => {
    const violations = listSourceTsxFiles(sourceRoot)
      .filter((path) => !isRawControlGuardExempt(path))
      .filter((path) => sourceHasRawControlOutsideAllowedExceptions(path, readTargetSource(path)));

    expect(violations).toEqual([]);
  });

  it("permits only the four styled image-upload inputs in Config", () => {
    const configSource = readTargetSource("routes/ConfigRoute.tsx");
    const configStyles = readTargetSource("routes/ConfigRoute.styles.ts");
    const currentFileInputs = configSource.match(configFileInputPattern) ?? [];

    expect(currentFileInputs).toHaveLength(4);
    expect(currentFileInputs.every((input) => input.includes("onChange={async"))).toBe(true);
    for (const context of configFileInputContexts) {
      expect(configSource).toMatch(context);
    }
    expect(configStyles).toContain("themeBackgroundDropButton");
    expect(configStyles).toContain("avatarImageDropButton");
    expect(configStyles).toContain("fileUploadButton");
    expect((configStyles.match(/\[&_input\]:\[opacity:0\]/g) ?? []).length).toBeGreaterThanOrEqual(3);
    expect(sourceHasRawControlOutsideAllowedExceptions("routes/ConfigRoute.tsx", configSource)).toBe(false);
    expect(sourceHasRawControlOutsideAllowedExceptions("routes/ConfigRoute.tsx", `${configSource}\n${currentFileInputs[0]}`)).toBe(true);
  });

  it("Evolution route and run-record panels preserve block button geometry after VUI native migration", () => {
    for (const className of [
      evolutionStyles.caseTraceSummary,
      evolutionStyles.workflowStepButton,
      evolutionRunRecordsStyles.runCardButton,
      evolutionStyles.proposalCardButton,
    ]) {
      expect(className).toContain("w-full");
    }
    expect(evolutionStyles.compactIconAction).toContain("w-9");
  });

  it("agent-management product controls preserve invisible checkboxes and embedded search geometry", () => {
    const denseListSource = readTargetSource("components/vui/product/agent-management/AgentDenseList.tsx");
    const filterRailSource = readTargetSource("components/vui/product/agent-management/AgentFilterRail.tsx");

    expect(denseListSource).toContain("!w-px");
    expect(denseListSource).toContain("!h-px");
    expect(filterRailSource).toContain("!border-0");
    expect(filterRailSource).toContain("!bg-transparent");
  });

  it("routes/AgentsRoute.styles.ts preserves block and fixed-size button geometry after VUI native migration", () => {
    for (const className of [
      agentStyles.avatarOption,
      agentStyles.detailTab,
      agentStyles.detailTabActive,
      agentStyles.managementChecklistDone,
      agentStyles.managementChecklistMissing,
    ]) {
      expect(className).toContain("w-full");
    }
    expect(agentStyles.detailAvatarButton).toContain("w-[46px]");
    expect(agentStyles.iconButton).toContain("w-[26px]");
    expect(agentStyles.returnBannerButton).toContain("w-fit");
  });

  it.each(cssModuleFreeTargets)("%s no longer imports a local CSS module", (path) => {
    const source = readTargetSource(path);

    expect(source).not.toContain(".module.css");
  });

  it("app/AppShellUtilityMenu.styles.ts keeps VUI list button grid on internal slots", () => {
    expect(utilityMenuStyles.utilityFileButton).toContain("[&_[data-slot=vui-button-content]]:w-full");
    expect(utilityMenuStyles.utilityFileButton).toContain("[&_[data-slot=vui-button-label]]:grid");
    expect(utilityMenuStyles.utilityFileButton).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(utilityMenuStyles.utilityFileButtonActive).toContain("[&_[data-slot=vui-button-label]]:grid");
  });

  it("routes/SkillsRoute.tsx keeps multiline VUI list buttons on a natural-height root grid", () => {
    const source = readTargetSource("routes/SkillsRoute.styles.ts");

    expect(source).toContain("skillButtonBaseClass");
    expect(source).toContain("!h-auto");
    expect(source).toContain("!grid grid-cols-[10px_minmax(0,1fr)_auto]");
    expect(source).not.toContain("[&_[data-slot=vui-button-label]]:grid");
  });

  it("routes/PromptTemplatesRoute.tsx keeps multiline VUI list buttons on a natural-height root grid", () => {
    const source = readTargetSource("routes/PromptTemplatesRoute.styles.ts");

    expect(source).toContain("templateButtonBaseClass");
    expect(source).toContain("!h-auto");
    expect(source).toContain("!grid gap-[5px]");
    expect(source).not.toContain("[&_[data-slot=vui-button-label]]:grid");
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
    const activeStageSource = readTargetSource("routes/TeamSourceCollectionActiveStagePanel.styles.ts");
    const screeningSource = readTargetSource("routes/TeamSourceCollectionScreeningPanel.styles.ts");

    expect(source).toContain("researchStageActions");
    expect(source).not.toContain("sourceCollectionStagePrimaryAction");
    expect(source).not.toContain("sourceCollectionPanelActions");
    expect(activeStageSource).toContain("sourceCollectionStagePrimaryAction");
    expect(screeningSource).toContain("sourceCollectionPanelActions");
    expect(teamStyles.researchStageActions).toContain("flex");
    expect(teamStyles.researchStageActions).toContain("flex-wrap");
    expect(teamStyles.researchStageActions).not.toContain("grid-template-columns");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStagePrimaryAction).toContain("w-fit");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStagePrimaryAction).not.toMatch(/(^|\s)w-full(\s|$)/);
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionPanelActions).toContain("flex");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionPanelActions).toContain("flex-wrap");
  });

  it("keeps PetRoute progress width in Tailwind instead of raw inline width", () => {
    const source = readTargetSource("routes/PetRoute.tsx");

    expect(source).toContain("--pet-progress");
    expect(source).not.toContain("style={{ width: `${progress}%` }}");
    expect(petStyles.progressFillClass).toContain("w-[var(--pet-progress)]");
  });

  it.each(staticInlineStyleCleanupTargets)("$path keeps static layout styles out of raw inline style props", ({ path, forbidden }) => {
    const source = readTargetSource(path);

    expect(source).not.toContain(forbidden);
  });
});
