import { describe, expect, it } from "vitest";

import { InProcessDesktopSessionStore } from "../src/windows/desktopSessionStore.js";

describe("InProcessDesktopSessionStore", () => {
  it("registers a session and bumps revisions for in-process mutations", () => {
    const store = new InProcessDesktopSessionStore();
    const registration = store.register({ desktopSessionId: "electron-session-1", capabilities: ["a"] });
    expect(registration).toEqual({ desktopSessionId: "electron-session-1", revision: 1 });

    const windowState = {
      role: "workbench" as const,
      provider: "electron",
      open: true,
      focused: true,
      windowId: 7,
      rendererProcessId: 7070,
      url: "http://127.0.0.1:8000/"
    };
    const reported = store.reportWindow({
      desktopSessionId: "electron-session-1",
      role: "workbench",
      revision: 1,
      state: windowState
    });
    expect(reported.revision).toBe(2);
    expect(store.snapshot()?.windows.workbench).toMatchObject({ open: true, rendererProcessId: 7070 });

    const heartbeat = store.heartbeat({ desktopSessionId: "electron-session-1", revision: 2 });
    expect(heartbeat.revision).toBe(3);
  });

  it("rejects mutations with stale revisions", () => {
    const store = new InProcessDesktopSessionStore();
    store.register({ desktopSessionId: "electron-session-1", capabilities: [] });
    expect(() =>
      store.reportWindow({
        desktopSessionId: "electron-session-1",
        role: "workbench",
        revision: 9,
        state: { role: "workbench", provider: "electron", open: false, focused: false, windowId: 0, rendererProcessId: 0, url: "" }
      })
    ).toThrow("revision conflict");
  });

  it("closes the session and rejects further mutations", () => {
    const store = new InProcessDesktopSessionStore();
    store.register({ desktopSessionId: "electron-session-1", capabilities: [] });
    const closed = store.close({ desktopSessionId: "electron-session-1", revision: 1 });
    expect(closed.revision).toBe(2);
    expect(store.snapshot()).toBeNull();
    expect(() => store.heartbeat({ desktopSessionId: "electron-session-1", revision: 2 })).toThrow(
      "not registered"
    );
  });
});
