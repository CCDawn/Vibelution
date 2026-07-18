import { describe, expect, it } from "vitest";

import directorySource from "./AgentConversationDirectory.tsx?raw";

describe("AgentConversationDirectory", () => {
  it("renders Agent identity as the left navigation item and keeps session count as metadata", () => {
    expect(directorySource).toContain('aria-label={lang === "zh" ? "Agent 管理" : "Agent management"}');
    expect(directorySource).toContain("agent.displayName");
    expect(directorySource).toContain("agent.llmBindings?.dialogue?.modelId");
    expect(directorySource).toContain("sessionCountByAgentId");
    expect(directorySource).toContain('aria-current={active ? "page" : undefined}');
  });
});
