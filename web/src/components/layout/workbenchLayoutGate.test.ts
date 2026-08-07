import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const webSrc = resolve(import.meta.dirname, "../..");
const routesDir = resolve(webSrc, "routes");

/** Allowed legacy single-key names (migration only — do not add new ones). */
const ALLOWED_LEGACY_WIDTH_KEYS = new Set([
  "vibelution.logs.sidebar-width",
  "vibelution.logs.right-rail-width",
  "vibelution.logs.runtime-scenes-sidebar-width",
  "vibelution.tools.left-panel-width",
  "vibelution.git.change-panel-width",
  "vibelution.supervised-review.queue-width",
  "vibelution.evolution.runs-queue-width",
  "vibelution.evolution.library-list-width",
  "vibelution.evolution.live-launch-width",
  "vibelution.evolution.live-run-width",
  "vibelution.evolution.live-io-height",
  "vibelution.self.sidebar.width",
  "vibelution.agent-workspace.column-widths.v1",
]);

const LEGACY_KEY_RE = /["'](vibelution\.[a-z0-9._-]*(?:width|height)[a-z0-9._-]*)["']/gi;

function walkTsFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      walkTsFiles(full, out);
      continue;
    }
    if (/\.(tsx|ts)$/.test(name) && !name.endsWith(".test.ts") && !name.endsWith(".test.tsx")) {
      out.push(full);
    }
  }
  return out;
}

describe("workbench layout gate (Wave 5)", () => {
  it("forbids new ad-hoc width/height localStorage keys outside the migration allowlist", () => {
    const files = walkTsFiles(routesDir);
    const offenders: string[] = [];

    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      for (const match of text.matchAll(LEGACY_KEY_RE)) {
        const key = match[1];
        if (key === "vibelution.pane-layouts.v1" || key === "vibelution.pane-heights.v1") {
          continue;
        }
        if (ALLOWED_LEGACY_WIDTH_KEYS.has(key)) {
          continue;
        }
        // Shared shell store key is not a pane width key.
        if (key === "vibelution-shell-store") {
          continue;
        }
        offenders.push(`${relative(webSrc, file)}: ${key}`);
      }
    }

    expect(offenders, `New legacy keys found:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("keeps Chat workbench on shared axis resize session + registry layout id", () => {
    const chatLayout = readFileSync(resolve(webSrc, "routes/chat/useChatWorkbenchLayout.ts"), "utf-8");
    const chatRoute = readFileSync(resolve(webSrc, "routes/chat/ChatCodingRouteWorkbench.tsx"), "utf-8");
    const statusRail = readFileSync(resolve(webSrc, "routes/chat/ChatStatusRail.tsx"), "utf-8");
    const indexRail = readFileSync(resolve(webSrc, "routes/chat/ChatConversationIndexRail.tsx"), "utf-8");
    const sessionTabs = readFileSync(resolve(webSrc, "routes/AgentSessionTabStrip.styles.ts"), "utf-8");
    expect(chatLayout).toContain("attachAxisResizeSession");
    expect(chatLayout).toContain("CHAT_WORKBENCH_LAYOUT_ID");
    expect(chatLayout).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(chatLayout).toContain("setChatPanelWidths");
    expect(chatLayout).toContain("getResizeBounds");
    // Coupled dual-pane math stays Chat-owned (doc may mention the generic hook by name).
    expect(chatLayout).not.toMatch(/import\s*\{[^}]*usePersistedPaneResize/);
    expect(chatRoute).toContain("ChatSessionWorkbenchShell");
    expect(chatRoute).toContain("statusRail={");
    expect(chatRoute).toContain("conversationIndex={");
    const chatShell = readFileSync(resolve(webSrc, "routes/chat/ChatSessionWorkbenchShell.tsx"), "utf-8");
    expect(chatShell).toContain("VSessionWorkbenchPage");
    expect(chatShell).toContain('domainRecipe="chat-session-workbench"');
    expect(chatShell).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(chatShell).toContain('data-chat-geometry="dual-pane"');
    // Conversation center region may live on shell or workbench after R01 extract.
    expect(
      chatRoute.includes('data-vui-region="chat-conversation-center"')
      || chatShell.includes('data-vui-region="chat-conversation-center"')
      || chatShell.includes("PaneCollapseHandle")
      || chatRoute.includes("PaneCollapseHandle"),
    ).toBe(true);
    expect(statusRail).toContain('data-vui-region="chat-status-rail"');
    expect(indexRail).toContain('data-vui-region="chat-session-index"');
    // Soft cool active tab — not full ink slab fill.
    expect(sessionTabs).toContain("agentSessionTabActive");
    expect(sessionTabs).toContain("accent-cool");
    expect(sessionTabs).not.toContain("bg-[var(--accent)]");
    expect(sessionTabs).not.toContain("bg-[var(--accent-primary)]");
  });

  it("keeps Memory project-memory-queue on shared height resize handle (Wave 6D)", () => {
    const panel = readFileSync(resolve(webSrc, "routes/MemoryProjectMemoryQueuePanel.tsx"), "utf-8");
    expect(panel).toContain("usePersistedPaneHeight");
    expect(panel).toContain("PaneHeightResizeHandle");
    expect(panel).toContain("project-memory-queue");
    expect(panel).toContain("WORKBENCH_LAYOUT_IDS.memory");
  });

  it("keeps Memory sources/knowledge three-pane on VSplitWorkspace + registry layout id", () => {
    const memory = readFileSync(resolve(webSrc, "routes/MemoryRoute.tsx"), "utf-8");
    expect(memory).toContain("VSplitWorkspace");
    expect(memory).toContain("WORKBENCH_LAYOUT_IDS.memory");
    expect(memory).toContain("MEMORY_SPLIT_RESIZE");
    expect(memory).toContain('id: "left"');
    expect(memory).toContain('id: "right"');
    expect(memory).toContain('data-vui-region="memory-sources-workspace"');
    expect(memory).toContain('data-vui-region="memory-knowledge-workspace"');
    expect(memory).not.toMatch(/import\s*\{[^}]*usePersistedPaneResize/);
    expect(memory).not.toContain("PaneResizeHandle");
    expect(memory).not.toContain("--memory-left-width");
  });

  it("keeps Memory agent-memory three-pane on VSplitWorkspace under memory layout id", () => {
    const agent = readFileSync(resolve(webSrc, "routes/MemoryAgentMemoryPanel.tsx"), "utf-8");
    expect(agent).toContain("VSplitWorkspace");
    expect(agent).toContain("WORKBENCH_LAYOUT_IDS.memory");
    expect(agent).toContain("AGENT_MEMORY_SPLIT_RESIZE");
    expect(agent).toContain("agent-list");
    expect(agent).toContain("agent-detail");
    expect(agent).toContain('data-vui-region="memory-agent-workspace"');
    expect(agent).not.toMatch(/import\s*\{[^}]*usePersistedPaneResize/);
  });

  it("keeps Evolution multi-rail on registry layoutId (domain resize exception)", () => {
    const evolution = readFileSync(resolve(webSrc, "routes/EvolutionRoute.tsx"), "utf-8");
    expect(evolution).toContain("VTrackWorkbenchPage");
    expect(evolution).toContain("WORKBENCH_LAYOUT_IDS.evolution");
    expect(evolution).toContain("usePersistedPaneResize");
    expect(evolution).toContain('domainRecipe="evolution-multi-rail"');
    expect(evolution).toContain('data-vui-recipe="evolution-workbench"');
    expect(evolution).toContain("runs-queue");
    expect(evolution).toContain("library-list");
    expect(evolution).toContain("live-launch");
    expect(evolution).toContain("live-run");
    expect(evolution).toContain("EvolutionSupervisedConversationEvidencePanel");
  });

  it("documents collapse-capable workbenches keep usePersistedPaneResize (not forced VSplit)", () => {
    // VSplitWorkspace does not own collapse-to-zero rails; these stay on the shared hook intentionally.
    for (const sample of [
      { file: "routes/GitRoute.tsx", layoutId: "WORKBENCH_LAYOUT_IDS.git", collapse: "PaneCollapseHandle" },
      { file: "routes/ToolsRoute.tsx", layoutId: "WORKBENCH_LAYOUT_IDS.tools", collapse: "PaneCollapseHandle" },
      { file: "routes/LogsRoute.tsx", layoutId: "WORKBENCH_LAYOUT_IDS.logs", collapse: "PaneCollapseHandle" },
      { file: "routes/LauncherRoute.tsx", layoutId: "WORKBENCH_LAYOUT_IDS.launcher", collapse: "railResizeHandle" },
    ] as const) {
      const text = readFileSync(resolve(webSrc, sample.file), "utf-8");
      expect(text, sample.file).toContain(sample.layoutId);
      expect(text, sample.file).toContain("usePersistedPaneResize");
      expect(text, sample.file).toContain(sample.collapse);
    }
  });

  it("retires ResearchFlowCanvasRoute to redirect; researchFlow layout id remains registered", () => {
    const research = readFileSync(resolve(webSrc, "routes/ResearchFlowCanvasRoute.tsx"), "utf-8");
    const ids = readFileSync(resolve(webSrc, "components/layout/workbenchLayoutIds.ts"), "utf-8");
    const workspace = readFileSync(
      resolve(webSrc, "routes/teams/research-workflow/ResearchProcessWorkspace.tsx"),
      "utf-8",
    );
    expect(ids).toContain("researchFlow");
    expect(research).toContain("Navigate");
    expect(research).toContain("researchView=workflow");
    expect(workspace).toContain("VWorkflowCanvas");
    expect(workspace).toContain("VCanvasWorkbenchPage");
    expect(workspace).toContain("WORKBENCH_LAYOUT_IDS.researchFlow");
  });

  it("keeps Teams source-collection list shells on shared height API (Wave 6E)", () => {
    const heights = readFileSync(
      resolve(webSrc, "routes/teams/source-collection/ui/teamSourceCollectionListHeights.ts"),
      "utf-8",
    );
    const shell = readFileSync(resolve(webSrc, "components/layout/PersistedHeightListShell.tsx"), "utf-8");
    const candidates = readFileSync(
      resolve(webSrc, "routes/teams/source-collection/ui/TeamSourceCollectionCandidatePanel.tsx"),
      "utf-8",
    );
    const screening = readFileSync(
      resolve(webSrc, "routes/teams/source-collection/ui/TeamSourceCollectionScreeningPanel.tsx"),
      "utf-8",
    );
    const memory = readFileSync(
      resolve(webSrc, "routes/teams/source-collection/ui/TeamSourceCollectionMemoryPanel.tsx"),
      "utf-8",
    );
    const graph = readFileSync(
      resolve(webSrc, "routes/teams/source-collection/ui/TeamSourceCollectionGraphPanel.tsx"),
      "utf-8",
    );
    expect(heights).toContain("WORKBENCH_LAYOUT_IDS.teams");
    expect(heights).toContain("source-collection-candidates");
    expect(heights).toContain("source-collection-screening");
    expect(heights).toContain("source-collection-memory");
    expect(heights).toContain("source-collection-graph-nodes");
    expect(shell).toContain("usePersistedPaneHeight");
    expect(shell).toContain("PaneHeightResizeHandle");
    expect(candidates).toContain("PersistedHeightListShell");
    expect(screening).toContain("PersistedHeightListShell");
    expect(memory).toContain("PersistedHeightListShell");
    expect(graph).toContain("PersistedHeightListShell");
  });

  it("keeps Memory compact lists and Launcher cleanup strips on shared height API (Wave 6F)", () => {
    const memoryHeights = readFileSync(resolve(webSrc, "routes/memoryListHeights.ts"), "utf-8");
    const launcherHeights = readFileSync(resolve(webSrc, "routes/launcherListHeights.ts"), "utf-8");
    const itemList = readFileSync(resolve(webSrc, "routes/MemoryItemListPanel.tsx"), "utf-8");
    const diagnostics = readFileSync(resolve(webSrc, "routes/LauncherDiagnosticsPanel.tsx"), "utf-8");
    const developer = readFileSync(resolve(webSrc, "routes/LauncherDeveloperModePanel.tsx"), "utf-8");
    const maintenance = readFileSync(resolve(webSrc, "routes/LauncherProjectMaintenancePanel.tsx"), "utf-8");
    expect(memoryHeights).toContain("compact-memory-list");
    expect(launcherHeights).toContain("guardian-table");
    expect(launcherHeights).toContain("cleanup-console");
    expect(itemList).toContain("PersistedHeightListShell");
    expect(diagnostics).toContain("LAUNCHER_GUARDIAN_TABLE_HEIGHT_PANE");
    expect(developer).toContain("LAUNCHER_CLEANUP_CONSOLE_HEIGHT_PANE");
    expect(maintenance).toContain("LAUNCHER_CLEANUP_CONSOLE_HEIGHT_PANE");
  });

  it("keeps Chat group member picker and Launcher noise grids on shared height API (Wave 6G)", () => {
    const chatHeights = readFileSync(resolve(webSrc, "routes/chat/chatListHeights.ts"), "utf-8");
    const statusRail = readFileSync(resolve(webSrc, "routes/chat/ChatStatusRail.tsx"), "utf-8");
    const launcherHeights = readFileSync(resolve(webSrc, "routes/launcherListHeights.ts"), "utf-8");
    const developer = readFileSync(resolve(webSrc, "routes/LauncherDeveloperModePanel.tsx"), "utf-8");
    const maintenance = readFileSync(resolve(webSrc, "routes/LauncherProjectMaintenancePanel.tsx"), "utf-8");
    expect(chatHeights).toContain("group-member-picker");
    expect(chatHeights).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(statusRail).toContain("PersistedHeightListShell");
    expect(statusRail).toContain("CHAT_GROUP_MEMBER_PICKER_HEIGHT_PANE");
    expect(launcherHeights).toContain("noise-item-grid");
    expect(developer).toContain("LAUNCHER_NOISE_ITEM_GRID_HEIGHT_PANE");
    expect(maintenance).toContain("LAUNCHER_NOISE_ITEM_GRID_HEIGHT_PANE");
  });

  it("keeps Chat compact-details body on height API and dialogs on viewport clamp (Wave 6H)", () => {
    const chatHeights = readFileSync(resolve(webSrc, "routes/chat/chatListHeights.ts"), "utf-8");
    const statusRail = readFileSync(resolve(webSrc, "routes/chat/ChatStatusRail.tsx"), "utf-8");
    const chatStyles = readFileSync(resolve(webSrc, "routes/ChatCodingRoute.styles.ts"), "utf-8");
    const cacheDialog = readFileSync(resolve(webSrc, "routes/chat/CacheDetailDialog.tsx"), "utf-8");
    const wizardDialog = readFileSync(resolve(webSrc, "routes/agent-create/AgentCreateWizardDialog.tsx"), "utf-8");
    const wizardStyles = readFileSync(resolve(webSrc, "routes/agent-create/AgentCreateWizardDialog.styles.ts"), "utf-8");
    const policy = readFileSync(resolve(webSrc, "components/layout/dialogHeightPolicy.ts"), "utf-8");
    expect(chatHeights).toContain("compact-details");
    expect(statusRail).toContain("CHAT_COMPACT_DETAILS_HEIGHT_PANE");
    expect(statusRail).toContain("compactDetailsBody");
    expect(chatStyles).not.toMatch(/compactDetails:\s*`[^`]*max-h-\[220px\]/);
    expect(chatStyles).toContain("100dvh");
    expect(cacheDialog).not.toContain("usePersistedPaneHeight");
    expect(cacheDialog).not.toContain("PersistedHeightListShell");
    expect(wizardDialog).not.toContain("usePersistedPaneHeight");
    expect(wizardDialog).not.toContain("PersistedHeightListShell");
    expect(wizardStyles).toContain("100dvh");
    expect(wizardDialog).toContain("VDialog");
    expect(wizardDialog).not.toContain("createPortal(");
    expect(policy).toContain("viewport");
    expect(policy).toContain("usePersistedPaneHeight");
  });

  it("keeps Evolution CASE IO on shared height resize handle", () => {
    const evolution = readFileSync(resolve(webSrc, "routes/EvolutionRoute.tsx"), "utf-8");
    const liveIo = readFileSync(resolve(webSrc, "routes/EvolutionSupervisedLiveIoPanel.tsx"), "utf-8");
    expect(evolution).toContain("usePersistedPaneHeight");
    expect(liveIo).toContain("PaneHeightResizeHandle");
    expect(evolution).not.toContain("beginPaneHeightResize");
  });

  it("keeps Memory graph node list on shared height resize handle (Wave 6B)", () => {
    const graph = readFileSync(resolve(webSrc, "routes/MemoryGraphViewPanel.tsx"), "utf-8");
    expect(graph).toContain("usePersistedPaneHeight");
    expect(graph).toContain("PaneHeightResizeHandle");
    expect(graph).toContain("graph-node-list");
    expect(graph).toContain("WORKBENCH_LAYOUT_IDS.memory");
    expect(graph).not.toContain("beginPaneHeightResize");
  });

  it("keeps Logs package-files and Launcher diagnostics on shared height resize (Wave 6C)", () => {
    const logs = readFileSync(resolve(webSrc, "routes/LogsRoute.tsx"), "utf-8");
    const launcherDiag = readFileSync(resolve(webSrc, "routes/LauncherDiagnosticsPanel.tsx"), "utf-8");
    expect(logs).toContain("usePersistedPaneHeight");
    expect(logs).toContain("PaneHeightResizeHandle");
    expect(logs).toContain("package-files");
    expect(logs).toContain("WORKBENCH_LAYOUT_IDS.logs");
    expect(launcherDiag).toContain("usePersistedPaneHeight");
    expect(launcherDiag).toContain("PaneHeightResizeHandle");
    expect(launcherDiag).toContain("diagnostics-body");
    expect(launcherDiag).toContain("WORKBENCH_LAYOUT_IDS.launcher");
  });

  it("keeps Agents/Teams/Memory domain recipe markers (Wave 6B)", () => {
    const agents = readFileSync(resolve(webSrc, "routes/AgentsRoute.tsx"), "utf-8");
    const agentsWorkspace = readFileSync(resolve(webSrc, "routes/AgentWorkspaceLayoutPanel.tsx"), "utf-8");
    // TeamsRoute.tsx is thin re-export; recipe markers live in workbench/composers.
    const teamsEntry = readFileSync(resolve(webSrc, "routes/TeamsRoute.tsx"), "utf-8");
    const teamsWorkbench = readFileSync(resolve(webSrc, "routes/teams/useTeamsWorkbenchModel.tsx"), "utf-8");
    const teamsCanvasComposer = readFileSync(resolve(webSrc, "routes/teams/TeamsCanvasComposer.tsx"), "utf-8");
    const teamsCanvas = readFileSync(resolve(webSrc, "routes/teams/TeamOrganizationCanvasSurface.tsx"), "utf-8");
    const memory = readFileSync(resolve(webSrc, "routes/MemoryRoute.tsx"), "utf-8");
    expect(agents).toContain('data-vui-recipe="agents-management-workbench"');
    expect(agentsWorkspace).toContain('data-vui-region="agents-directory"');
    expect(teamsEntry).toMatch(/from\s+["']\.\/teams\/TeamsRouteWorkbench["']/);
    expect(
      teamsWorkbench.includes('data-vui-recipe="teams-organization-workbench"')
      || teamsWorkbench.includes('data-vui-domain-recipe="teams-organization-workbench"')
      || teamsCanvasComposer.includes('domainRecipe="teams-organization-workbench"')
      || teamsCanvasComposer.includes("domainRecipe={\"teams-organization-workbench\"}"),
    ).toBe(true);
    expect(
      teamsCanvas.includes('data-vui-region="teams-canvas"')
      || teamsCanvasComposer.includes('data-vui-region="teams-canvas"')
      || teamsWorkbench.includes('data-vui-region="teams-canvas"'),
    ).toBe(true);
    expect(
      memory.includes('data-vui-domain-recipe="memory-knowledge-workbench"')
      || memory.includes('data-vui-recipe="memory-knowledge-workbench"'),
    ).toBe(true);
  });

  it("keeps remaining workbench routes on domain recipe markers (Wave 7A)", () => {
    const samples: Array<{ file: string; recipe: string }> = [
      { file: "routes/LogsRoute.tsx", recipe: "logs-workbench" },
      { file: "routes/GitRoute.tsx", recipe: "git-workbench" },
      { file: "routes/ToolsRoute.tsx", recipe: "tools-workbench" },
      { file: "routes/EvolutionRoute.tsx", recipe: "evolution-workbench" },
      { file: "routes/LauncherRoute.tsx", recipe: "launcher-workbench" },
      { file: "routes/SupervisedReviewRoute.tsx", recipe: "supervised-review-workbench" },
      { file: "routes/SelfEvolutionTrack.tsx", recipe: "evolution-self-workbench" },
      { file: "routes/SkillsRoute.tsx", recipe: "skills-workbench" },
      { file: "routes/KernelTaskCenterRoute.tsx", recipe: "kernel-task-center-workbench" },
      { file: "routes/PromptTemplatesRoute.tsx", recipe: "prompt-templates-workbench" },
    ];
    for (const sample of samples) {
      const text = readFileSync(resolve(webSrc, sample.file), "utf-8");
      expect(
        text.includes(`data-vui-recipe="${sample.recipe}"`)
        || text.includes(`data-vui-domain-recipe="${sample.recipe}"`)
        || text.includes(`domainRecipe="${sample.recipe}"`),
        sample.file,
      ).toBe(true);
    }
  });

  it("keeps route resize class maps placement-only (Wave 6A)", () => {
    const samples: Array<{ file: string; key: string }> = [
      { file: "routes/GitRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/SupervisedReviewRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/SelfEvolutionTrack.styles.ts", key: "sidebarResizer" },
      { file: "routes/EvolutionRoute.styles.ts", key: "liveIoResizeHandle" },
      { file: "routes/LogsRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/ToolsRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/LauncherRoute.styles.ts", key: "railResizeHandle" },
      { file: "routes/MemoryGraphViewPanel.styles.ts", key: "graphNodeListResizeHandle" },
      { file: "routes/LogsRoute.styles.ts", key: "packageFilesResizeHandle" },
      { file: "routes/LauncherDiagnosticsPanel.styles.ts", key: "diagnosticsBodyResizeHandle" },
      { file: "routes/MemoryProjectMemoryQueuePanel.styles.ts", key: "projectMemoryQueueResizeHandle" },
      { file: "routes/teams/source-collection/ui/TeamSourceCollectionCandidatePanel.styles.ts", key: "sourceCollectionListResizeHandle" },
      { file: "routes/teams/source-collection/ui/TeamSourceCollectionScreeningPanel.styles.ts", key: "sourceCollectionListResizeHandle" },
      { file: "routes/teams/source-collection/ui/TeamSourceCollectionMemoryPanel.styles.ts", key: "sourceCollectionListResizeHandle" },
      { file: "routes/teams/source-collection/ui/TeamSourceCollectionGraphPanel.styles.ts", key: "sourceCollectionListResizeHandle" },
      { file: "routes/MemoryItemListPanel.styles.ts", key: "compactMemoryListResizeHandle" },
      { file: "routes/LauncherDiagnosticsPanel.styles.ts", key: "guardianTableResizeHandle" },
      { file: "routes/LauncherDeveloperModePanel.styles.ts", key: "cleanupConsoleResizeHandle" },
      { file: "routes/LauncherProjectMaintenancePanel.styles.ts", key: "cleanupConsoleResizeHandle" },
      { file: "routes/chat/ChatStatusRail.styles.ts", key: "groupMemberPickerResizeHandle" },
      { file: "routes/chat/ChatStatusRail.styles.ts", key: "compactDetailsResizeHandle" },
      { file: "routes/LauncherDeveloperModePanel.styles.ts", key: "noiseItemGridResizeHandle" },
      { file: "routes/LauncherProjectMaintenancePanel.styles.ts", key: "noiseItemGridResizeHandle" },
    ];

    for (const sample of samples) {
      const text = readFileSync(resolve(webSrc, sample.file), "utf-8");
      // Key assignment should not reintroduce private lit-rule / col-resize chrome.
      const keyBlock = text.match(new RegExp(`${sample.key}:\\s*(?:\`[^\`]*\`|"[^"]*"|'[^']*')`, "m"));
      expect(keyBlock, `${sample.file} ${sample.key}`).not.toBeNull();
      const value = keyBlock?.[0] ?? "";
      expect(value, `${sample.file} ${sample.key} must not own col-resize chrome`).not.toMatch(/cursor-col-resize/);
      expect(value, `${sample.file} ${sample.key} must not own row-resize chrome`).not.toMatch(/cursor-row-resize/);
      expect(value, `${sample.file} ${sample.key} must not paint private before: rule`).not.toMatch(/before:w-/);
    }

    const configStyles = readFileSync(resolve(webSrc, "routes/ConfigRoute.styles.ts"), "utf-8");
    expect(configStyles).not.toContain("sidebarResizeX");
    expect(configStyles).not.toContain("sidebarResizeY");
    expect(configStyles).not.toContain("sidebarResizeCorner");
  });
});
