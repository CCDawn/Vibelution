import { describe, expect, it } from "vitest";

import routeSource from "./ChatCodingRoute.tsx?raw";
import tabStripSource from "./AgentSessionTabStrip.tsx?raw";
import lifecycleSource from "./chat/useChatWorkspaceLifecycle.ts?raw";

describe("ChatCodingRoute Agent-session hierarchy", () => {
  it("uses Agent navigation on the left and queries tabs by the selected Agent", () => {
    expect(routeSource).toContain("AgentConversationDirectory,");
    expect(routeSource).toContain("visibleDirectoryAgents,");
    expect(routeSource).toContain('from "./AgentConversationDirectory"');
    expect(routeSource).toContain('queryKey: ["sessions", "agent", selectedChatAgentId]');
    expect(routeSource).toContain('`/api/sessions/query?agentId=${encodeURIComponent(selectedChatAgentId)}&limit=100`');
    expect(routeSource).toContain("<AgentConversationDirectory");
    expect(routeSource).toContain('import("./agent-create/AgentCreateWizardDialog")');
    expect(routeSource).toContain("setAgentCreateWizardOpen(true)");
    expect(routeSource).toContain("<AgentCreateWizardDialog");
    expect(routeSource).toContain("{agentCreateWizardOpen ? (");
    expect(routeSource).toContain("triggerRef={agentCreateTriggerRef}");
    expect(routeSource).toContain("createAgentButtonRef={agentCreateTriggerRef}");
    expect(routeSource).toContain("if (!agent.directSessionId) return false");
    expect(routeSource).toContain("handleOpenAgent(agent)");
    expect(routeSource).toContain("handleOpenDirectSession(latestSession.id)");
    expect(routeSource).toContain("onOpenAgent={(agent, latestSession) => {");
    expect(routeSource).not.toContain("await createSessionMutation.mutateAsync({ agentId: agent.agentId })");
    expect(routeSource).not.toContain('createSessionMutation.mutate({ agentId: "" })');
    expect(routeSource).toContain("在当前 Agent 下新建会话");
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
