// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getWorkbenchUiPreferences, saveWorkbenchUiPreferences, type WorkbenchUiPreferences } from "../api/workbenchUiPreferences";
import { readPaneLayout, writePaneLayout } from "../components/layout/paneLayoutPersistence";
import { flushWorkbenchUiPreferencesToServer, resetWorkbenchUiPreferencesSyncForTests, startWorkbenchUiPreferencesSync } from "./workbenchUiPreferencesSync";

vi.mock("../api/workbenchUiPreferences", () => ({ getWorkbenchUiPreferences: vi.fn(), saveWorkbenchUiPreferences: vi.fn() }));

const pendingKey = "vibelution.workbench-ui-pending-layouts.v1";
const widths = (sidebar: number) => ({ sidebar, aside: 280 });
let server: WorkbenchUiPreferences;
let stop: (() => void) | undefined;
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const reply = (sidebar: number) => ({ ok: true, preferences: { ...server, paneLayouts: { ...server.paneLayouts, finance: widths(sidebar) } } });

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  localStorage.clear();
  resetWorkbenchUiPreferencesSyncForTests();
  server = { schemaVersion: 1, paneLayouts: { finance: widths(280), chat: { left: 300, right: 320 } }, shell: {} };
  vi.mocked(getWorkbenchUiPreferences).mockImplementation(async () => server);
  vi.mocked(saveWorkbenchUiPreferences).mockImplementation(async (payload) => {
    if (payload.paneLayout) server = { ...server, paneLayouts: { ...server.paneLayouts, [payload.paneLayout.layoutId]: { ...payload.paneLayout.widths } } };
    return { ok: true, preferences: server };
  });
});

afterEach(() => { stop?.(); stop = undefined; resetWorkbenchUiPreferencesSyncForTests(); vi.restoreAllMocks(); vi.useRealTimers(); localStorage.clear(); });

async function start() { stop = startWorkbenchUiPreferencesSync(); await settle(); }

describe("workbench pane preference synchronization", () => {
  it("keeps an unsynced local resize when the page reloads before the debounce fires", async () => {
    // Generation ids may contain the same digits as a width; they are not a
    // duplicate width snapshot. Keep the observed collision deterministic.
    vi.spyOn(crypto, "randomUUID").mockReturnValueOnce("f3793044-532a-4925-b0ee-610f0f6db6c7");
    await start();
    writePaneLayout("finance", widths(304));
    stop?.();
    resetWorkbenchUiPreferencesSyncForTests();
    vi.mocked(saveWorkbenchUiPreferences).mockRejectedValue(new Error("offline"));
    await start();
    expect(readPaneLayout("finance")).toEqual(widths(304));
    expect(JSON.parse(localStorage.getItem(pendingKey)!)).toEqual({
      schemaVersion: 1,
      layouts: { finance: "f3793044-532a-4925-b0ee-610f0f6db6c7" },
    });
  });

  it("accepts newer server widths for a clean local cache", async () => {
    writePaneLayout("finance", widths(280));
    server.paneLayouts.finance = widths(328);
    await start();
    expect(readPaneLayout("finance")).toEqual(widths(328));
    expect(saveWorkbenchUiPreferences).not.toHaveBeenCalled();
  });

  it("protects a resize made while the initial server read is still in flight", async () => {
    writePaneLayout("finance", widths(280));
    let hydrate!: (preferences: WorkbenchUiPreferences) => void;
    vi.mocked(getWorkbenchUiPreferences).mockImplementationOnce(() => new Promise(resolve => { hydrate = resolve; }));
    stop = startWorkbenchUiPreferencesSync();
    writePaneLayout("finance", widths(304));
    hydrate(server);
    await settle();
    expect(readPaneLayout("finance")).toEqual(widths(304));
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledExactlyOnceWith({ paneLayout: { layoutId: "finance", widths: widths(304) } });
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("saves only the changed layout and acknowledges the exact returned snapshot", async () => {
    await start();
    server.paneLayouts.agents = { sidebar: 350 };
    writePaneLayout("finance", widths(304));
    await flushWorkbenchUiPreferencesToServer();
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledExactlyOnceWith({ paneLayout: { layoutId: "finance", widths: widths(304) } });
    expect(server.paneLayouts.agents).toEqual({ sidebar: 350 });
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("keeps failed saves pending without replacing the local widths", async () => {
    await start();
    vi.mocked(saveWorkbenchUiPreferences).mockRejectedValue(new Error("offline"));
    writePaneLayout("finance", widths(304));
    await flushWorkbenchUiPreferencesToServer();
    expect(readPaneLayout("finance")).toEqual(widths(304));
    expect(localStorage.getItem(pendingKey)).toContain("finance");
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledTimes(1);
  });

  it("does not acknowledge a response that did not retain the requested widths", async () => {
    await start();
    vi.mocked(saveWorkbenchUiPreferences).mockResolvedValue(reply(280));
    writePaneLayout("finance", widths(304));
    await flushWorkbenchUiPreferencesToServer();
    expect(localStorage.getItem(pendingKey)).toContain("finance");
    expect(readPaneLayout("finance")).toEqual(widths(304));
  });

  it("acknowledges submitted pane values even when the server retains other pane keys", async () => {
    await start();
    vi.mocked(saveWorkbenchUiPreferences).mockResolvedValue({ ok: true, preferences: {
      ...server, paneLayouts: { ...server.paneLayouts, finance: { ...widths(304), legacyPane: 300 } },
    } });
    writePaneLayout("finance", widths(304));
    await flushWorkbenchUiPreferencesToServer();
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("does not hydrate after the last subscriber stops", async () => {
    writePaneLayout("finance", widths(304));
    let hydrate!: (preferences: WorkbenchUiPreferences) => void;
    vi.mocked(getWorkbenchUiPreferences).mockImplementationOnce(() => new Promise(resolve => { hydrate = resolve; }));
    stop = startWorkbenchUiPreferencesSync();
    stop();
    hydrate(server);
    await settle();
    expect(readPaneLayout("finance")).toEqual(widths(304));
    expect(saveWorkbenchUiPreferences).not.toHaveBeenCalled();
  });

  it("keeps observing while another subscriber is still mounted", async () => {
    await start();
    const stopFirst = stop!;
    stop = startWorkbenchUiPreferencesSync();
    stopFirst();
    writePaneLayout("finance", widths(304));
    await flushWorkbenchUiPreferencesToServer();
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledExactlyOnceWith({ paneLayout: { layoutId: "finance", widths: widths(304) } });
  });

  it("serializes the new mount behind an old request without letting its response acknowledge the new edit", async () => {
    await start();
    let first!: (value: Awaited<ReturnType<typeof saveWorkbenchUiPreferences>>) => void;
    let second!: typeof first;
    vi.mocked(saveWorkbenchUiPreferences)
      .mockImplementationOnce(() => new Promise(resolve => { first = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { second = resolve; }));
    writePaneLayout("finance", widths(304));
    const saving = flushWorkbenchUiPreferencesToServer();
    stop!();
    stop = startWorkbenchUiPreferencesSync();
    await settle();
    writePaneLayout("finance", widths(328));
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledTimes(1);
    first(reply(304));
    await saving;
    await settle();
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledTimes(2);
    expect(saveWorkbenchUiPreferences).toHaveBeenLastCalledWith({ paneLayout: { layoutId: "finance", widths: widths(328) } });
    expect(localStorage.getItem(pendingKey)).toContain("finance");
    second(reply(328));
    await settle();
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("serializes changed generations and never acknowledges a newer resize with an older response", async () => {
    await start();
    let first!: (value: Awaited<ReturnType<typeof saveWorkbenchUiPreferences>>) => void;
    let second!: typeof first;
    vi.mocked(saveWorkbenchUiPreferences)
      .mockImplementationOnce(() => new Promise(resolve => { first = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { second = resolve; }));
    writePaneLayout("finance", widths(304));
    const saving = flushWorkbenchUiPreferencesToServer();
    writePaneLayout("finance", widths(328));
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledTimes(1);
    first(reply(304));
    await settle();
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledTimes(2);
    expect(saveWorkbenchUiPreferences).toHaveBeenLastCalledWith({ paneLayout: { layoutId: "finance", widths: widths(328) } });
    expect(localStorage.getItem(pendingKey)).toContain("finance");
    expect(readPaneLayout("finance")).toEqual(widths(328));
    second(reply(328));
    await saving;
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("bootstraps a local layout absent from the server through the merge API", async () => {
    writePaneLayout("finance", widths(304));
    server = { schemaVersion: 1, paneLayouts: {}, shell: {} };
    await start();
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledWith({ paneLayout: { layoutId: "finance", widths: widths(304) } });
  });

  it("keeps only the failed layout pending when another layout succeeds", async () => {
    await start();
    vi.mocked(saveWorkbenchUiPreferences).mockRejectedValueOnce(new Error("offline"));
    writePaneLayout("finance", widths(304));
    writePaneLayout("chat", { left: 340, right: 320 });
    await flushWorkbenchUiPreferencesToServer();
    expect(saveWorkbenchUiPreferences).toHaveBeenCalledTimes(2);
    const pending = JSON.parse(localStorage.getItem(pendingKey)!);
    expect(Object.keys(pending.layouts)).toEqual(["finance"]);
    expect(readPaneLayout("chat")).toEqual({ left: 340, right: 320 });
  });
});
