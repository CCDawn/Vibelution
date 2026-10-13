// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, useLocation, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  resolveBareRouteBootstrapTarget,
  resolveStoredDirectChatSelection,
  CHAT_SELECTION_STORAGE_KEY,
  readCurrentChatSelectionPreference,
  storedChatSelectionBlocksServerBootstrap,
  useChatSelectionPersistence,
} from "./useChatSelectionPersistence";
import { parseChatRouteSelection, type ChatRouteSelection } from "./chatSelectionProjection";

let root: Root | undefined;
let host: HTMLDivElement | undefined;
let currentPersistence: ReturnType<typeof useChatSelectionPersistence> | null = null;
let navigateRoute: NavigateFunction | null = null;

function PersistenceRouteProbe({
  activeSessionAgentId = "",
  selectedAgentId = "",
  serverSessionId = "",
  sessionRows = sessions,
  selectionOverride,
}: {
  activeSessionAgentId?: string;
  selectedAgentId?: string;
  serverSessionId?: string;
  sessionRows?: SessionSummary[];
  selectionOverride?: ChatRouteSelection;
}) {
  const location = useLocation();
  navigateRoute = useNavigate();
  currentPersistence = useChatSelectionPersistence({
    selection: selectionOverride ?? parseChatRouteSelection(location.search),
    serverSessionId,
    activeSessionAgentId,
    selectedAgentId,
    sessions: sessionRows,
  });
  return null;
}

async function mountRouteProbe(path: string, props: Parameters<typeof PersistenceRouteProbe>[0] = {}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root?.render(createElement(
    MemoryRouter,
    { initialEntries: [path] },
    createElement(PersistenceRouteProbe, props),
  )));
}

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

afterEach(async () => {
  if (root) {
    await act(async () => root?.unmount());
    root = undefined;
  }
  host?.remove();
  host = undefined;
  currentPersistence = null;
  navigateRoute = null;
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

    renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ["/chat"] }, createElement(Probe)));

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

  it("safely reads the current preference through the hook-owned storage key", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: () => JSON.stringify({ sessionId: "session-luna-1", agentId: "agent-luna" }),
      },
    });
    expect(readCurrentChatSelectionPreference()).toMatchObject({
      sessionId: "session-luna-1",
      agentId: "agent-luna",
    });
  });

  it("persists only a changed route selection and uses the canonical session Agent", async () => {
    window.localStorage.removeItem(CHAT_SELECTION_STORAGE_KEY);
    const setItem = vi.spyOn(window.localStorage, "setItem");
    await mountRouteProbe("/chat?session=session-luna-1", {
      activeSessionAgentId: "agent-gpt",
      selectedAgentId: "agent-gpt",
    });

    expect(readCurrentChatSelectionPreference()).toMatchObject({
      sessionId: "session-luna-1",
      agentId: "agent-luna",
    });
    expect(setItem).toHaveBeenCalledTimes(1);

    await act(async () => root?.render(createElement(
      MemoryRouter,
      { initialEntries: ["/chat?session=session-luna-1"] },
      createElement(PersistenceRouteProbe, {
        activeSessionAgentId: "agent-gpt",
        selectedAgentId: "agent-gpt",
        sessionRows: [...sessions].reverse(),
      }),
    )));

    expect(currentPersistence?.bareRouteBootstrapTarget).toBeNull();
    expect(readCurrentChatSelectionPreference()).toMatchObject({ agentId: "agent-luna" });
    expect(setItem).toHaveBeenCalledTimes(1);
  });

  it("does not persist an embedded Chat selection when its Finance URL points elsewhere", async () => {
    window.localStorage.removeItem(CHAT_SELECTION_STORAGE_KEY);
    const setItem = vi.spyOn(window.localStorage, "setItem");
    await mountRouteProbe("/finance?session=session-gpt-1", {
      selectionOverride: { kind: "session", sessionId: "session-luna-1" },
      activeSessionAgentId: "agent-luna",
      selectedAgentId: "agent-luna",
    });

    expect(readCurrentChatSelectionPreference()).toBeNull();
    expect(setItem).not.toHaveBeenCalled();
  });

  it("re-reads the latest stored Agent when the same workbench enters bare Chat", async () => {
    window.localStorage.setItem(CHAT_SELECTION_STORAGE_KEY, JSON.stringify({
      sessionId: "session-luna-1",
      agentId: "agent-luna",
    }));
    await mountRouteProbe("/chat?session=session-luna-1");

    window.localStorage.setItem(CHAT_SELECTION_STORAGE_KEY, JSON.stringify({
      sessionId: "session-gpt-1",
      agentId: "agent-gpt",
    }));
    await act(async () => navigateRoute?.("/chat"));

    expect(currentPersistence?.storedSelection).toMatchObject({ agentId: "agent-gpt" });
    expect(currentPersistence?.bareRouteBootstrapTarget).toEqual({ kind: "session", sessionId: "session-gpt-1" });
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

  it("falls back to the stored Agent's visible session before the server pointer", () => {
    expect(resolveBareRouteBootstrapTarget({
      stored: { sessionId: "session-removed", agentId: "agent-luna" },
      serverSessionId: "session-gpt-1",
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
