import { beforeEach, describe, expect, it } from "vitest";

import { useChatWorkbenchStore } from "./chatWorkbenchStore";

describe("chatWorkbenchStore", () => {
  beforeEach(() => {
    useChatWorkbenchStore.setState({
      sessionWorkspaces: {},
    });
  });

  it("starts a hydrated session on the agent conversation only", () => {
    useChatWorkbenchStore
      .getState()
      .hydrateSession("session-live", ["config/settings.py"], "config/settings.py");

    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-live"]).toEqual({
      openTabs: [],
      activeTab: "agent",
    });
  });

  it("keeps manual file opens available after the agent-only default", () => {
    const store = useChatWorkbenchStore.getState();

    store.hydrateSession("session-live", ["config/settings.py"], "config/settings.py");
    useChatWorkbenchStore.getState().openPreviewTab("session-live", "config/settings.py");

    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-live"]).toEqual({
      openTabs: ["config/settings.py"],
      activeTab: "config/settings.py",
    });
  });

  it("removes a deleted session workspace without owning any active focus", () => {
    const store = useChatWorkbenchStore.getState();

    store.openPreviewTab("session-live", "config/settings.py");
    store.openPreviewTab("session-next", "core/web/services/session_service.py");

    useChatWorkbenchStore.getState().removeSession("session-live");

    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-live"]).toBeUndefined();
    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-next"]).toEqual({
      openTabs: ["core/web/services/session_service.py"],
      activeTab: "core/web/services/session_service.py",
    });
  });

  it("clears all session workspaces after destructive reset", () => {
    const store = useChatWorkbenchStore.getState();

    store.openPreviewTab("session-live", "config/settings.py");
    store.openPreviewTab("session-next", "core/web/services/session_service.py");

    useChatWorkbenchStore.getState().resetSessions();

    expect(useChatWorkbenchStore.getState().sessionWorkspaces).toEqual({});
  });

  it("does not carry any active session field in the workspace state shape", () => {
    const state = useChatWorkbenchStore.getState();
    expect("activeSessionId" in state).toBe(false);
    expect("setActiveSession" in state).toBe(false);
  });

  it("does not thrash subscribers when removeSession receives an unknown id", () => {
    const before = useChatWorkbenchStore.getState();
    useChatWorkbenchStore.getState().removeSession("session-unknown");
    const after = useChatWorkbenchStore.getState();
    expect(after).toBe(before);
    expect(after.sessionWorkspaces).toEqual(before.sessionWorkspaces);
  });
});
