import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const previewRoot = dirname(fileURLToPath(import.meta.url));
const vuiRoot = resolve(previewRoot, "../../components/vui");
const indexPath = join(vuiRoot, "designs", "INDEX.md");

// These named design sections do not render as standalone previews: they either
// document composition inside their owning product surfaces, or they are
// product components bound to server queries (the research recovery panel and
// entry fetch team failure state; the message version switcher lives inside
// ConversationView row metaActions) whose meaningful state cannot be expressed
// as a static preview.
const previewExemptDesignSections = new Set([
  // ConfigRoute-owned composition depends on account queries, native browser
  // authorization and canonical draft/apply callbacks. Covered by panel/hook,
  // real route save tests, the approved isolated preview and native settings acceptance.
  "ChatGPTSubscriptionPanel",
  "ChallengeQuestionStageZones",
  "ResearchAnomalyInboxExtendCta",
  "ResearchWorkflowRecoveryPanel",
  "ResearchWorkflowRecoveryEntry",
  "ConversationMessageVersionSwitcher",
  // Chat rerun choice is mounted by the workbench and covered by its click tests.
  "ConversationRerunFileChoiceDialog",
  "AgentUserContentSectionView",
  // Route-owned compositions: source/run/session state is supplied by EvolutionRoute.
  // Covered by their interaction tests and the isolated supervised workspace preview.
  "SupervisedConversationWorkspace",
  "SelfEvolutionConversationWorkspace",
  "EvolutionSupervisedLiveSetupPanel",
  // Route-owned composition of existing VUI APIs; AgentPerceptionPane supplies
  // authorization, policy drafts and native Session facts. Covered by panel,
  // Agent-selection/draft interaction tests and the formal runtime preview.
  "AgentPerceptionPanel",
  // Route-owned composition of existing VUI APIs; native room timeline queries
  // and the selected team's current round supply its meaningful state. Covered
  // by TeamHomeSurface interaction tests and the isolated team/chat preview.
  "TeamHomeSurface",
  // Route-owned dialog: team task-board, workspace changes and file-content queries
  // supply its states. Covered by dialog interaction tests and the isolated chat preview.
  "ChatGroupArtifactDialog",
  // Route-owned composition: the authorized Session catalog and original route
  // actions supply its state. Covered by browse/return tests and the approved isolated workbench preview.
  "ChatSessionBrowser",
  // Route-owned composition of the existing ChatRightRail renderer, scoped
  // project/session tab models and server-backed task/Git/notification panels.
  // Covered by adapter/panel interaction tests and production-source desktop,
  // 390px and non-chat browser acceptance; it has no standalone VUI export.
  "ProjectUtilityRightRail",
  // Route-owned index compositions: the persisted list preferences, authorized
  // paged session/directory queries and original navigation callbacks supply
  // their states. Covered by toolbar/search/shortcut interaction tests, the
  // approved single-row preview and the isolated workbench browser acceptance.
  "ChatSessionIndexToolbar",
  "ChatSessionIndexSearch",
  // Launcher-owned composition requires role-scoped IPC and native Session
  // state; real query-refresh and recovery-model tests cover it. It is not a
  // standalone VUI export. Packaged GUI acceptance remains a separate check.
  "LauncherAssistantRoute",
  // Workspace route depends on the selected native assistant/session, project
  // queries and router search state; its panels and routing have interaction tests.
  "LauncherAssistantWorkspaceRoute",
  // Launcher-owned cards consume identity-bound IPC rather than static props.
  // Their read/interaction tests and isolated real-component fixture cover the
  // composition; packaged visual acceptance remains a separate check.
  "LauncherAssistantTaskCards",
  // Parts of that Launcher-owned composition, not standalone VUI exports.
  // Identity-scoped provider/cleanup callbacks and the real navigation anchor
  // supply their state. Task-card, overview and StrictMode/navigation tests
  // cover them; approved source preview and packaged UI acceptance cover pixels.
  "LauncherAssistantTaskSidebar",
  "LauncherAssistantTaskDetail",
  "LauncherTaskNavigationSlot",
  // Launcher-owned confirmation consumes identity-bound native cleanup plans
  // and one-use tokens; it is not a standalone VUI export. Card interaction
  // tests and the isolated real-component delete/cancel/bulk preview cover it.
  "LauncherTaskCleanupDialog",
  // Route composition uses the live Launcher browser bridge and native view;
  // interaction tests and the approved isolated preview cover its UI.
  "LauncherAssistantBrowserWorkspace",
  // Shell subscribes to native Launcher state, queries project/update status,
  // changes document settings and hosts router outlets. Navigation additionally
  // acts on the real desktop bridge and router location; shell/navigation tests
  // exercise these integrations without making a gallery action control a window.
  "LauncherShell",
  "LauncherNavigation",
  // Project selection opens the native project picker and depends on branch
  // queries; update state and its restart action are owned by Launcher IPC.
  "LauncherProjectRoute",
  "LauncherUpdatesRoute",
  // Launcher-owned route compositions, not standalone VUI exports. Native
  // version/update state, settings drafts, instance lifecycles and maintenance
  // plans are covered by their interaction tests and the isolated real-route
  // browser checks (including failed update retry and inventory read failures).
  "LauncherUpdateTopbar",
  "LauncherStartupSettingsPanel",
  "LauncherBranchInstancesPanel",
  "LauncherToolsRoute",
  "LauncherProcessMonitorPanel",
  "LauncherProjectMaintenancePanel",
  // Route-owned operator control: window choices and one-shot confirmations
  // require live consent state, not a static standalone VUI export. Covered
  // by its interaction/authorization tests and the approved isolated CUA preview.
  "PersonalAssistantComputerPanel",
  // Human-attention surface bound to the native desktop bridge: the notifier
  // renders null and is driven by overview polling plus
  // notifyHumanAttention/onHumanAttentionOpened. Covered by its trigger-chain,
  // dedup and open-callback navigation interaction tests.
  "HumanAttentionNotifier",
  // Route-owned composer composition: the plus menu's meaningful state comes
  // from workbench-injected attachment/reference/capability/budget props. It
  // has an approved isolated preview (design/chat-composer-plus-menu-preview)
  // plus menu and dialog interaction tests.
  "ChatComposerPlusMenu",
  // Route-owned server-bound dialog: the budget revision/values/pending state
  // comes from the session budget-parameters query and mutation. Covered by
  // its draft/validation/409 interaction tests and the isolated plus-menu preview.
  "ChatComposerBudgetPopover",
]);

function collectPreviewSources(directory: string): string {
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        return collectPreviewSources(path);
      }
      return entry.name.endsWith(".tsx") ? readFileSync(path, "utf8") : "";
    })
    .join("\n");
}

function implementedDesignComponents(): string[] {
  const currentDesigns = readFileSync(indexPath, "utf8").split("## 拟新增")[0];
  return currentDesigns
    .split(/\r?\n/)
    .filter((line) => line.startsWith("|"))
    .flatMap((line) =>
      Array.from(line.matchAll(/`([A-Z][A-Za-z0-9]+)`/g), (match) => match[1]),
    )
    .filter((name, index, names) => names.indexOf(name) === index);
}

describe("VUI component preview coverage", () => {
  it("renders every standalone implemented component registered in the design index", () => {
    const previewSources = collectPreviewSources(previewRoot);
    const missing = implementedDesignComponents()
      .filter((name) => !previewExemptDesignSections.has(name))
      .filter((name) => !previewSources.includes(`<${name}`));

    expect(missing).toEqual([]);
  });
});
