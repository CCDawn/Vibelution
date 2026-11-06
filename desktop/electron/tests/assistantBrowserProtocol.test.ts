import { describe, expect, it, vi } from "vitest";
import type { AssistantBrowser, BrowserState } from "../src/browser/assistantBrowser.js";
import { parseMainControlClaim, projectMainControlResult } from "../src/assistant/mainControlTransport.js";
import { createBrowserMainControl, invokeOperatorBrowser, parseOperatorBrowserCommand } from "../src/browser/browserMainControl.js";

const deliveryId = "a".repeat(32), pageId = "12345678-1234-1234-1234-123456789abc", snapshotId = "87654321-4321-4321-4321-cba987654321";
const state = { pages: [{ id: pageId, url: "https://example.com/", title: "Example", loading: false, canGoBack: false, canGoForward: false }], activePageId: pageId, takeover: false };
const row = { deliveryId, action: "browser_interact", pageId, snapshotId, elementRef: "1", url: "https://example.com/path?q=one#section", elementName: "Save", operation: "click" } as const;
const claim = (r: unknown) => parseMainControlClaim({ schemaVersion: 1, request: r });
function setup() {
  const browser = { getState: vi.fn((): BrowserState => state), previewInteraction: vi.fn(async () => ({ pageId, snapshotId, elementRef: "1", url: row.url, title: "Example", name: "Save", role: "button" })),
    click: vi.fn(async () => {}), fill: vi.fn(async () => {}), open: vi.fn(async () => state), ensure: vi.fn(async () => state), select: vi.fn(() => state), back: vi.fn(async () => {}), forward: vi.fn(async () => {}), reload: vi.fn(async () => {}), snapshot: vi.fn(async () => ({ pageId, snapshotId, url: row.url, title: "Example", untrusted: true, text: "visible", elements: [] })), setBounds: vi.fn(), requestTakeover: vi.fn(async () => state) };
  const ensureWorkspace = vi.fn(async () => {});
  const control = createBrowserMainControl({ browser: () => browser as unknown as AssistantBrowser, ensureWorkspace });
  return { browser, ensureWorkspace, control };
}
describe("private browser protocol", () => {
  it.each([
    { action: "browser_ensure", url: "https://example.com/" },
    { action: "browser_select", pageId },
    { action: "browser_show" },
  ] as const)("keeps $action closed and shows the workspace before using the existing owner", async payload => {
    const request = claim({ deliveryId, ...payload })!;
    expect(request).toEqual({ deliveryId, ...payload });
    for (const extra of [{ source: "operator" }, { approved: true }, { operation: "resume" }, { value: "private" }]) {
      expect(() => claim({ deliveryId, ...payload, ...extra })).toThrow("ASSISTANT_MAIN_CONTROL_INVALID");
    }
    const f = setup();
    expect(await f.control(request as Parameters<typeof f.control>[0])).toEqual({ schemaVersion: 1, operation: payload.action.slice(8), code: "ok", state });
    const ownerCall = payload.action === "browser_ensure" ? f.browser.ensure : payload.action === "browser_select" ? f.browser.select : f.browser.getState;
    expect(f.ensureWorkspace.mock.invocationCallOrder[0]).toBeLessThan(ownerCall.mock.invocationCallOrder[0]);
    if (payload.action === "browser_ensure") expect(f.browser.ensure).toHaveBeenCalledWith(payload.url, "assistant");
    if (payload.action === "browser_select") expect(f.browser.select).toHaveBeenCalledWith(pageId, "assistant");
    expect(f.browser.open).not.toHaveBeenCalled(); expect(f.browser.requestTakeover).not.toHaveBeenCalled();
  });
  it("shows the workspace without creating pages or releasing an operator takeover", async () => {
    const f = setup(); const taken = { ...state, takeover: true };
    f.browser.getState.mockReturnValue(taken);
    expect(await f.control({ deliveryId, action: "browser_show" })).toEqual({ schemaVersion: 1, operation: "show", code: "ok", state: taken });
    expect(f.browser.ensure).not.toHaveBeenCalled(); expect(f.browser.select).not.toHaveBeenCalled(); expect(f.browser.open).not.toHaveBeenCalled();
    for (const action of ["browser_resume", "browser_takeover"]) expect(() => claim({ deliveryId, action })).toThrow();
  });
  it("shows an empty workspace without manufacturing an active page", async () => {
    const f = setup(); const empty = { pages: [], activePageId: null, takeover: false };
    f.browser.getState.mockReturnValue(empty);
    expect(await f.control({ deliveryId, action: "browser_show" })).toEqual({ schemaVersion: 1, operation: "show", code: "ok", state: empty });
    expect(f.browser.open).not.toHaveBeenCalled(); expect(f.browser.ensure).not.toHaveBeenCalled(); expect(f.browser.select).not.toHaveBeenCalled();
  });
  it.each(["browser_ensure", "browser_select", "browser_show"] as const)("never executes %s after workspace display is cancelled", async action => {
    const f = setup(); let release!: () => void;
    f.ensureWorkspace.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
    const request = claim({ deliveryId, action, ...(action === "browser_ensure" ? { url: "https://example.com/" } : action === "browser_select" ? { pageId } : {}) })!;
    const abort = new AbortController(); const pending = f.control(request as Parameters<typeof f.control>[0], abort.signal);
    abort.abort(); expect(await pending).toMatchObject({ code: "BROWSER_UNAVAILABLE" }); release(); await Promise.resolve();
    expect(f.browser.ensure).not.toHaveBeenCalled(); expect(f.browser.select).not.toHaveBeenCalled(); expect(f.browser.getState).not.toHaveBeenCalled();
  });
  it("binds execution to the approved page, snapshot, ref, URL and name", async () => {
    const f = setup();
    expect(await f.control(row)).toEqual({ schemaVersion: 1, operation: "interact", code: "ok", state });
    expect(f.browser.previewInteraction).toHaveBeenCalledWith(pageId, snapshotId, "1");
    expect(f.browser.click).toHaveBeenCalledWith(pageId, snapshotId, "1", "assistant");
    f.browser.click.mockClear();
    for (const target of [{ url: "https://evil.example/" }, { url: "https://example.com/path?q=two#section" }, { url: "https://example.com/path?q=one#different" }, { url: "https://EXAMPLE.com/path?q=one#section" }, { name: "Delete" }, { elementRef: "2" }, { snapshotId: pageId }, { pageId: snapshotId }]) {
      f.browser.previewInteraction.mockResolvedValueOnce({ pageId, snapshotId, elementRef: "1", url: row.url, title: "Example", name: "Save", role: "button", ...target });
      expect(await f.control(row)).toMatchObject({ code: "BROWSER_TARGET_UNAVAILABLE" });
    }
    expect(f.browser.click).not.toHaveBeenCalled();
    expect(await f.control({ ...row, operation: "fill", value: "hello" })).toMatchObject({ code: "ok" });
    expect(f.browser.fill).toHaveBeenCalledWith(pageId, snapshotId, "1", "hello", "assistant");
  });
  it("rejects extra fields, getters, poisoned prototypes and invalid origins, URLs or references", () => {
    for (const change of [{ url: "https://user:pass@example.com/" }, { url: "file:///x" }, { url: "" }, { url: "https://example.com/" + "x".repeat(8192) }, { elementRef: "0" }, { elementRef: "1000" }, { pageId: "not-a-uuid" }, { source: "operator" }, { value: "unexpected" }]) expect(() => claim({ ...row, ...change })).toThrow();
    const getter = { ...row }; Object.defineProperty(getter, "elementName", { enumerable: true, get() { throw new Error("must not run"); } });
    expect(() => claim(getter)).toThrow("ASSISTANT_MAIN_CONTROL_INVALID");
    expect(() => claim(Object.assign(Object.create({ evil: true }), row))).toThrow();
    expect(() => parseOperatorBrowserCommand({ operation: "open", url: "https://example.com", source: "assistant" })).toThrow();
    expect(() => parseOperatorBrowserCommand({ operation: "navigate", pageId, url: "javascript:alert(1)" })).toThrow();
  });
  it("rejects unsafe result shapes and enforces text, page and total size limits", () => {
    const request = claim({ deliveryId, action: "browser_read", pageId })!;
    const snap = { pageId, snapshotId, url: row.url, title: "T", untrusted: true, text: "x", elements: [{ ref: "1", role: "button", name: "Save" }] };
    const result = { schemaVersion: 1, operation: "read", code: "ok", snapshot: snap };
    expect(projectMainControlResult(request, result)).toEqual(result);
    for (const bad of [{ ...snap, text: "😀".repeat(4001) }, { ...snap, elements: Array(81).fill(snap.elements[0]) }, { ...snap, elements: [snap.elements[0], snap.elements[0]] }, { ...snap, url: "https://user:pass@example.com/" }, { ...snap, url: "" }, { ...snap, url: "https://example.com/" + "x".repeat(8192) }, { ...snap, text: "\u0000".repeat(8000), elements: Array.from({ length: 80 }, (_, i) => ({ ref: String(i + 1), role: "\u0000".repeat(40), name: "\u0000".repeat(160) })) }])
      expect(projectMainControlResult(request, { ...result, snapshot: bad })).toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
    const malicious = { ...snap }; Object.defineProperty(malicious, "text", { enumerable: true, get() { throw new Error("secret"); } });
    expect(projectMainControlResult(request, { ...result, snapshot: malicious })).toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
    expect(projectMainControlResult(request, { schemaVersion: 1, operation: "read", code: "BROWSER_ACTION_OUTCOME_UNKNOWN" })).toEqual({ schemaVersion: 1, operation: "read", code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
    expect(projectMainControlResult(request, { schemaVersion: 1, operation: "read", code: "BROWSER_URL_INVALID", message: "secret" })).toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
  });
  it("retains the complete approved address up to 8192 characters", () => {
    const prefix = "https://example.com/", url = prefix + "x".repeat(8192 - prefix.length - 4) + "?q#f";
    const parsed = claim({ ...row, url })!; expect(parsed).toMatchObject({ url });
    const request = claim({ deliveryId, action: "browser_read", pageId })!;
    const result = { schemaVersion: 1, operation: "read", code: "ok", snapshot: { pageId, snapshotId, url, title: "T", untrusted: true, text: "", elements: [] } };
    expect(projectMainControlResult(request, result)).toEqual(result);
    expect(() => claim({ ...row, url: url + "x" })).toThrow("ASSISTANT_MAIN_CONTROL_INVALID");
  });
  it("uses the browser owner to enforce read blocking while takeover is pending", async () => {
    const f = setup(); f.browser.snapshot.mockRejectedValueOnce(Object.assign(new Error("private details"), { code: "BROWSER_TAKEOVER_ACTIVE" }));
    expect(await f.control({ deliveryId, action: "browser_read", pageId })).toEqual({ schemaVersion: 1, operation: "read", code: "BROWSER_TAKEOVER_ACTIVE" });
    expect(f.browser.snapshot).toHaveBeenCalledWith(pageId); expect(f.browser.getState).not.toHaveBeenCalled();
  });
  it.each(["back", "forward", "reload"] as const)("awaits %s completion for assistant and operator", async operation => {
    const f = setup(); let finish!: () => void;
    f.browser[operation].mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
    let settled = false; const assistant = f.control({ deliveryId, action: `browser_${operation}`, pageId }).then(result => { settled = true; return result; });
    await Promise.resolve(); expect(f.browser[operation]).toHaveBeenCalledWith(pageId, "assistant"); expect(settled).toBe(false); expect(f.browser.getState).not.toHaveBeenCalled();
    finish(); expect(await assistant).toMatchObject({ code: "ok" });
    f.browser.getState.mockClear(); f.browser[operation].mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
    settled = false; const operator = invokeOperatorBrowser(f.browser as unknown as AssistantBrowser, { operation, pageId }).then(result => { settled = true; return result; });
    await Promise.resolve(); expect(f.browser[operation]).toHaveBeenCalledWith(pageId, "operator"); expect(settled).toBe(false); expect(f.browser.getState).not.toHaveBeenCalled();
    finish(); expect(await operator).toEqual(state);
  });
  it("does not replay unknown actions, and does not start after abort", async () => {
    const f = setup();
    let release!: () => void;
    f.browser.click.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
    const abort = new AbortController(); const pending = f.control(row, abort.signal);
    await vi.waitFor(() => expect(f.browser.click).toHaveBeenCalledTimes(1));
    abort.abort(); expect(await pending).toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" }); release();
    expect(f.browser.click).toHaveBeenCalledTimes(1);
    const before = new AbortController(); before.abort();
    expect(await f.control({ deliveryId, action: "browser_open", url: "https://example.com/" }, before.signal)).toMatchObject({ code: "BROWSER_UNAVAILABLE" });
    expect(f.ensureWorkspace).not.toHaveBeenCalled(); expect(f.browser.open).not.toHaveBeenCalled();
  });
  it("opens the workspace first and never acts after a cancelled preview", async () => {
    const f = setup();
    expect(await f.control({ deliveryId, action: "browser_open", url: "https://example.com/" })).toMatchObject({ code: "ok" });
    expect(f.ensureWorkspace.mock.invocationCallOrder[0]).toBeLessThan(f.browser.open.mock.invocationCallOrder[0]);
    let release!: (v: Awaited<ReturnType<typeof f.browser.previewInteraction>>) => void;
    f.browser.previewInteraction.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const abort = new AbortController(); const pending = f.control(row, abort.signal);
    abort.abort(); expect(await pending).toMatchObject({ code: "BROWSER_ACTION_OUTCOME_UNKNOWN" });
    release({ pageId, snapshotId, elementRef: "1", url: row.url, title: "Example", name: "Save", role: "button" });
    await Promise.resolve(); await Promise.resolve();
    expect(f.browser.click).not.toHaveBeenCalled();
  });
  it("uses the operator origin internally and only after strict command parsing", async () => {
    const f = setup();
    await invokeOperatorBrowser(f.browser as unknown as AssistantBrowser, { operation: "open", url: "https://example.com/" });
    expect(f.browser.open).toHaveBeenCalledWith("https://example.com/", "operator");
    expect(await invokeOperatorBrowser(f.browser as unknown as AssistantBrowser, { operation: "bounds", bounds: null })).toEqual(state);
    expect(f.browser.setBounds).toHaveBeenCalledWith(null);
    await expect(invokeOperatorBrowser(f.browser as unknown as AssistantBrowser, { operation: "bounds", bounds: { x: 0, y: 0, width: -1, height: 1 } })).rejects.toThrow();
  });
  it("retains the existing non-browser transport contract", () => {
    const old = { deliveryId, action: "launcher_theme_set", operation: "set", theme: "dark" };
    const parsed = claim(old)!; expect(parsed).toEqual(old);
    expect(projectMainControlResult(parsed, { schemaVersion: 1, operation: "set", code: "applied", theme: "dark" })).toEqual({ schemaVersion: 1, operation: "set", code: "applied", theme: "dark" });
    expect(() => claim({ ...old, source: "operator" })).toThrow();
  });
});
