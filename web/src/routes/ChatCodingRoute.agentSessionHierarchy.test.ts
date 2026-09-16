import { describe, expect, it } from "vitest";

import routeSource from "./chat/ChatCodingRouteWorkbench.tsx?raw";
import visibleSessionCatalogSource from "./chat/useChatVisibleSessionCatalog.ts?raw";
import agentSessionTabsSource from "./chat/useChatAgentSessionTabs.ts?raw";
import tabStripSource from "./AgentSessionTabStrip.tsx?raw";
import lifecycleSource from "./chat/useChatWorkspaceLifecycle.ts?raw";
import agentDirectoryActionsSource from "./chat/useChatAgentDirectoryActions.ts?raw";

describe("ChatCodingRoute Agent-session hierarchy", () => {
  it("uses Agent navigation on the left and queries tabs by the selected Agent", () => {
    expect(routeSource).toContain("AgentConversationDirectory,");
    expect(routeSource).toContain('from "../AgentConversationDirectory"');
    expect(routeSource).toContain("useChatVisibleSessionCatalog");
    expect(routeSource).toContain("useChatAgentSessionTabs");
    expect(visibleSessionCatalogSource).toContain("visibleDirectoryAgents");
    expect(visibleSessionCatalogSource).toContain('from "../AgentConversationDirectory"');
    expect(agentSessionTabsSource).toContain('queryKey: ["sessions", "agent", selectedChatAgentId]');
    expect(agentSessionTabsSource).toContain("querySessions({");
    expect(agentSessionTabsSource).toContain("agentId: selectedChatAgentId");
    expect(agentSessionTabsSource).toContain("limit: 100");
    expect(routeSource).toContain("<AgentConversationDirectory");
    expect(routeSource).toContain('import("../agent-create/AgentCreateWizardDialog")');
    // Open wizard lives in directory actions hook (not inline in workbench).
    expect(agentDirectoryActionsSource).toContain("setAgentCreateWizardOpen(true)");
    expect(routeSource).toContain("<AgentCreateWizardDialog");
    expect(routeSource).toContain("{agentCreateWizardOpen ? (");
    expect(routeSource).toContain("triggerRef={agentCreateTriggerRef}");
    expect(routeSource).toContain("createAgentButtonRef={agentCreateTriggerRef}");
    expect(routeSource).toContain("if (!agent.directSessionId) return false");
    expect(routeSource).toContain("handleOpenAgent(agent)");
    expect(routeSource).not.toContain("handleOpenDirectSession(latestSession.id)");
    expect(routeSource).toContain("onOpenAgent={(agent) => {");
    expect(routeSource).not.toContain("await createSessionMutation.mutateAsync({ agentId: agent.agentId })");
    expect(routeSource).not.toContain('createSessionMutation.mutate({ agentId: "" })');
    expect(tabStripSource).toContain("在当前 Agent 下新建会话");
    expect(routeSource).toContain("onCreateSession={handleCreateSession}");
    expect(routeSource).not.toContain("<span>{lang === \"zh\" ? \"新建会话\" : \"New session\"}</span>");
    expect(lifecycleSource).toContain("setEditingSessionTitle(");
    expect(lifecycleSource).toContain("editingSessionIdRef.current === variables.sessionId");
    // Create shows the new session directly: the create flow never opens the
    // rename editor, so no temp-id editor is entered and no draft is trusted.
    expect(lifecycleSource).not.toContain("setEditingSessionId(tempSessionId)");
    expect(lifecycleSource).not.toContain("editingSessionIdRef.current = tempSessionId");
    expect(lifecycleSource).toContain("const editingTempTitle = Boolean(");
    // Only an operator-opened rename on the temp tab survives the remap.
    expect(lifecycleSource).toContain("if (keepFocusOnCreated && editingTempTitle) {");
    expect(lifecycleSource).toContain("suppressRenameBlurUntilRef.current = Date.now() + 2500");
    // New sessions default to the Agent display name (backend + optimistic shell).
    expect(lifecycleSource).toContain("agentDisplayName || defaultNewSessionTitle(lang)");
    expect(lifecycleSource).not.toContain("renameAgentDirectoryEntries(agents, agentId, confirmedTitle)");
  });

  it("uses each session title without root-child visual hierarchy", () => {
    expect(tabStripSource).toContain("const sessionTitle =");
    expect(tabStripSource).toContain("session.title");
    expect(tabStripSource).not.toContain("sessionIsChild");
    expect(tabStripSource).not.toContain("MessageCircleHeart");
  });

  it("optimistically removes deleted sessions from Agent tab caches with rollback", () => {
    expect(lifecycleSource).toContain("captureAgentSessionCacheSnapshots(queryClient)");
    expect(lifecycleSource).toContain("removeSessionFromAgentSessionCaches(queryClient, variables.sessionId)");
    expect(lifecycleSource).toContain(
      "restoreAgentSessionCacheSnapshots(queryClient, context?.previousAgentSessionCaches)",
    );
  });
});
