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
  // Route-owned compositions of existing VUI APIs. Canonical Agent/Session
  // queries and the native desktop bridge supply their meaningful states;
  // none is a standalone VUI export. Covered by personal-assistant route,
  // overview, identity/return interaction tests and native desktop acceptance.
  "PersonalAssistantRoute",
  "DesktopAssistantRoute",
  "PersonalAssistantOverview",
  "PersonalAssistantState",
  // Server-bound product dialog: settings payload and whitelisted model
  // choices come from the personal-assistant settings API and session LLM
  // options, so its meaningful state cannot be expressed as a static preview.
  // Covered by its dialog interaction tests (open/rename/appearance/model).
  "PersonalAssistantSettings",
  "DesktopAssistantReturnNotice",
  // Dual-channel human-attention surfaces bound to the native desktop bridge:
  // the notifier renders null and is driven by overview polling plus
  // notifyHumanAttention/onHumanAttentionOpened; the notice stack's cards only
  // arrive through the Electron preload delivery channel inside the floating
  // assistant window. Covered by their trigger-chain, dedup, card render,
  // click/close/stack and 12s hover-pause interaction tests.
  "HumanAttentionNotifier",
  "HumanAttentionNoticeStack",
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
