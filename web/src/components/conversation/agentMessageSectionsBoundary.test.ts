import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const conversationModuleDir = new URL("./", import.meta.url);

function moduleExists(name: string) {
  return existsSync(new URL(name, conversationModuleDir));
}

function moduleSource(name: string) {
  return readFileSync(new URL(name, conversationModuleDir), "utf8");
}

describe("agent message section module boundary", () => {
  it("splits AgentMessage sections from ConversationMessage predicates", () => {
    expect(moduleExists("agentMessageSections.ts")).toBe(true);
    expect(moduleExists("conversationMessagePredicates.ts")).toBe(true);
    expect(moduleExists("messageSections.ts")).toBe(false);

    const agentSectionSource = moduleSource("agentMessageSections.ts");
    const conversationPredicateSource = moduleSource("conversationMessagePredicates.ts");
    expect(agentSectionSource).toContain("buildAgentMessageSectionState");
    expect(agentSectionSource).not.toContain("ConversationMessage");
    expect(conversationPredicateSource).toContain("isTurnErrorMessage");
    expect(conversationPredicateSource).not.toContain("buildAgentMessageSectionState");

    for (const caller of [
      "ConversationView.tsx",
      "agentMessageRenderState.ts",
      "agentMessageOperations.ts",
      "timelineMessageProcessProjection.ts",
      "AgentContextSectionsView.tsx",
      "../../routes/ChatCodingRoute.tsx",
    ]) {
      expect(moduleSource(caller)).not.toContain("./messageSections");
      expect(moduleSource(caller)).not.toContain("/messageSections");
    }
  });
});
