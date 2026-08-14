import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  resolveBareRouteBootstrapTarget,
  resolveStoredDirectChatSelection,
  storedChatSelectionBlocksServerBootstrap,
  useChatSelectionPersistence,
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useChatSelectionPersistence", () => {
  it("reads the stored session during the first warm-cache bare-route render", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: () => JSON.stringify({ sessionId: "session-luna-1", agentId: "agent-luna" }),
        setItem: () => undefined,
      },
    });

    let bootstrapTarget: ReturnType<typeof useChatSelectionPersistence>["bareRouteBootstrapTarget"] = null;
    function Probe() {
      bootstrapTarget = useChatSelectionPersistence({
        selection: { kind: "bare" },
        serverSessionId: "session-gpt-1",
        activeSessionAgentId: "",
        selectedAgentId: "",
        sessions,
      }).bareRouteBootstrapTarget;
      return null;
    }

    renderToStaticMarkup(createElement(Probe));

    expect(bootstrapTarget).toEqual({ kind: "session", sessionId: "session-luna-1" });
  });

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

describe("resolveBareRouteBootstrapTarget", () => {
  it("prefers a valid stored last-viewed session over the server pointer", () => {
    expect(resolveBareRouteBootstrapTarget({
      stored: { sessionId: "session-luna-1", agentId: "agent-luna" },
      serverSessionId: "session-gpt-1",
      sessions,
    })).toEqual({ kind: "session", sessionId: "session-luna-1" });
  });

  it("falls back to a valid server pointer when no stored session exists", () => {
    expect(resolveBareRouteBootstrapTarget({
      stored: null,
      serverSessionId: "session-gpt-1",
      sessions,
    })).toEqual({ kind: "session", sessionId: "session-gpt-1" });
  });

  it("ignores a stale stored session and a stale server pointer", () => {
    expect(resolveBareRouteBootstrapTarget({
      stored: { sessionId: "session-removed" },
      serverSessionId: "session-removed-too",
      sessions,
    })).toEqual({ kind: "session", sessionId: "session-luna-1" });
  });

  it("falls back to the first visible session when no preference is valid", () => {
    expect(resolveBareRouteBootstrapTarget({
      stored: null,
      serverSessionId: "",
      sessions,
    })).toEqual({ kind: "session", sessionId: "session-luna-1" });
  });

  it("keeps the bare route when the directory is not authoritative or empty", () => {
    expect(resolveBareRouteBootstrapTarget({
      stored: { sessionId: "session-luna-1" },
      serverSessionId: "session-gpt-1",
      sessions: undefined,
    })).toBeNull();
    expect(resolveBareRouteBootstrapTarget({
      stored: null,
      serverSessionId: null,
      sessions: [],
    })).toBeNull();
  });
});
