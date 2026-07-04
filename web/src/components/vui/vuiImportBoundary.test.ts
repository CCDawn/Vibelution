import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { extname, join, relative } from "node:path";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { fileURLToPath } from "node:url";
import * as heroUiReact from "@heroui/react";

const sourceRoot = fileURLToPath(new URL("../../", import.meta.url));
const boundaryTestRelativePath = "components/vui/vuiImportBoundary.test.ts";
const heroUiImportToken = "@heroui/react";
const vuiRendererRelativeRoot = "components/vui/renderers/";
const vuiProductRelativeRoot = "components/vui/product/";
const routeSourceExtensions = new Set([".ts", ".tsx"]);
const routeVisualUtilityPattern =
  /className\s*=\s*(?:["'`][^"'`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^"'`]*["'`]|{`[^`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^`]*`})/;
const localVisualClassConstantPattern = /const\s+[A-Za-z0-9_]+Class\s*=/;
const localStylesObjectPattern = /const\s+styles\s*=/;
const productSharedParentStyleConsumers = [
  "app/AppShellStatusGuidePanel.tsx",
  "app/AppShellUtilityMenu.tsx",
  "components/conversation/AgentContextSectionsView.tsx",
  "components/conversation/AgentMessageTurnView.tsx",
  "components/conversation/AgentResponseSectionView.tsx",
  "components/conversation/AgentUserContentSectionView.tsx",
  "components/conversation/conversationInlineMarkdown.tsx",
  "routes/AgentArchiveZonePanel.tsx",
  "routes/AgentAvatarEditorPanel.tsx",
  "routes/AgentBulkConfigPanel.tsx",
  "routes/AgentContextCompressionPanel.tsx",
  "routes/AgentCoreConfigPanel.tsx",
  "routes/AgentCreatePanel.tsx",
  "routes/AgentDebugResetPanel.tsx",
  "routes/AgentDetailHeaderPanel.tsx",
  "routes/AgentDetailWorkspacePanel.tsx",
  "routes/AgentEmptySelectionPanel.tsx",
  "routes/AgentHealthMaintenancePanel.tsx",
  "routes/AgentListStatePanel.tsx",
  "routes/AgentListWorkspacePanel.tsx",
  "routes/AgentManagementHeaderPanel.tsx",
  "routes/AgentMemoryPolicyPanel.tsx",
  "routes/AgentModeMembershipPanel.tsx",
  "routes/AgentPersonaProfilePanel.tsx",
  "routes/AgentTaskProfilePanel.tsx",
  "routes/AgentToolGovernancePanel.tsx",
  "routes/AgentActivityHistoryPanel.tsx",
  "routes/AgentManagementBriefPanel.tsx",
  "routes/AgentOverviewPanel.tsx",
  "routes/AgentReferencesPanel.tsx",
  "routes/AgentReturnBannerPanel.tsx",
  "routes/AgentRuntimeFocusPanel.tsx",
  "routes/AgentRuntimePolicyPanel.tsx",
  "routes/AgentToolSummaryPanel.tsx",
  "routes/AgentSessionTabStrip.tsx",
  "routes/ConfigLogHelperCenterPanel.tsx",
  "routes/ConfigWorkspacePlaceholderPanel.tsx",
  "routes/ConversationIndexSection.tsx",
  "routes/ConversationIndexTree.tsx",
  "routes/DirectSessionIndexItem.tsx",
  "routes/GroupSessionIndexItems.tsx",
  "routes/MemoryAgentMemoryPanel.tsx",
  "routes/MemoryCleanupPanel.tsx",
  "routes/MemoryDetailPanel.tsx",
  "routes/MemoryEffectivePanel.tsx",
  "routes/MemoryManagePanel.tsx",
  "routes/MemoryManagementEditor.tsx",
  "routes/MemoryMatrixPanel.tsx",
  "routes/MemoryGraphCanvas.tsx",
  "routes/MemoryGraphViewPanel.tsx",
  "routes/MemoryKnowledgeBaseSidebar.tsx",
  "routes/MemoryKnowledgeDetailPanel.tsx",
  "routes/MemoryKnowledgeGovernancePanel.tsx",
  "routes/MemoryKnowledgeModeTabs.tsx",
  "routes/MemoryKnowledgePermissionsPanel.tsx",
  "routes/MemoryKnowledgePipelinePanel.tsx",
  "routes/MemoryKnowledgeRagPanel.tsx",
  "routes/MemoryKnowledgeReviewPanel.tsx",
  "routes/MemoryKnowledgeSearchPanel.tsx",
  "routes/MemoryKnowledgeSourceGovernancePanel.tsx",
  "routes/MemoryKnowledgeStewardPanel.tsx",
  "routes/MemoryKnowledgeUsageContractPanel.tsx",
  "routes/MemoryItemListPanel.tsx",
  "routes/MemoryOverviewPanel.tsx",
  "routes/MemoryProjectMemoryQueuePanel.tsx",
  "routes/MemoryReviewQueuePanel.tsx",
  "routes/MemorySelectedConfigPanel.tsx",
  "routes/MemorySourceAndItemPanels.tsx",
  "routes/MemoryWarningStrip.tsx",
  "routes/TeamMemoryIndexPanel.tsx",
  "routes/TeamSourceCollectionActiveStagePanel.tsx",
  "routes/TeamSourceCollectionCandidatePanel.tsx",
  "routes/TeamSourceCollectionConversationPanel.tsx",
  "routes/TeamSourceCollectionControlsPanel.tsx",
  "routes/TeamSourceCollectionExtractionRecoveryPanel.tsx",
  "routes/TeamSourceCollectionFindingDetailsPanel.tsx",
  "routes/TeamSourceCollectionGraphPanel.tsx",
  "routes/TeamSourceCollectionManualWritebackPanel.tsx",
  "routes/TeamSourceCollectionMemoryPanel.tsx",
  "routes/TeamSourceCollectionRunSettingsPanel.tsx",
  "routes/TeamSourceCollectionScreeningPanel.tsx",
  "routes/TeamSourceCollectionStageAgentsPanel.tsx",
  "routes/TeamSourceCollectionRunSwitcherPanel.tsx",
  "routes/TeamSourceCollectionSourceDetailPanel.tsx",
  "routes/TeamSourceCollectionStandaloneStagePanel.tsx",
  "routes/TeamSourceCollectionStorageActionsPanel.tsx",
  "routes/RuntimeScenesPane.tsx",
  "routes/SessionContextMenu.tsx",
  "routes/TeamWorkflowGraphView.tsx",
  "routes/chat/CliAgentRunTerminalPanel.tsx",
] as const;

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
  it("documents the current HeroUI package root provider surface", () => {
    const providerSource = readText(join(sourceRoot, "components", "vui", "renderers", "heroui", "HeroProvider.tsx"));

    expect("HeroUIProvider" in heroUiReact).toBe(false);
    expect(providerSource).toContain('data-vui-provider="heroui"');
    expect(providerSource).toContain("HeroUI 3.2.1 does not expose a root provider");
  });

  it("keeps HeroUI imports inside the VUI renderer layer", () => {
    const offenders = walkFiles(sourceRoot)
      .filter((file) => readText(file).includes(heroUiImportToken))
      .map(relativeFromSourceRoot)
      .filter((file) => file !== boundaryTestRelativePath)
      .filter((file) => !file.startsWith("components/vui/"));

    expect(offenders).toEqual([]);
  });

  it("keeps VUI product components from importing HeroUI directly", () => {
    const offenders = walkFiles(join(sourceRoot, "components", "vui", "product"))
      .filter((file) => readText(file).includes(heroUiImportToken))
      .map(relativeFromSourceRoot)
      .filter((file) => !file.startsWith(vuiRendererRelativeRoot))
      .filter((file) => file.startsWith(vuiProductRelativeRoot));

    expect(offenders).toEqual([]);
  });

  it("keeps product source files from adding inline Tailwind visual utility strings", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
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
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => localStylesObjectPattern.test(readText(join(sourceRoot, file))));

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
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
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
      .filter((file) => !allowedSharedConsumers.has(file));

    expect(offenders).toEqual([]);
  });
});
