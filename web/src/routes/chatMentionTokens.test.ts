import { describe, expect, it } from "vitest";

import type { AgentInstance } from "../api/types";
import { buildChatMentionTargets, tokenizeChatMentions } from "./chatMentionTokens";

function agent(partial: Partial<AgentInstance>): AgentInstance {
  return {
    agentId: partial.agentId ?? "agent-1",
    agentCode: partial.agentCode ?? "A001",
    displayName: partial.displayName ?? "Agent One",
    kind: partial.kind ?? "persistent",
    primaryMode: partial.primaryMode ?? "research",
    roleKey: partial.roleKey ?? "member",
    templateId: partial.templateId ?? "template",
    profileId: partial.profileId ?? "profile",
    promptTemplateId: partial.promptTemplateId ?? "prompt",
    directSessionId: partial.directSessionId ?? "session-1",
    workspacePath: partial.workspacePath ?? "",
    toolPolicyId: partial.toolPolicyId ?? "tools",
    memoryPolicyId: partial.memoryPolicyId ?? "memory",
    createdBy: partial.createdBy ?? "test",
    status: partial.status ?? "active",
    metadata: partial.metadata ?? {},
    createdAt: partial.createdAt ?? "2026-05-29T00:00:00Z",
    updatedAt: partial.updatedAt ?? "2026-05-29T00:00:00Z",
  };
}

describe("chat mention tokens", () => {
  it("turns agent code and display-name mentions into clickable targets", () => {
    const targets = buildChatMentionTargets([
      agent({
        agentId: "agent-20260528-180638",
        agentCode: "A030",
        displayName: "苏若川",
        directSessionId: "session-20260528-180638",
      }),
    ]);

    const segments = tokenizeChatMentions("@A030请处理，@苏若川 看一下", targets);
    const mentions = segments.filter((segment) => segment.type === "mention");

    expect(mentions).toHaveLength(2);
    expect(mentions[0]).toMatchObject({
      text: "@A030",
      target: {
        kind: "agent",
        agentCode: "A030",
        displayName: "苏若川",
        directSessionId: "session-20260528-180638",
      },
    });
    expect(mentions[1]).toMatchObject({ text: "@苏若川" });
  });

  it("recognizes all-agent aliases and leaves unknown mentions as text", () => {
    const targets = buildChatMentionTargets([]);
    const segments = tokenizeChatMentions("@全体成员 同步，@不存在 暂不跳转", targets);

    expect(segments[0]).toMatchObject({
      type: "mention",
      text: "@全体成员",
      target: { kind: "all" },
    });
    expect(segments.map((segment) => segment.text).join("")).toBe("@全体成员 同步，@不存在 暂不跳转");
    expect(segments.filter((segment) => segment.type === "mention")).toHaveLength(1);
  });

  it("does not treat a shorter ASCII agent code as a prefix of a longer code", () => {
    const targets = buildChatMentionTargets([
      agent({ agentCode: "A03", displayName: "短码", directSessionId: "session-short" }),
    ]);

    expect(tokenizeChatMentions("@A030 不是短码", targets)).toEqual([
      { type: "text", text: "@A030 不是短码" },
    ]);
  });
});
