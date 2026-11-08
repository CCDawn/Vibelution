// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserState, safeBrowserUrl } from "../../api/launcherAssistantBrowser";
import { LauncherAssistantBrowserWorkspace } from "./LauncherAssistantBrowserWorkspace";
import type { LauncherControlContinuation } from "./useLauncherControlContinuation";
const control = vi.hoisted(() => ({ capture: vi.fn(), complete: vi.fn(), cancel: vi.fn() }));
vi.mock("./LauncherAssistantRoute", () => ({ LauncherAssistantRoute: ({ onControlContinuationReady }: { onControlContinuationReady?: (value: LauncherControlContinuation | null) => void }) => {
  React.useEffect(() => { onControlContinuationReady?.(control); return () => onControlContinuationReady?.(null); }, [onControlContinuationReady]);
  return <div>原生对话<input aria-label="对话草稿" /></div>;
} }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const page = { id: "one", url: "https://example.com/path?secret=1#part", title: "Example", loading: false, canGoBack: true, canGoForward: false };
const initial = { pages: [page], activePageId: "one", takeover: false };
let root: Root, host: HTMLDivElement, invoke: ReturnType<typeof vi.fn>, onChanged: ReturnType<typeof vi.fn>;
function button(label: string) { const found = [...host.querySelectorAll("button")].find(node => node.getAttribute("aria-label") === label || node.textContent?.trim() === label); if (!found) throw new Error(`Missing ${label}`); return found; }
beforeEach(() => {
  control.capture.mockReset(); control.complete.mockReset(); control.cancel.mockReset();
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 1000 });
  window.localStorage.clear();
  invoke = vi.fn(async () => initial); onChanged = vi.fn(() => () => {});
  window.vibelutionLauncherBrowser = { invoke, onChanged };
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); delete window.vibelutionLauncherBrowser; vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render(revealRequested = true) { await act(async () => { root.render(<LauncherAssistantBrowserWorkspace revealRequested={revealRequested} />); }); }
describe("Launcher browser workspace", () => {
  it.each([1000, 600])("starts in conversation at %spx and reveals the same pane on a native request", async width => {
    window.innerWidth = width;
    let show: (() => void) | undefined;
    window.vibelutionLauncherBrowser!.onShow = listener => { show = listener; return () => {}; };
    await render(false);
    const draft = host.querySelector<HTMLInputElement>('input[aria-label="对话草稿"]')!;
    draft.value = "保留草稿";
    expect(button("打开网页")).toBeTruthy();
    expect(host.querySelector('[data-vui="split-workspace"]')?.className).toContain('[&>[data-vui=split-main]]:!hidden');
    expect(button("打开网页").textContent).toBe("网页");
    expect([...host.querySelectorAll("button[aria-pressed]")].some(node => node.textContent === "网页")).toBe(false);
    await act(async () => show?.());
    expect(host.querySelector('button[aria-label="打开网页"]')).toBeNull();
    expect(host.querySelector<HTMLInputElement>('input[aria-label="对话草稿"]')).toBe(draft);
    expect(draft.value).toBe("保留草稿");
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "close")).toBe(false);
  });
  it("reveals a legacy request without replacing the conversation and stays closed after the user folds it", async () => {
    await render(false);
    const draft = host.querySelector<HTMLInputElement>('input[aria-label="对话草稿"]')!;
    draft.value = "同一会话";
    await render(true);
    expect(host.querySelector('button[aria-label="打开网页"]')).toBeNull();
    expect(host.querySelector('input[aria-label="对话草稿"]')).toBe(draft);
    await act(async () => button("收起网页").click());
    await render(true);
    expect(button("打开网页")).toBeTruthy();
    expect(draft.value).toBe("同一会话");
  });
  it("drags beyond 520px and keeps browser space when the workspace shrinks", async () => {
    let width = 1200;
    const observers = new Set<ResizeObserverCallback>();
    vi.stubGlobal("ResizeObserver", class {
      constructor(private callback: ResizeObserverCallback) { observers.add(callback); }
      observe() {} disconnect() { observers.delete(this.callback); } unobserve() {}
    });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => ({ x: 0, y: 0, left: 0, top: 0, right: width, bottom: 800, width, height: 800, toJSON: () => ({}) }));
    const pointer = (type: string, x: number) => { const event = new Event(type, { bubbles: true }); Object.defineProperties(event, { button: { value: 0 }, clientX: { value: x } }); return event; };
    await render();
    const split = host.querySelector<HTMLElement>('[data-vui="split-workspace"]')!;
    const handle = host.querySelector<HTMLElement>('[role="separator"]')!;
    await act(async () => { handle.dispatchEvent(pointer("pointerdown", 0)); window.dispatchEvent(pointer("pointermove", 400)); await new Promise(resolve => setTimeout(resolve, 40)); window.dispatchEvent(pointer("pointerup", 400)); });
    expect(split.style.getPropertyValue("--pane-w-sidebar")).toBe("760px");
    expect(handle.getAttribute("aria-valuemax")).toBe("834");
    await act(async () => { handle.dispatchEvent(pointer("pointerdown", 0)); window.dispatchEvent(pointer("pointermove", 400)); await new Promise(resolve => setTimeout(resolve, 40)); window.dispatchEvent(pointer("pointerup", 400)); });
    expect(split.style.getPropertyValue("--pane-w-sidebar")).toBe("834px");
    width = 900;
    await act(async () => { for (const callback of [...observers]) callback([], {} as ResizeObserver); });
    expect(handle.getAttribute("aria-valuemax")).toBe("534");
    expect(split.style.getPropertyValue("--pane-w-sidebar")).toBe("534px");
    expect(JSON.parse(window.localStorage.getItem("vibelution.pane-layouts.v1") ?? "{}")["launcher-assistant-browser"].sidebar).toBe(534);
  });
  it("preserves complete addresses and rejects invalid or oversized URLs", () => {
    expect(safeBrowserUrl(page.url)).toBe(page.url);
    expect(browserState(initial).pages[0].url).toBe(page.url);
    expect(browserState({ ...initial, pages: [{ ...page, url: "" }] }).pages[0].url).toBe("");
    const prefix = "https://example.com/";
    const limit = prefix + "a".repeat(8192 - prefix.length);
    expect(safeBrowserUrl(limit)).toBe(limit);
    expect(() => safeBrowserUrl(limit + "a")).toThrow();
    expect(() => safeBrowserUrl(prefix + "中".repeat(1000))).toThrow();
    expect(() => browserState({ ...initial, pages: [{ ...page, url: limit + "a" }] })).toThrow();
    expect(() => browserState({ ...initial, pages: [{ ...page, url: "https://name:password@example.com/" }] })).toThrow();
    expect(() => safeBrowserUrl("file:///secret")).toThrow();
    expect(() => safeBrowserUrl("https://name:password@example.com/")).toThrow();
    expect(() => browserState({ ...initial, activePageId: "missing" })).toThrow();
  });
  it("displays and navigates with the complete address", async () => {
    await render();
    const input = host.querySelector<HTMLInputElement>('input[aria-label="网页地址"]')!;
    expect(input.value).toBe(page.url);
    await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "navigate" && payload.url === page.url)).toBe(true);
  });
  it("waits for takeover and clears native bounds when switching to chat", async () => {
    let resolve!: (value: unknown) => void;
    invoke.mockImplementation((payload: { operation: string }) => payload.operation === "takeover" ? new Promise(r => { resolve = r; }) : Promise.resolve(initial));
    await render();
    await act(async () => button("接手").click());
    expect(button("等待当前操作").disabled).toBe(true);
    expect(invoke.mock.calls.filter(([payload]) => payload.operation === "takeover")).toHaveLength(1);
    await act(async () => resolve({ ...initial, takeover: true }));
    expect(button("交给助理并继续")).toBeTruthy();
    await act(async () => { window.innerWidth = 600; window.dispatchEvent(new Event("resize")); });
    await act(async () => button("对话").click());
    expect(host.textContent).toContain("原生对话");
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "bounds" && payload.bounds === null)).toBe(true);
  });
  it("continues the click-time task only after an explicit successful handoff", async () => {
    const intent = { requestId: "frozen" }; control.capture.mockReturnValue(intent);
    let resolve!: (value: unknown) => void;
    invoke.mockImplementation((payload: { operation: string }) => payload.operation === "resume"
      ? new Promise(done => { resolve = done; }) : Promise.resolve({ ...initial, takeover: true }));
    await render(); expect(control.capture).not.toHaveBeenCalled(); expect(control.complete).not.toHaveBeenCalled();
    await act(async () => button("交给助理并继续").click());
    expect(control.capture).toHaveBeenCalledOnce(); expect(control.complete).not.toHaveBeenCalled();
    await act(async () => resolve(initial));
    expect(control.complete).toHaveBeenCalledWith(intent, expect.any(Function));
    expect(control.complete).toHaveBeenCalledOnce();
  });
  it("does not continue if resume fails or control is still held by the user", async () => {
    control.capture.mockReturnValue({ requestId: "frozen" });
    invoke.mockResolvedValue({ ...initial, takeover: true });
    await render(); await act(async () => button("交给助理并继续").click());
    expect(control.complete).not.toHaveBeenCalled();
    invoke.mockRejectedValue(new Error("failed"));
    await act(async () => button("交给助理并继续").click());
    expect(control.complete).not.toHaveBeenCalled();
  });
  it("shows the page again when an explicit open arrives while narrow chat is selected", async () => {
    let show: (() => void) | undefined;
    window.vibelutionLauncherBrowser!.onShow = listener => { show = listener; return () => {}; };
    window.innerWidth = 600;
    await render();
    await act(async () => button("对话").click());
    expect(host.textContent).toContain("原生对话");
    await act(async () => show?.());
    expect(host.querySelector('[aria-label="浏览器"]')).toBeTruthy();
    expect(host.querySelector('[aria-label="网页地址"]')).toBeTruthy();
  });
  it("collapses without closing pages or remounting the conversation and restores its bounds", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ x: 40, y: 50, left: 40, top: 50, right: 440, bottom: 350, width: 400, height: 300, toJSON: () => ({}) });
    await render();
    const draft = host.querySelector<HTMLInputElement>('input[aria-label="对话草稿"]')!;
    draft.value = "未发送的草稿";
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); });
    await act(async () => { button("收起网页").click(); await new Promise(resolve => setTimeout(resolve, 40)); });
    const split = host.querySelector('[data-vui="split-workspace"]')!;
    expect(split.className).toContain('[&>[data-vui=split-sidebar]]:!w-full');
    expect(split.className).toContain('[&>[data-vui=split-main]]:!hidden');
    expect(host.querySelector('input[aria-label="对话草稿"]')).toBe(draft);
    expect(draft.value).toBe("未发送的草稿");
    expect(invoke.mock.calls.at(-1)?.[0]).toEqual({ operation: "bounds", bounds: null });
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "close")).toBe(false);
    await act(async () => { button("打开网页").click(); await new Promise(resolve => setTimeout(resolve, 40)); });
    expect(split.className).not.toContain('[&>[data-vui=split-main]]:!hidden');
    expect(host.querySelector('input[aria-label="对话草稿"]')).toBe(draft);
    expect(host.querySelector<HTMLInputElement>('input[aria-label="网页地址"]')?.value).toBe(page.url);
    expect(invoke.mock.calls.at(-1)?.[0]).toMatchObject({ operation: "bounds", bounds: { x: 40, y: 50, width: 400, height: 300 } });
  });
  it("reopens a collapsed panel when the host explicitly requests it", async () => {
    let show: (() => void) | undefined;
    window.vibelutionLauncherBrowser!.onShow = listener => { show = listener; return () => {}; };
    await render();
    await act(async () => button("收起网页").click());
    expect(button("打开网页")).toBeTruthy();
    await act(async () => show?.());
    expect(host.querySelector('button[aria-label="打开网页"]')).toBeNull();
    expect(host.querySelector('[data-vui="split-workspace"]')?.className).not.toContain('[&>[data-vui=split-main]]:!hidden');
  });
  it("keeps valid bounds when the host document is occluded", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ x: 40, y: 50, left: 40, top: 50, right: 440, bottom: 350, width: 400, height: 300, toJSON: () => ({}) });
    await render();
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await new Promise(resolve => setTimeout(resolve, 40)); });
    expect(invoke.mock.calls.at(-1)?.[0]).toMatchObject({ operation: "bounds", bounds: { x: 40, y: 50, width: 400, height: 300 } });
  });
  it("publishes hidden document bounds and clears them without animation frames", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 123);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ x: 40, y: 50, left: 40, top: 50, right: 440, bottom: 350, width: 400, height: 300, toJSON: () => ({}) });
    await render();
    expect(invoke.mock.calls.at(-1)?.[0]).toEqual({ operation: "bounds", bounds: { x: 40, y: 50, width: 400, height: 300 } });
    const dialog = document.createElement("div"); dialog.setAttribute("data-vui", "dialog-overlay");
    await act(async () => { document.body.appendChild(dialog); await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(invoke.mock.calls.at(-1)?.[0]).toEqual({ operation: "bounds", bounds: null });
    await act(async () => { dialog.remove(); await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(invoke.mock.calls.at(-1)?.[0]).toEqual({ operation: "bounds", bounds: { x: 40, y: 50, width: 400, height: 300 } });
    await act(async () => button("收起网页").click());
    expect(invoke.mock.calls.at(-1)?.[0]).toEqual({ operation: "bounds", bounds: null });
    invoke.mockClear();
    await act(async () => root.unmount());
    expect(invoke.mock.calls.at(-1)?.[0]).toEqual({ operation: "bounds", bounds: null });
    root = createRoot(host);
  });
  it.each(["dialog-overlay", "popover"])("hides the native page behind a %s and restores its bounds after closing", async overlayKind => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ x: 40, y: 50, left: 40, top: 50, right: 440, bottom: 350, width: 400, height: 300, toJSON: () => ({}) });
    await render();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); });
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "bounds" && payload.bounds?.width === 400)).toBe(true);
    const dialog = document.createElement("div"); dialog.setAttribute("data-vui", overlayKind);
    await act(async () => { document.body.appendChild(dialog); await new Promise(resolve => setTimeout(resolve, 40)); });
    expect(invoke.mock.calls.at(-1)?.[0]).toEqual({ operation: "bounds", bounds: null });
    await act(async () => { dialog.remove(); await new Promise(resolve => setTimeout(resolve, 40)); });
    expect(invoke.mock.calls.at(-1)?.[0]).toMatchObject({ operation: "bounds", bounds: { x: 40, y: 50, width: 400, height: 300 } });
  });
  it("rejects invalid address without invoking navigation", async () => {
    await render();
    const input = host.querySelector<HTMLInputElement>('input[aria-label="网页地址"]')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => { setter.call(input, "javascript:alert(1)"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("http 或 https");
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "navigate")).toBe(false);
  });
});
