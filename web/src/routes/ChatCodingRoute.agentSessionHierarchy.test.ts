import { describe, expect, it } from "vitest";

import routeSource from "./ChatCodingRoute.tsx?raw";
import tabStripSource from "./AgentSessionTabStrip.tsx?raw";

describe("ChatCodingRoute Agent-session hierarchy", () => {
  it("uses Agent navigation on the left and queries tabs by the selected Agent", () => {
    expect(routeSource).toContain('import { AgentConversationDirectory } from "./AgentConversationDirectory"');
    expect(routeSource).toContain('queryKey: ["sessions", "agent", selectedChatAgentId]');
    expect(routeSource).toContain('`/api/sessions/query?agentId=${encodeURIComponent(selectedChatAgentId)}&limit=100`');
    expect(routeSource).toContain("<AgentConversationDirectory");
    expect(routeSource).toContain('import { AgentCreateWizardDialog } from "./agent-create/AgentCreateWizardDialog"');
    expect(routeSource).toContain("setAgentCreateWizardOpen(true)");
    expect(routeSource).toContain("<AgentCreateWizardDialog");
    expect(routeSource).toContain("triggerRef={agentCreateTriggerRef}");
    expect(routeSource).toContain("createAgentButtonRef={agentCreateTriggerRef}");
    expect(routeSource).toContain("await createSessionMutation.mutateAsync({ agentId: agent.agentId })");
    expect(routeSource).not.toContain('createSessionMutation.mutate({ agentId: "" })');
    expect(routeSource).toContain("在当前 Agent 下新建会话");
  });

  it("uses the session title, not the Agent name, for root session tabs", () => {
    expect(tabStripSource).toContain("sessionIsChild ? (session.taskTitle || session.resultCard?.title || session.title) : session.title");
  });

  it("optimistically removes deleted sessions from Agent tab caches with rollback", () => {
    expect(routeSource).toContain("captureAgentSessionCacheSnapshots(queryClient)");
    expect(routeSource).toContain("removeSessionFromAgentSessionCaches(queryClient, variables.sessionId)");
    expect(routeSource).toContain(
      "restoreAgentSessionCacheSnapshots(queryClient, context?.previousAgentSessionCaches)",
    );
  });
});
