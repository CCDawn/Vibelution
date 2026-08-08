import { describe, expect, it } from "vitest";

import {
  chatSelectionStorageKey,
  parseChatSelectionSearch,
  reconcileChatSelection,
  resolveChatSelection,
  selectChatAgent,
  selectChatRoom,
  selectChatSession,
  serializeChatSelectionSearch,
} from "./chatSelectionProjection";

describe("chat selection projection", () => {
  const sessionsById = new Map([
    ["session-gpt", "agent-gpt"],
    ["session-luna", "agent-luna"],
  ]);

  it("keeps URL selection authoritative and derives agent from the session", () => {
    const result = resolveChatSelection({
      url: { sessionId: "session-luna", agentId: "agent-old" },
      local: { sessionId: "session-gpt", agentId: "agent-gpt" },
      server: { sessionId: "session-gpt", agentId: "agent-gpt" },
      availability: { sessionsById },
    });
    expect(result.source).toBe("url");
    expect(result.selection).toMatchObject({ sessionId: "session-luna", agentId: "agent-luna" });
  });

  it("does not fall back while the session index is still unavailable", () => {
    const result = resolveChatSelection({
      url: { sessionId: "session-pending", agentId: "agent-pending" },
      availability: undefined,
    });
    expect(result.selection).toMatchObject({ sessionId: "session-pending", agentId: "agent-pending" });
  });

  it("reconciles a stale session to the first valid agent/session only after data is authoritative", () => {
    const result = reconcileChatSelection(
      { sessionId: "session-deleted", agentId: "agent-deleted" },
      {
        agentIds: new Set(["agent-gpt"]),
        sessionsById: new Map([["session-gpt", "agent-gpt"]]),
        firstAgentId: "agent-gpt",
        firstSessionId: "session-gpt",
      },
    );
    expect(result).toMatchObject({ sessionId: "session-gpt", agentId: "agent-gpt" });
  });

  it("serializes and parses the durable projection without dropping unrelated params", () => {
    const search = serializeChatSelectionSearch("?filter=recent", {
      agentId: "agent-luna",
      sessionId: "session-luna",
      tabId: "agent",
    });
    expect(search).toContain("filter=recent");
    expect(parseChatSelectionSearch(search)).toMatchObject({
      agentId: "agent-luna",
      sessionId: "session-luna",
      tabId: "agent",
    });
  });

  it("makes agent/session/room transitions mutually exclusive", () => {
    const agent = selectChatAgent({ sessionId: "session-old" }, "agent-luna", "session-luna");
    expect(agent).toMatchObject({ agentId: "agent-luna", sessionId: "session-luna", roomId: null });
    const session = selectChatSession(agent, "session-gpt", "agent-gpt");
    expect(session).toMatchObject({ agentId: "agent-gpt", sessionId: "session-gpt", roomId: null });
    expect(selectChatRoom(session, "room-team")).toMatchObject({
      roomId: "room-team",
      sessionId: null,
    });
  });

  it("uses a versioned project/user key for local fallback isolation", () => {
    expect(chatSelectionStorageKey("project A", "user/1")).toBe(
      "vibelution.chat-selection.v1:project%20A:user%2F1",
    );
  });
});
