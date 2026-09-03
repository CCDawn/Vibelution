import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { basename, extname, join, relative } from "node:path";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../../", import.meta.url));
const packageJsonPath = fileURLToPath(new URL("../../../package.json", import.meta.url));
const heroUiImportToken = "@heroui/react";
const vuiRendererRelativeRoot = "components/vui/renderers/";
const vuiProductRelativeRoot = "components/vui/product/";
const routeSourceExtensions = new Set([".ts", ".tsx"]);
const routeVisualUtilityPattern =
  /className\s*=\s*(?:["'`][^"'`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^"'`]*["'`]|{`[^`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^`]*`})/;
const localVisualClassConstantPattern = /const\s+[A-Za-z0-9_]+Class\s*=/;
const localStylesObjectPattern = /const\s+styles\s*=/;
const parentRouteStyleImportPattern = /from\s+["']\.\/([A-Za-z0-9]+Route)\.styles["']/g;
const productSharedParentStyleConsumers = [
  "components/layout/PersistedHeightListShell.tsx",
  "components/conversation/ConversationFollowupQueueBar.tsx",
  "components/conversation/ConversationToolActivityPills.tsx",
  "routes/chat/CacheDetailDialog.tsx",
  "routes/chat/ChatConversationIndexRail.tsx",
  "routes/chat/chatRoutePresentation.tsx",
  "routes/chat/ChatStatusRail.tsx",
  "routes/chat/TokenCoreStatusPanel.tsx",
  "routes/chat/useChatWorkbenchLayout.ts",
  // Known Launcher surface subcomponent sharing the parent placement style
  // (the owning LauncherRoute passes className down) instead of owning one.
  "routes/LauncherRegistryDiagnosticsBanner.tsx",
  "routes/TeamAiSearchWorkspacePanel.tsx",
  "routes/TeamExperimentPlanningLedgerPanel.tsx",
  "routes/TeamKnowledgeCollectionCompletionFlowPanel.tsx",
  "routes/TeamResearchLoopPanel.tsx",
  "routes/TeamResearchStageAgentPanel.tsx",
  "routes/TeamResearchStageLauncherPanel.tsx",
  "routes/TeamSourceCollectionActiveStageWorkspacePanel.tsx",
  "routes/TeamSourceCollectionControlsWorkspacePanel.tsx",
  "routes/TeamSourceCollectionGraphWorkspacePanel.tsx",
  "routes/TeamSourceCollectionMemoryWorkspacePanel.tsx",
  "routes/TeamSourceCollectionScreeningWorkspacePanel.tsx",
  // Challenge-question detail surface subcomponents share the owning panel's
  // style module (ChallengeQuestionDetailPanel.styles) instead of owning one.
  "routes/teams/challenge-cup/ChallengeQuestionRegisterDialog.tsx",
  "routes/teams/challenge-cup/ChallengeQuestionStageZoneHeading.tsx",
  "routes/teams/challenge-cup/ChallengeQuestionRunResetDialog.tsx",
  "routes/teams/challenge-cup/ChallengeQuestionReviewForm.tsx",
  // Companions (virtual human life) surface: the route and its rail/portrait
  // subcomponents share the route-owned companions/CompanionChatRails style
  // modules instead of each owning one.
  "routes/CompanionsRoute.tsx",
  "routes/companions/CompanionLifeRail.tsx",
  "routes/companions/CompanionPersonRail.tsx",
  "routes/companions/CompanionPortrait.tsx",
  "routes/companions/CompanionPreferenceCard.tsx",
  "routes/teams/workflowTone.ts",
  "routes/TeamsRoute.tsx",
  // Companions surface subcomponents share the owning route's style modules
  // (companions.styles / CompanionChatRails.styles) instead of owning one.
  "routes/CompanionsRoute.tsx",
  "routes/companions/CompanionLifeRail.tsx",
  "routes/companions/CompanionPersonRail.tsx",
  "routes/companions/CompanionPortrait.tsx",
] as const;
const isolatedDesignReferenceArtifacts = new Set([
  "design/challenge-cup-platform-home-preview-tooltips.tsx",
]);
// VWorkflowCanvas is the sanctioned product facade for the React Flow canvas renderer;
// workflowLayoutTypes re-exports the layout graph types. They are the only product files
// allowed to touch the shadcn workflow renderer directly.
const vuiWorkflowCanvasFacadeFiles = new Set([
  "components/vui/product/workflow/VWorkflowCanvas.tsx",
  "components/vui/product/workflow/workflowLayoutTypes.ts",
]);
const designSystemSourceFiles = new Set([
  "design/vuiChromeRecipes.ts",
  "design/vuiSurfaceAlphaPolicy.ts",
  "design/vuiSurfaceRecipes.ts",
]);

/**
 * VUI migration ledger: files that still carry pre-VUI styling patterns
 * (inline Tailwind utilities, local class constants, local styles objects,
 * parent-route style imports, style-map usage without a local .styles.ts).
 *
 * These are KNOWN migration debt, tracked so the gates below stay green while
 * the migration queue is worked through. The lists are fixed: any NEW file
 * with these patterns still fails the gates (nothing is auto-exempted).
 * See designs/INDEX.md migration tracking for the queue.
 */
const legacyInlineTailwindFiles = new Set<string>([
  "design/research-overview-preview.tsx",
  "design/research-process-flow-preview.tsx",
  "design/vui-component-preview/catalog/AestheticCatalog.tsx",
  "design/vui-component-preview/catalog/FoundationCatalog.tsx",
  "design/vui-component-preview/catalog/InteractiveCatalog.tsx",
  "design/vui-component-preview/catalog/RecipeCatalog.tsx",
  "design/vui-component-preview/catalog/StructureCatalog.tsx",
  "design/vui-component-preview/VuiComponentPreviewApp.tsx",
  "design/vui-component-preview/VuiPreviewCard.tsx",
  "design/vui-component-preview/VuiPreviewHeader.tsx",
  "design/vui-component-preview/VuiPreviewSection.tsx",
  "routes/AgentEffectiveConfigurationPanel.tsx",
  "routes/shared/ProgressiveRegionSkeleton.tsx",
  "routes/TeamExperimentPlanningLedgerPanel.tsx",
  "routes/TeamResearchStageLauncherPanel.tsx",
  "routes/teams/renderTeamsShellFrame.tsx",
  "routes/teams/research-workflow/ResearchProcessWorkspace.tsx",
  "routes/teams/ResearchBoardKanban.tsx",
  "routes/teams/ResearchOverviewSurface.tsx",
  "routes/teams/ResearchPrimaryActionBar.tsx",
  "routes/teams/ResearchStageNav.tsx",
  "routes/teams/ResearchWorkflowErrorSurface.tsx",
  "routes/teams/TeamResearchBoardPrimarySurface.tsx",
  "routes/teams/TeamsCanvasComposer.tsx",
  "routes/teams/TeamShellModeSwitch.tsx",
  "routes/teams/TeamShellRail.tsx",
  "routes/teams/useTeamsWorkbenchShellPhase.tsx",
]);

const legacyLocalClassConstFiles = new Set<string>([
  "routes/TeamResearchStageLauncherPanel.tsx",
  "routes/teams/ResearchBoardKanban.tsx",
  "routes/teams/ResearchPrimaryActionBar.tsx",
]);

const legacyLocalStylesFiles = new Set<string>([
  "routes/teams/ExperimentStageComposer.tsx",
  "routes/teams/ResearchStageWorkbenchShell.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionActiveStageWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionControlsWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionGraphWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionMemoryWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionScreeningWorkspacePanel.tsx",
  "routes/teams/SourceCollectionComposer.tsx",
  "routes/teams/TeamCommunicationPanel.tsx",
  "routes/teams/TeamResearchWorkflowPanelHost.tsx",
]);

const legacyParentStyleImportFiles = new Set<string>([
  "routes/EvolutionDatasetCatalogPanel.tsx",
  "routes/EvolutionSupervisedCaseTracePanel.tsx",
  "routes/EvolutionSupervisedConversationEvidencePanel.tsx",
  "routes/EvolutionSupervisedLibraryView.tsx",
  "routes/EvolutionSupervisedLiveIoPanel.tsx",
  "routes/EvolutionSupervisedLiveSetupPanel.tsx",
  "routes/EvolutionSupervisedRunPlanPanel.tsx",
  "routes/EvolutionSupervisedRunsView.tsx",
  "routes/EvolutionSupervisedWorkflowMembersPanel.tsx",
]);

const legacyStyleMapFiles = new Set<string>([
  "design/research-overview-preview.tsx",
  "design/research-process-flow-preview.tsx",
  "design/vui-component-preview/catalog/AestheticCatalog.tsx",
  "design/vui-component-preview/catalog/AgentCatalog.tsx",
  "design/vui-component-preview/catalog/DataCatalog.tsx",
  "design/vui-component-preview/catalog/FormsCatalog.tsx",
  "design/vui-component-preview/catalog/FoundationCatalog.tsx",
  "design/vui-component-preview/catalog/InteractiveCatalog.tsx",
  "design/vui-component-preview/catalog/NativeFormsCatalog.tsx",
  "design/vui-component-preview/catalog/RecipeCatalog.tsx",
  "design/vui-component-preview/catalog/StructureCatalog.tsx",
  "design/vui-component-preview/catalog/TeamCatalog.tsx",
  "design/vui-component-preview/catalog/TeamSourceCatalog.tsx",
  "design/vui-component-preview/VuiComponentPreviewApp.tsx",
  "design/vui-component-preview/VuiPreviewCard.tsx",
  "design/vui-component-preview/VuiPreviewHeader.tsx",
  "design/vui-component-preview/VuiPreviewSection.tsx",
  "routes/AgentListStatePanel.tsx",
  "routes/AgentRenameDialog.tsx",
  "routes/chat/ChatCenterTabStrip.tsx",
  "routes/chat/ChatCodingRouteWorkbench.tsx",
  "routes/chat/ChatConversationIndexPanelContent.tsx",
  "routes/chat/ChatMessageChromeHeader.tsx",
  "routes/chat/ChatSessionWorkbenchShell.tsx",
  "routes/chat/ChatWorkbenchCenterColumn.tsx",
  "routes/chat/TurnStatusTailPanel.tsx",
  "routes/EvolutionDatasetCatalogPanel.tsx",
  "routes/EvolutionSupervisedCaseTracePanel.tsx",
  "routes/EvolutionSupervisedConversationEvidencePanel.tsx",
  "routes/EvolutionSupervisedLibraryView.tsx",
  "routes/EvolutionSupervisedLiveIoPanel.tsx",
  "routes/EvolutionSupervisedLiveSetupPanel.tsx",
  "routes/EvolutionSupervisedRunPlanPanel.tsx",
  "routes/EvolutionSupervisedRunsView.tsx",
  "routes/EvolutionSupervisedWorkflowMembersPanel.tsx",
  "routes/shared/ProgressiveRegionSkeleton.tsx",
  "routes/teams/challenge-cup/ChallengeQuestionAnalysisSection.tsx",
  "routes/teams/challenge-cup/ChallengeQuestionDetailPrimitives.tsx",
  "routes/teams/challenge-cup/ChallengeQuestionEvidenceSection.tsx",
  "routes/teams/challenge-cup/ChallengeQuestionPlanSection.tsx",
  "routes/teams/ExperimentStageComposer.tsx",
  "routes/teams/renderTeamsShellFrame.tsx",
  "routes/teams/renderTeamsWorkbenchBoardPage.tsx",
  "routes/teams/renderTeamsWorkbenchCanvasPage.tsx",
  "routes/teams/research-workflow/ResearchProcessWorkspace.tsx",
  "routes/teams/ResearchBoardKanban.tsx",
  "routes/teams/ResearchOverviewSurface.tsx",
  "routes/teams/ResearchPrimaryActionBar.tsx",
  "routes/teams/ResearchStageNav.tsx",
  "routes/teams/ResearchStageWorkbenchShell.tsx",
  "routes/teams/ResearchWorkflowErrorSurface.tsx",
  "routes/teams/source-collection/createSourceCollectionActionHandlers.ts",
  "routes/teams/source-collection/createSourceCollectionController.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionActiveStageWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionControlsWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionGraphWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionMemoryWorkspacePanel.tsx",
  "routes/teams/source-collection/ui/TeamSourceCollectionScreeningWorkspacePanel.tsx",
  "routes/teams/SourceCollectionComposer.tsx",
  "routes/teams/TeamCanvasReadOnlyInspector.tsx",
  "routes/teams/TeamCommunicationPanel.tsx",
  "routes/teams/TeamNodeBindingPanel.tsx",
  "routes/teams/TeamOrganizationCanvasSurface.tsx",
  "routes/teams/TeamResearchBoardPrimarySurface.tsx",
  "routes/teams/teamResearchPrimarySurfaceRenderers.tsx",
  "routes/teams/TeamResearchWorkflowPanelHost.tsx",
  "routes/teams/TeamsCanvasComposer.tsx",
  "routes/teams/TeamShellModeSwitch.tsx",
  "routes/teams/TeamShellRail.tsx",
  "routes/teams/TeamShellToolbar.tsx",
  "routes/teams/TeamsOverviewComposer.tsx",
  "routes/teams/TeamsShellGateSurface.tsx",
  "routes/teams/teamsShellSurfaceModel.ts",
  "routes/teams/teamsWorkspacePanelRenderers.tsx",
  "routes/teams/useTeamsWorkbenchModel.tsx",
  "routes/teams/useTeamsWorkbenchShellPhase.tsx",
]);

function walkFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  return entries.flatMap((entry) => {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      return walkFiles(fullPath);
    }
    return /\.(ts|tsx|css)$/.test(entry) ? [fullPath] : [];
  });
}

function readText(file: string): string {
  return readFileSync(file, "utf-8");
}

function relativeFromSourceRoot(file: string): string {
  return relative(sourceRoot, file).replace(/\\/g, "/");
}

describe("VUI architecture boundary", () => {
  it("keeps @heroui/react out of package.json and source imports", () => {
    const packageJson = readText(packageJsonPath);
    expect(packageJson).not.toContain(heroUiImportToken);

    const boundarySelf = relativeFromSourceRoot(fileURLToPath(import.meta.url)).replace(/\\/g, "/");
    const offenders = walkFiles(sourceRoot)
      .filter((file) => readText(file).includes(heroUiImportToken))
      .map(relativeFromSourceRoot)
      .filter((file) => file !== boundarySelf)
      // Tests may name the token to forbid it (e.g. `.not.toContain("@heroui/react")`).
      .filter((file) => !file.endsWith(".test.ts") && !file.endsWith(".test.tsx"));

    expect(offenders).toEqual([]);
  });

  it("documents the root provider as a VUI/shadcn boundary", () => {
    const providerSource = readText(join(sourceRoot, "components", "vui", "VuiProvider.tsx"));
    const mainSource = readText(join(sourceRoot, "main.tsx"));

    expect(providerSource).toContain("export function VuiProvider");
    expect(providerSource).toContain('data-vui-provider="shadcn"');
    expect(mainSource).toContain('from "./components/vui/VuiProvider"');
    expect(mainSource).toContain("vui-provider-theme.css");
    expect(mainSource).not.toContain("heroui-theme.css");
    expect(mainSource).not.toContain("renderers/heroui");
  });

  it("keeps VUI product components from importing renderer backends directly", () => {
    const offenders = walkFiles(join(sourceRoot, "components", "vui", "product"))
      .filter((file) => {
        const text = readText(file);
        return text.includes(heroUiImportToken) || /from\s+["'][^"']*renderers\/shadcn\//.test(text);
      })
      .map(relativeFromSourceRoot)
      .filter((file) => !file.startsWith(vuiRendererRelativeRoot))
      .filter((file) => file.startsWith(vuiProductRelativeRoot))
      .filter((file) => !vuiWorkflowCanvasFacadeFiles.has(file));

    expect(offenders).toEqual([]);
  });

  it("keeps routes from importing VUI renderers or shadcn backends directly", () => {
    const rendererImportPattern = /from\s+["'][^"']*components\/vui\/renderers\//;
    const offenders = walkFiles(join(sourceRoot, "routes"))
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !file.endsWith(".test.ts") && !file.endsWith(".test.tsx"))
      .filter((file) => rendererImportPattern.test(readText(join(sourceRoot, file))));

    expect(offenders).toEqual([]);
  });

  it("documents the VUI facade + shadcn renderer ownership model", () => {
    const readme = readText(join(sourceRoot, "components", "vui", "README.md"));
    expect(readme).toContain("stable product API");
    expect(readme).toContain("shadcn-style + Radix is the preferred implementation backend");
    // The README phrases the rule as "no new V* product element without a
    // designs/ section and real consumers"; assert its stable wording.
    expect(readme).toContain("No new `V*`");
    expect(readme).toContain("VButton");
    expect(readme).toContain("ShadcnButton");
    expect(readme).toContain("VListDetailPage");
  });

  it("keeps interactive form primitives on the shadcn renderer path", () => {
    const button = readText(join(sourceRoot, "components", "vui", "primitives", "VButton.tsx"));
    const input = readText(join(sourceRoot, "components", "vui", "forms", "VInput.tsx"));
    const select = readText(join(sourceRoot, "components", "vui", "forms", "VSelect.tsx"));
    const checkbox = readText(join(sourceRoot, "components", "vui", "forms", "VCheckbox.tsx"));
    const tooltip = readText(join(sourceRoot, "components", "vui", "primitives", "VTooltip.tsx"));
    const dialog = readText(join(sourceRoot, "components", "vui", "primitives", "VDialog.tsx"));

    expect(button).toContain("ShadcnButton");
    expect(input).toContain("ShadcnInput");
    expect(select).toContain("ShadcnSelect");
    expect(checkbox).toContain("ShadcnCheckbox");
    expect(tooltip).toContain("ShadcnTooltip");
    expect(dialog).toContain("ShadcnDialog");
    expect(dialog).toContain("export function VConfirmDialog");
  });

  it("keeps product source files from adding inline Tailwind visual utility strings", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !isolatedDesignReferenceArtifacts.has(file))
      .filter((file) => !legacyInlineTailwindFiles.has(file))
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !file.endsWith(".test.tsx"))
      .filter((file) => !file.endsWith(".test.ts"))
      .filter((file) => routeVisualUtilityPattern.test(readText(join(sourceRoot, file))))

    expect(offenders).toEqual([]);
  });

  it("keeps product source files from owning local visual class constants", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !designSystemSourceFiles.has(file))
      .filter((file) => !legacyLocalClassConstFiles.has(file))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => localVisualClassConstantPattern.test(readText(join(sourceRoot, file))));

    expect(offenders).toEqual([]);
  });

  it("keeps product source files from owning local styles objects", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const allowedSharedConsumers = new Set<string>(productSharedParentStyleConsumers);
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !designSystemSourceFiles.has(file))
      .filter((file) => !legacyLocalStylesFiles.has(file))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => !allowedSharedConsumers.has(file))
      .filter((file) => localStylesObjectPattern.test(readText(join(sourceRoot, file))));

    expect(offenders).toEqual([]);
  });

  it("keeps parent route style imports bounded to the migration allow-list", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const allowedSharedConsumers = new Set<string>(productSharedParentStyleConsumers);
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !isolatedDesignReferenceArtifacts.has(file))
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !designSystemSourceFiles.has(file))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => {
        const source = readText(join(sourceRoot, file));
        return [...source.matchAll(parentRouteStyleImportPattern)].some((match) => basename(file) !== `${match[1]}.tsx`);
      })
      .filter((file) => !legacyParentStyleImportFiles.has(file))
      .filter((file) => !allowedSharedConsumers.has(file));

    expect(offenders).toEqual([]);
  });

  it("keeps parent style-map sharing explicitly bounded to known surface subcomponents", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const allowedSharedConsumers = new Set<string>(productSharedParentStyleConsumers);
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !isolatedDesignReferenceArtifacts.has(file))
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !designSystemSourceFiles.has(file))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => {
        const source = readText(join(sourceRoot, file));
        return source.includes("className=") || source.includes("styles.");
      })
      .filter(
        (file) =>
          !existsSync(join(sourceRoot, file.replace(/\.tsx?$/, ".styles.ts"))) &&
          !existsSync(join(sourceRoot, file.replace(/\.tsx?$/, ".module.css"))),
      )
      .filter((file) => !legacyStyleMapFiles.has(file))
      .filter((file) => !allowedSharedConsumers.has(file));

    expect(offenders).toEqual([]);
  });
});
