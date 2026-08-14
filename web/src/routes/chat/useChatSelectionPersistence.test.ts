import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  resolveStoredDirectChatSelection,
  storedChatSelectionBlocksServerBootstrap,
} from "./useChatSelectionPersistence";

const sessions: SessionSummary[] = [
  {
    id: "session-luna-1",
    title: "Luna 1",
    agentId: "agent-luna",
    status: "ready",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
    currentPhase: "complete",
  },
  {
    id: "session-gpt-1",
    title: "GPT 1",
    agentId: "agent-gpt",
    status: "ready",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
    currentPhase: "complete",
  },
];

describe("useChatSelectionPersistence", () => {
  it("restores a valid local session and derives its Agent", () => {
    expect(resolveStoredDirectChatSelection({
      agentId: "agent-luna",
      sessionId: "session-luna-1",
    }, sessions)).toEqual({
      agentId: "agent-luna",
      sessionId: "session-luna-1",
      roomId: null,
      tabId: null,
    });
  });

  it("rejects a stale local session instead of falling back to a different session", () => {
    expect(resolveStoredDirectChatSelection({
      agentId: "agent-luna",
      sessionId: "session-removed",
    }, sessions)).toBeNull();
  });

  it("uses the canonical session Agent when a local projection has a stale Agent id", () => {
    expect(resolveStoredDirectChatSelection({
      agentId: "agent-old",
      sessionId: "session-gpt-1",
    }, sessions)).toEqual({
      agentId: "agent-gpt",
      sessionId: "session-gpt-1",
      roomId: null,
      tabId: null,
    });
  });

  it("does not restore an archived session from local selection storage", () => {
    const archived = {
      ...sessions[0],
      hiddenFromIndex: true,
      archiveState: { status: "archived" },
    } as SessionSummary;

    expect(resolveStoredDirectChatSelection({
      agentId: "agent-luna",
      sessionId: "session-luna-1",
    }, [archived, sessions[1]])).toBeNull();
  });

  it("blocks server bootstrap while a stored viewing session can still restore", () => {
    const storage = {
      getItem: () => JSON.stringify({ sessionId: "session-luna-1", agentId: "agent-luna" }),
      setItem: () => undefined,
    };
    expect(storedChatSelectionBlocksServerBootstrap(undefined, storage)).toBe(true);
    expect(storedChatSelectionBlocksServerBootstrap(sessions, storage)).toBe(true);
    expect(storedChatSelectionBlocksServerBootstrap(sessions, {
      getItem: () => JSON.stringify({ sessionId: "session-removed" }),
      setItem: () => undefined,
    })).toBe(false);
    expect(storedChatSelectionBlocksServerBootstrap(sessions, {
      getItem: () => null,
      setItem: () => undefined,
    })).toBe(false);
  });
});
