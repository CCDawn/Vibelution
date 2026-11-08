import { EventEmitter } from "node:events";
import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ views: [] as any[], ses: null as any }));
vi.mock("electron", async () => {
  const { EventEmitter } = await import("node:events");
  class Contents extends EventEmitter {
    url = ""; title = "Page"; destroyed = false; input = vi.fn(); execute = vi.fn(async () => ({ text: "page", elements: [{ ref: "1", role: "button", name: "Go" }] }));
    navigationHistory = { canGoBack: () => false, canGoForward: () => false, goBack: vi.fn(), goForward: vi.fn() };
    setWindowOpenHandler = vi.fn(); isDestroyed() { return this.destroyed; } getURL() { return this.url; } getTitle() { return this.title; } isLoading() { return false; }
    async loadURL(url: string) { this.emit("did-start-navigation", {}, url, false, true); this.url = url; }
    executeJavaScriptInIsolatedWorld = (...args: unknown[]) => this.execute(...args);
    sendInputEvent = this.input; insertText = vi.fn(async () => {}); reload = vi.fn(); stop = vi.fn();
    close() { this.destroyed = true; this.emit("destroyed"); }
  }
  class View { webContents = new Contents(); setBounds = vi.fn(); getBounds = () => ({ x: 0, y: 0, width: 100, height: 100 }); constructor(public options: unknown) { mocks.views.push(this); } }
  class Session extends EventEmitter { setPermissionCheckHandler = vi.fn(); setPermissionRequestHandler = vi.fn(); }
  mocks.ses = new Session();
  return { WebContentsView: View, session: { fromPartition: vi.fn(() => mocks.ses) } };
});
import { AssistantBrowser } from "../src/browser/assistantBrowser.js";
class Host extends EventEmitter {
  destroyed = false; visible = true; minimized = false; contentView = { addChildView: vi.fn(), removeChildView: vi.fn() };
  isDestroyed() { return this.destroyed; } isVisible() { return this.visible; } isMinimized() { return this.minimized; } getContentSize() { return [600, 400]; }
}
function setup() {
  const host = new Host(), changed = vi.fn(); const browser = new AssistantBrowser({ getHost: () => host as never, onChanged: changed });
  browser.setBounds({ x: 0, y: 0, width: 500, height: 300 });
  return { host, browser, changed };
}
beforeEach(() => { mocks.views.length = 0; });
describe("Assistant embedded browser isolation", () => {
  it("uses a sandboxed separate session, denies permissions, popups, downloads and dangerous navigation", async () => {
    const { browser } = setup(); await browser.open("https://example.com", "operator"); const view = mocks.views[0], w = view.webContents;
    expect(view.options.webPreferences).toEqual({ partition: "persist:vibelution-assistant-browser", nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, webviewTag: false });
    expect(mocks.ses.setPermissionCheckHandler.mock.lastCall[0]()).toBe(false);
    const callback = vi.fn(); mocks.ses.setPermissionRequestHandler.mock.lastCall[0](null, "media", callback); expect(callback).toHaveBeenCalledWith(false);
    expect(w.setWindowOpenHandler.mock.lastCall[0]()).toEqual({ action: "deny" });
    const preventDefault = vi.fn(); w.emit("will-frame-navigate", { url: "file:///secret", preventDefault }); w.emit("will-redirect", { url: "javascript:alert(1)", preventDefault }); mocks.ses.emit("will-download", { preventDefault }); expect(preventDefault).toHaveBeenCalledTimes(3);
    for (const url of ["file:///secret", "javascript:alert(1)", "data:text/html,hi", "https://user:pass@example.com"]) await expect(browser.open(url, "assistant")).rejects.toMatchObject({ code: "BROWSER_URL_INVALID" });
  });
  it("caps pages and preserves exact query and fragment in observable URLs", async () => {
    const { browser } = setup(); for (let i = 0; i < 4; i++) await browser.open(`https://example.com/${i}?token=secret#fragment`, "assistant");
    expect(browser.getState().pages[0].url).toBe("https://example.com/0?token=secret#fragment");
    await expect(browser.open("https://example.com/5", "assistant")).rejects.toMatchObject({ code: "BROWSER_PAGE_LIMIT" });
  });
  it("reuses and selects an exact canonical URL even when all four pages are occupied", async () => {
    const { browser } = setup(); const url = "https://example.com/path?q=one#part";
    const id = (await browser.open(url, "assistant")).activePageId!;
    const load = vi.spyOn(mocks.views[0].webContents, "loadURL");
    for (let i = 0; i < 3; i++) await browser.open(`https://other.example/${i}`, "assistant");
    for (const target of ["https://EXAMPLE.com:443/path?q=one#part", url]) {
      expect((await browser.ensure(target, "assistant")).activePageId).toBe(id);
      expect(browser.getState().pages).toHaveLength(4);
    }
    expect(load).not.toHaveBeenCalled(); expect(mocks.views).toHaveLength(4);
    expect(await browser.snapshot(id)).toMatchObject({ pageId: id, url });
  });
  it.each(["https://example.com/path?q=two#part", "https://example.com/path?q=one#other", "https://example.com/else?q=one#part"])("does not reuse a different complete URL %s", async url => {
    const { browser } = setup(); const first = (await browser.open("https://example.com/path?q=one#part", "assistant")).activePageId!;
    const state = await browser.ensure(url, "assistant");
    expect(state.pages).toHaveLength(2); expect(state.activePageId).not.toBe(first);
    expect(state.pages.find(p => p.id === state.activePageId)?.url).toBe(url);
  });
  it("matches the current destination rather than a page's pre-redirect requested URL", async () => {
    const { browser } = setup(); const requested = "https://example.com/start", destination = "https://example.org/result";
    const id = (await browser.open(requested, "assistant")).activePageId!;
    mocks.views[0].webContents.url = destination;
    expect((await browser.ensure(destination, "assistant")).activePageId).toBe(id);
    expect((await browser.ensure(requested, "assistant")).pages).toHaveLength(2);
  });
  it("selects an existing page for the assistant and reads that page's current snapshot", async () => {
    const { browser } = setup(); const url = "https://example.com/selected?q=now#current";
    const id = (await browser.open(url, "assistant")).activePageId!;
    await browser.open("https://other.example/", "assistant");
    const first = mocks.views[0], second = mocks.views[1];
    const state = browser.select(id, "assistant");
    expect(state.activePageId).toBe(id); expect(state.pages).toHaveLength(2);
    expect(await browser.snapshot(id)).toMatchObject({ pageId: id, url });
    expect(first.webContents.execute).toHaveBeenCalledTimes(1); expect(second.webContents.execute).not.toHaveBeenCalled();
    expect(() => browser.select("not-an-existing-page", "assistant")).toThrow("BROWSER_PAGE_NOT_FOUND");
  });
  it("keeps explicit open creating pages and blocks ensure or selection during takeover", async () => {
    const { browser } = setup(); const url = "https://example.com/";
    const id = (await browser.open(url, "assistant")).activePageId!;
    expect((await browser.open(url, "assistant")).pages).toHaveLength(2);
    const pending = browser.requestTakeover("operator");
    await expect(browser.ensure(url, "assistant")).rejects.toMatchObject({ code: "BROWSER_TAKEOVER_ACTIVE" });
    expect(() => browser.select(id, "assistant")).toThrow("BROWSER_TAKEOVER_ACTIVE");
    await pending;
    await expect(browser.ensure("https://new.example/", "assistant")).rejects.toMatchObject({ code: "BROWSER_TAKEOVER_ACTIVE" });
    expect(() => browser.resume("assistant")).toThrow("BROWSER_SOURCE_FORBIDDEN");
    expect(browser.getState()).toMatchObject({ takeover: true, pages: [{}, {}] });
  });
  it("opens only the verified anchor destination in the same view and reports unknown outcome", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "assistant")).activePageId!; const w = mocks.views[0].webContents;
    const snap = await browser.snapshot(id); const load = vi.spyOn(w, "loadURL");
    w.execute.mockResolvedValueOnce({ navigateUrl: "https://destination.example/search?q=term#section" });
    await expect(browser.click(id, snap.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
    expect(load).toHaveBeenCalledExactlyOnceWith("https://destination.example/search?q=term#section");
    expect(mocks.views).toHaveLength(1); expect(w.setWindowOpenHandler.mock.lastCall[0]()).toEqual({ action: "deny" });
  });
  it("waits for a clicked anchor navigation before completing takeover", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    const snap = await browser.snapshot(id); w.execute.mockResolvedValueOnce({ navigateUrl: "https://destination.example/next" });
    let finish!: () => void; const load = vi.spyOn(w, "loadURL").mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
    const click = browser.click(id, snap.snapshotId, "1", "assistant"); const outcome = expect(click).rejects.toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(1)); let settled = false;
    const takeover = browser.requestTakeover("operator").then(state => { settled = true; return state; }); await Promise.resolve(); expect(settled).toBe(false);
    finish(); await outcome; expect((await takeover).takeover).toBe(true); expect(load).toHaveBeenCalledTimes(1);
  });
  it.each(["file:///secret", "javascript:alert(1)", "https://user:pass@example.com/", "https://example.com/\nsecret"])("rejects unsafe verified destination %s", async url => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    const snap = await browser.snapshot(id); const load = vi.spyOn(w, "loadURL"); w.execute.mockResolvedValueOnce({ navigateUrl: url });
    await expect(browser.click(id, snap.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_URL_INVALID" }); expect(load).not.toHaveBeenCalled();
    await expect(browser.navigate(id, url, "operator")).rejects.toMatchObject({ code: "BROWSER_URL_INVALID" });
  });
  it("limits untrusted snapshots and invalidates old refs on new snapshot, navigation, and close", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "assistant")).activePageId!; const w = mocks.views[0].webContents;
    w.execute.mockResolvedValue({ text: "x".repeat(10000), elements: Array.from({ length: 100 }, (_, i) => ({ ref: String(i + 1), name: "n".repeat(300), role: "button" })) });
    const a = await browser.snapshot(id); expect(a.untrusted).toBe(true); expect(a.text).toHaveLength(8000); expect(a.elements).toHaveLength(80); expect(a.elements[0].name).toHaveLength(160); expect(Buffer.byteLength(JSON.stringify(a))).toBeLessThan(128 * 1024);
    const b = await browser.snapshot(id); await expect(browser.click(id, a.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_SNAPSHOT_STALE" });
    await browser.navigate(id, "https://example.org", "assistant"); await expect(browser.click(id, b.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_SNAPSHOT_STALE" });
    browser.close(id, "operator"); await expect(browser.snapshot(id)).rejects.toMatchObject({ code: "BROWSER_PAGE_NOT_FOUND" });
  });
  it("reports an unlaid-out viewport and invalidates the previous snapshot", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    const previous = await browser.snapshot(id); w.execute.mockResolvedValueOnce({ viewportUnavailable: true });
    await expect(browser.snapshot(id)).rejects.toMatchObject({ code: "BROWSER_PAGE_NOT_VISIBLE" });
    await expect(browser.click(id, previous.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_SNAPSHOT_STALE" });
    w.execute.mockResolvedValueOnce({ text: "empty", elements: [] });
    expect(await browser.snapshot(id)).toMatchObject({ text: "empty", elements: [] });
  });
  it("bounds worst-case JSON escaping and provides a validated read-only approval preview", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com/?token=secret", "assistant")).activePageId!; const w = mocks.views[0].webContents;
    w.execute.mockResolvedValueOnce({ text: "\u0001".repeat(8000), elements: Array.from({ length: 80 }, (_, i) => ({ ref: String(i + 1), name: "\u0001".repeat(160), role: "\u0001".repeat(40) })) });
    const snap = await browser.snapshot(id); expect(Buffer.byteLength(JSON.stringify(snap))).toBeLessThanOrEqual(120 * 1024);
    w.execute.mockResolvedValueOnce({ x: 10, y: 10, name: "Search", role: "button" });
    expect(await browser.previewInteraction(id, snap.snapshotId, "1")).toMatchObject({ pageId: id, elementRef: "1", url: "https://example.com/?token=secret", name: "Search", role: "button" });
    expect(w.input).not.toHaveBeenCalled(); expect(w.insertText).not.toHaveBeenCalled();
  });
  it("binds previews to the complete URL and rejects oversized or credentialed current URLs", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com/path?q=one#part", "operator")).activePageId!; const w = mocks.views[0].webContents;
    const snap = await browser.snapshot(id); expect(snap.url).toBe("https://example.com/path?q=one#part");
    w.execute.mockResolvedValueOnce({ name: "Go", role: "button" }); expect((await browser.previewInteraction(id, snap.snapshotId, "1")).url).toBe(snap.url);
    w.url = "https://example.com/path?q=two#part"; await expect(browser.previewInteraction(id, snap.snapshotId, "1")).rejects.toMatchObject({ code: "BROWSER_SNAPSHOT_STALE" });
    w.url = "https://example.com/" + "a".repeat(8192); expect(() => browser.getState()).toThrow("BROWSER_URL_INVALID"); await expect(browser.snapshot(id)).rejects.toMatchObject({ code: "BROWSER_URL_INVALID" });
    w.url = "https://name:password@example.com/"; expect(() => browser.getState()).toThrow("BROWSER_URL_INVALID");
  });
  it("times out a hung snapshot, releases takeover, and ignores the late result", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    const previous = await browser.snapshot(id); let resolve!: (value: unknown) => void; w.execute.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    vi.useFakeTimers(); try {
      const hung = browser.snapshot(id); const failed = expect(hung).rejects.toMatchObject({ code: "BROWSER_SNAPSHOT_FAILED" }); const takeover = browser.requestTakeover("operator");
      await vi.advanceTimersByTimeAsync(8_000); await failed; expect((await takeover).takeover).toBe(true); browser.resume("operator");
      const current = await browser.snapshot(id); resolve({ text: "late", elements: [{ ref: "2", role: "button", name: "old" }] }); await Promise.resolve(); await Promise.resolve();
      await expect(browser.click(id, previous.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_SNAPSHOT_STALE" });
      w.execute.mockResolvedValueOnce({ clicked: true }); await expect(browser.click(id, current.snapshotId, "1", "assistant")).resolves.toBeUndefined();
    } finally { vi.useRealTimers(); }
  });
  it("destroys a timed-out action page before takeover and ignores its late result", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!;
    const otherId = (await browser.open("https://other.example", "operator")).activePageId!; browser.select(id, "operator");
    const w = mocks.views[0].webContents, other = mocks.views[1].webContents, snap = await browser.snapshot(id);
    let resolve!: (value: unknown) => void; w.execute.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const close = vi.spyOn(w, "close").mockImplementationOnce(() => { throw new Error("close did not complete"); }); const calls = w.execute.mock.calls.length; vi.useFakeTimers(); try {
      const click = browser.click(id, snap.snapshotId, "1", "assistant"); const failed = expect(click).rejects.toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
      let takeoverSettled = false; const takeover = browser.requestTakeover("operator").then(state => { takeoverSettled = true; return state; });
      await vi.advanceTimersByTimeAsync(8_000); expect(close).toHaveBeenCalledExactlyOnceWith({ waitForBeforeUnload: false });
      await Promise.resolve(); expect(takeoverSettled).toBe(false); expect(w.destroyed).toBe(false);
      w.destroyed = true; w.emit("destroyed"); await failed; const state = await takeover;
      expect(state.takeover).toBe(true); expect(state.pages.map(p => p.id)).toEqual([otherId]); expect(other.destroyed).toBe(false);
      resolve({ clicked: true }); await Promise.resolve(); await Promise.resolve(); expect(w.execute.mock.calls.length).toBe(calls + 1);
      expect(browser.getState().pages.map(p => p.id)).toEqual([otherId]);
    } finally { close.mockRestore(); vi.useRealTimers(); }
  });
  it("bounds preview and fill execution with operation-specific error codes", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    const first = await browser.snapshot(id); w.execute.mockImplementationOnce(() => new Promise(() => {})); vi.useFakeTimers(); try {
      const preview = browser.previewInteraction(id, first.snapshotId, "1"); const failPreview = expect(preview).rejects.toMatchObject({ code: "BROWSER_TARGET_UNAVAILABLE" });
      await vi.advanceTimersByTimeAsync(8_000); await failPreview;
      const second = await browser.snapshot(id); w.execute.mockImplementationOnce(() => new Promise(() => {}));
      const fill = browser.fill(id, second.snapshotId, "1", "text", "assistant"); const failFill = expect(fill).rejects.toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
      const takeover = browser.requestTakeover("operator"); await vi.advanceTimersByTimeAsync(8_000); await failFill; expect((await takeover).takeover).toBe(true);
    } finally { vi.useRealTimers(); }
  });
  it("waits for an already-started read before takeover and blocks new reads immediately", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    let resolve!: (value: unknown) => void; w.execute.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const order: string[] = []; const read = browser.snapshot(id).then(() => order.push("read")); const takeover = browser.requestTakeover("operator").then(() => order.push("takeover"));
    await expect(browser.snapshot(id)).rejects.toMatchObject({ code: "BROWSER_TAKEOVER_ACTIVE" }); expect(order).toEqual([]);
    resolve({ text: "page", elements: [] }); await read; await takeover; expect(order).toEqual(["read", "takeover"]);
  });
  it.each(["back", "forward", "reload"] as const)("waits for %s navigation before takeover", async operation => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    w.navigationHistory.canGoBack = () => true; w.navigationHistory.canGoForward = () => true;
    const order: string[] = []; const navigation = browser[operation](id, "assistant").then(() => order.push("navigation"));
    const takeover = browser.requestTakeover("operator").then(() => order.push("takeover"));
    w.emit("did-start-navigation", {}, "https://example.com/next", false, true); await Promise.resolve(); expect(order).toEqual([]);
    w.url = "https://example.com/next"; w.isLoading = () => true; w.emit("did-navigate", {}, w.url, 200, "OK"); w.emit("dom-ready");
    await navigation; await takeover; expect(order).toEqual(["navigation", "takeover"]);
  });
  it("fails and releases takeover on history timeout even when stop emits did-stop-loading", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    vi.useFakeTimers(); try {
      w.stop.mockImplementation(() => w.emit("did-stop-loading")); const navigation = browser.reload(id, "assistant");
      const result = expect(navigation).rejects.toMatchObject({ code: "BROWSER_NAVIGATION_FAILED" }); const takeover = browser.requestTakeover("operator");
      w.emit("did-start-navigation", {}, "https://example.com", false, true); await vi.advanceTimersByTimeAsync(15_000); await result;
      expect(w.stop).toHaveBeenCalledTimes(1); expect((await takeover).takeover).toBe(true); expect(browser.getState().pages[0].loadError).toBe(true);
    } finally { vi.useRealTimers(); }
  });
  it("settles same-document history without waiting for a page load", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    w.navigationHistory.canGoBack = () => true; const action = browser.back(id, "assistant");
    w.emit("did-start-navigation", {}, "https://example.com/#part", true, true);
    w.url = "https://example.com/#part"; w.emit("did-navigate-in-page", {}, w.url, true); await expect(action).resolves.toBeUndefined();
  });
  it("reports uncertain fill after dispatch without retrying", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents, snap = await browser.snapshot(id);
    w.execute.mockResolvedValueOnce({ filled: false }); const count = w.execute.mock.calls.length;
    await expect(browser.fill(id, snap.snapshotId, "1", "hello", "assistant")).rejects.toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
    expect(w.execute.mock.calls.length).toBe(count + 1);
  });
  it("publishes only main-frame failures, ignores aborts, and clears failure on navigation and success", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    const error = () => browser.getState().pages.find(p => p.id === id)?.loadError;
    w.emit("did-fail-load", {}, -105, "failure", "https://example.com/", false); expect(error()).toBe(false);
    w.emit("did-fail-load", {}, -3, "aborted", "https://example.com/", true); expect(error()).toBe(false);
    w.emit("did-fail-load", {}, -105, "failure", "https://example.com/", true); expect(error()).toBe(true);
    w.emit("did-start-navigation", {}, "https://example.com/new", false, true); expect(error()).toBe(false);
    w.emit("did-fail-load", {}, -105, "failure", "https://example.com/new", true); expect(error()).toBe(true);
    w.emit("did-finish-load"); expect(error()).toBe(true); // An old finish event cannot erase a newer failure.
    w.emit("did-start-navigation", {}, "https://example.com/retry", false, true); expect(error()).toBe(false);
  });
  it("returns well-formed bounded strings at surrogate boundaries", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    w.title = "t".repeat(199) + "😀" + "\ud800";
    w.execute.mockResolvedValueOnce({ text: "x".repeat(7999) + "😀", elements: [{ ref: "1", role: "button", name: "n".repeat(158) + "\ud800" + "😀" }] });
    const snap = await browser.snapshot(id); expect(snap.title.isWellFormed()).toBe(true); expect(snap.title.length).toBeLessThanOrEqual(200);
    expect(snap.text.isWellFormed()).toBe(true); expect(snap.elements[0].name.isWellFormed()).toBe(true); expect(snap.elements[0].name.length).toBeLessThanOrEqual(160);
    expect(browser.getState().pages[0].title.isWellFormed()).toBe(true);
  });
  it("accepts main-frame DOM readiness while resources still load and ignores a late abort", async () => {
    const { browser } = setup(); await browser.open("https://example.com", "operator");
    const prototype = Object.getPrototypeOf(mocks.views[0].webContents); let rejectOld!: (error: unknown) => void;
    const spy = vi.spyOn(prototype, "loadURL").mockImplementation(function(this: any, url: string) {
      this.emit("did-start-navigation", {}, url, false, true); this.url = url; return new Promise<void>((_resolve, reject) => { rejectOld = reject; });
    });
    try {
      const opening = browser.open("https://video.example/search?q=term", "assistant"); const w = mocks.views[1].webContents;
      w.isLoading = () => true; w.emit("did-navigate", {}, w.url, 200, "OK"); w.emit("dom-ready");
      const state = await opening; expect(state.pages.find(p => p.id === state.activePageId)).toMatchObject({ url: "https://video.example/search?q=term", loading: true, loadError: false });
      rejectOld(Object.assign(new Error("late aborted"), { code: "ERR_ABORTED" })); await Promise.resolve(); await Promise.resolve();
      expect(browser.getState().pages.find(p => p.id === state.activePageId)?.loadError).toBe(false); expect(w.stop).not.toHaveBeenCalled();
    } finally { spy.mockRestore(); }
  });
  it("waits for DOM readiness if a loading page changes its fragment after commit", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    w.loadURL = vi.fn((url: string) => { w.emit("did-start-navigation", {}, url, false, true); return new Promise(() => {}); });
    let settled = false; const navigation = browser.navigate(id, "https://example.com/new", "assistant").then(state => { settled = true; return state; });
    w.url = "https://example.com/new"; w.emit("did-navigate", {}, w.url, 200, "OK");
    w.url = "https://example.com/new#fragment"; w.emit("did-start-navigation", {}, w.url, true, true); w.emit("did-navigate-in-page", {}, w.url, true);
    await Promise.resolve(); expect(settled).toBe(false); w.emit("dom-ready"); expect((await navigation).pages[0].url).toBe(w.url);
  });
  it("rejects a superseded load promptly and ignores its late failure while the replacement proceeds", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    let rejectOld!: (error: unknown) => void;
    w.loadURL = vi.fn().mockImplementationOnce((url: string) => { w.emit("did-start-navigation", {}, url, false, true); return new Promise<void>((_r, reject) => { rejectOld = reject; }); })
      .mockImplementationOnce((url: string) => { w.emit("did-start-navigation", {}, url, false, true); return new Promise<void>(() => {}); });
    const old = browser.navigate(id, "https://example.com/old", "assistant"); const failed = expect(old).rejects.toMatchObject({ code: "BROWSER_NAVIGATION_FAILED" });
    const current = browser.navigate(id, "https://example.com/new", "assistant"); await failed;
    rejectOld(Object.assign(new Error("late failure"), { code: "ERR_FAILED" }));
    w.emit("did-fail-load", {}, -2, "old failure", "https://example.com/old", true); await Promise.resolve();
    expect(browser.getState().pages[0].loadError).toBe(false);
    w.url = "https://example.com/new"; w.emit("did-navigate", {}, w.url, 200, "OK"); w.emit("dom-ready");
    expect((await current).pages[0].url).toBe("https://example.com/new"); expect(w.stop).not.toHaveBeenCalled();
  });
  it("fails a main-frame load error before DOM readiness without waiting for resources", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    w.loadURL = vi.fn((url: string) => { w.emit("did-start-navigation", {}, url, false, true); return new Promise(() => {}); });
    const action = browser.navigate(id, "https://example.org/failed", "assistant");
    const result = expect(action).rejects.toMatchObject({ code: "BROWSER_NAVIGATION_FAILED" });
    w.emit("did-fail-load", {}, -105, "name not resolved", "https://example.org/failed", true); await result;
    expect(browser.getState().pages[0].loadError).toBe(true); expect(w.stop).not.toHaveBeenCalled();
  });
  it("rejects navigation promptly if the page is destroyed before DOM readiness", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    w.loadURL = vi.fn(() => new Promise(() => {})); const action = browser.navigate(id, "https://example.org", "assistant");
    const failed = expect(action).rejects.toMatchObject({ code: "BROWSER_NAVIGATION_FAILED" }); browser.close(id, "operator"); await failed;
  });
  it("times out a pending navigation, stops that load, and releases takeover", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    vi.useFakeTimers(); try {
      w.loadURL = vi.fn(() => new Promise(() => {}));
      const navigation = browser.navigate(id, "https://example.org", "assistant"); const result = expect(navigation).rejects.toMatchObject({ code: "BROWSER_NAVIGATION_FAILED" });
      const takeover = browser.requestTakeover("operator"); await vi.advanceTimersByTimeAsync(15_000); await result;
      expect(w.stop).toHaveBeenCalledTimes(1); expect(browser.getState().pages[0].loadError).toBe(true); expect((await takeover).takeover).toBe(true);
    } finally { vi.useRealTimers(); }
  });
  it("keeps an initial page visible as failed after its load times out", async () => {
    const { browser } = setup(); await browser.open("https://example.com", "operator");
    const prototype = Object.getPrototypeOf(mocks.views[0].webContents);
    vi.useFakeTimers(); const spy = vi.spyOn(prototype, "loadURL").mockImplementation(() => new Promise(() => {}));
    try {
      const opening = browser.open("https://example.org", "assistant"); const result = expect(opening).rejects.toMatchObject({ code: "BROWSER_NAVIGATION_FAILED" });
      await vi.advanceTimersByTimeAsync(15_000); await result;
      const page = browser.getState().pages.find(p => p.id === browser.getState().activePageId);
      expect(page?.loadError).toBe(true); expect(mocks.views[1].webContents.stop).toHaveBeenCalledTimes(1);
    } finally { spy.mockRestore(); vi.useRealTimers(); }
  });
  it("never stops a newer load when an older navigation times out", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const w = mocks.views[0].webContents;
    vi.useFakeTimers(); try {
      let finish!: () => void; w.loadURL = vi.fn().mockImplementationOnce(() => new Promise(() => {})).mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
      const old = browser.navigate(id, "https://example.org/old", "assistant"); const result = expect(old).rejects.toMatchObject({ code: "BROWSER_NAVIGATION_FAILED" });
      await vi.advanceTimersByTimeAsync(7_000); const current = browser.navigate(id, "https://example.org/new", "assistant");
      await vi.advanceTimersByTimeAsync(8_000); await result; expect(w.stop).not.toHaveBeenCalled(); expect(browser.getState().pages[0].loadError).toBe(false);
      finish(); await current;
    } finally { vi.useRealTimers(); }
  });
  it("blocks new actions immediately and publishes takeover after the existing action settles", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "assistant")).activePageId!; const w = mocks.views[0].webContents, snap = await browser.snapshot(id);
    let resolve!: (value: unknown) => void; w.execute.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const order: string[] = []; const action = browser.click(id, snap.snapshotId, "1", "assistant").then(() => order.push("action"));
    const takeover = browser.requestTakeover("operator").then(state => { order.push("takeover"); return state; });
    expect(browser.getState().takeover).toBe(false); expect(() => browser.scroll(id, "down", "assistant")).toThrow("BROWSER_TAKEOVER_ACTIVE");
    expect(() => browser.resume("operator")).toThrow("BROWSER_TAKEOVER_ACTIVE");
    expect(browser.getState().pages).toHaveLength(1); // Read-only state remains available.
    resolve({ clicked: true }); await action; expect((await takeover).takeover).toBe(true); expect(order).toEqual(["action", "takeover"]); expect(w.input).not.toHaveBeenCalled();
    expect(() => browser.resume("assistant")).toThrow("BROWSER_SOURCE_FORBIDDEN"); browser.resume("operator");
  });
  it("reports an unknown result when navigation races a submitted action and never retries it", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "assistant")).activePageId!; const w = mocks.views[0].webContents, snap = await browser.snapshot(id);
    let resolve!: (value: unknown) => void; w.execute.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const before = w.execute.mock.calls.length;
    const action = browser.click(id, snap.snapshotId, "1", "assistant"); const takeover = browser.requestTakeover("operator");
    w.emit("did-start-navigation", {}, "https://example.com/next", false, true); resolve({ clicked: true });
    await expect(action).rejects.toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" }); expect((await takeover).takeover).toBe(true);
    expect(w.execute.mock.calls.length).toBe(before + 1);
  });
  it("refuses unavailable targets and uses target-bound isolated scripts", async () => {
    const { browser } = setup(); const id = (await browser.open("https://example.com", "assistant")).activePageId!; const w = mocks.views[0].webContents, snap = await browser.snapshot(id);
    w.execute.mockResolvedValueOnce(null); await expect(browser.click(id, snap.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_TARGET_UNAVAILABLE" });
    w.execute.mockResolvedValueOnce({ clicked: true }); await browser.click(id, snap.snapshotId, "1", "assistant"); expect(w.input).not.toHaveBeenCalled();
    w.execute.mockResolvedValueOnce({ filled: true }); await browser.fill(id, snap.snapshotId, "1", "hello", "assistant"); expect(w.insertText).not.toHaveBeenCalled();
    expect(w.execute.mock.calls.at(-1)[0]).toBe(947); expect(w.execute.mock.calls.at(-1)[1][0].code).toContain("hello");
  });
  it("detaches on hide, constrains bounds, and rejects interaction while hidden", async () => {
    const { browser, host } = setup(); const id = (await browser.open("https://example.com", "operator")).activePageId!; const snap = await browser.snapshot(id), view = mocks.views[0];
    browser.setBounds({ x: 500, y: 300, width: 200, height: 200 }); expect(view.setBounds).toHaveBeenLastCalledWith({ x: 500, y: 300, width: 100, height: 100 });
    host.visible = false; host.emit("hide"); expect(host.contentView.removeChildView).toHaveBeenCalledWith(view);
    await expect(browser.click(id, snap.snapshotId, "1", "assistant")).rejects.toMatchObject({ code: "BROWSER_PAGE_NOT_VISIBLE" });
    expect(() => browser.setBounds({ x: 0, y: 0, width: 0, height: 10 })).toThrow("BROWSER_BOUNDS_INVALID");
    browser.dispose(); expect(view.webContents.destroyed).toBe(true);
  });
});
