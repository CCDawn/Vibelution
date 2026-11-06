import type { AssistantBrowser, BrowserBounds, BrowserState } from "./assistantBrowser.js";
import { browserControlResult, browserError, browserErrorCodes, browserUrl, closed, parseBrowserClaim, uuid, type BrowserMainControlRequest } from "./browserControlProtocol.js";

type OperatorCommand = { operation: "state" | "takeover" | "resume" } | { operation: "open"; url: string }
  | { operation: "select" | "close" | "back" | "forward" | "reload"; pageId: string }
  | { operation: "navigate"; pageId: string; url: string } | { operation: "bounds"; bounds: BrowserBounds | null };
export function parseOperatorBrowserCommand(payload: unknown): OperatorCommand {
  const fail = (): never => { throw new Error("BROWSER_SOURCE_INVALID"); };
  if (!closed(payload, ["operation"], ["pageId", "url", "bounds"]) || typeof payload.operation !== "string") return fail();
  const op = payload.operation;
  const keys = op === "open" ? ["url"] : op === "navigate" ? ["pageId", "url"] : ["select", "close", "back", "forward", "reload"].includes(op) ? ["pageId"] : op === "bounds" ? ["bounds"] : [];
  if (!["state", "open", "select", "navigate", "back", "forward", "reload", "close", "takeover", "resume", "bounds"].includes(op) || !closed(payload, ["operation", ...keys])
    || ("pageId" in payload && !uuid(payload.pageId)) || ("url" in payload && !browserUrl(payload.url))) return fail();
  if (op === "bounds" && payload.bounds !== null) {
    const b = payload.bounds;
    if (!closed(b, ["x", "y", "width", "height"]) || ![b.x, b.y, b.width, b.height].every(x => typeof x === "number" && Number.isSafeInteger(x))
      || (b.x as number) < 0 || (b.y as number) < 0 || (b.width as number) <= 0 || (b.height as number) <= 0) return fail();
  }
  return { ...payload } as OperatorCommand;
}
export async function invokeOperatorBrowser(browser: AssistantBrowser, payload: unknown): Promise<BrowserState> {
  const p = parseOperatorBrowserCommand(payload);
  switch (p.operation) {
    case "state": return browser.getState();
    case "open": return browser.open(p.url, "operator");
    case "select": return browser.select(p.pageId, "operator");
    case "navigate": return browser.navigate(p.pageId, p.url, "operator");
    case "close": return browser.close(p.pageId, "operator");
    case "takeover": return browser.requestTakeover("operator");
    case "resume": return browser.resume("operator");
    case "bounds": browser.setBounds(p.bounds); return browser.getState();
    case "back": await browser.back(p.pageId, "operator"); return browser.getState();
    case "forward": await browser.forward(p.pageId, "operator"); return browser.getState();
    case "reload": await browser.reload(p.pageId, "operator"); return browser.getState();
  }
}
function errorCode(error: unknown): string {
  const code = error && typeof error === "object" ? Object.getOwnPropertyDescriptor(error, "code")?.value : undefined;
  return typeof code === "string" && browserErrorCodes.includes(code) ? code : "BROWSER_ACTION_OUTCOME_UNKNOWN";
}
async function abortable<T>(task: Promise<T>, signal: AbortSignal | undefined, aborted: () => T): Promise<T> {
  if (!signal) return task;
  if (signal.aborted) { void task.catch(() => {}); return aborted(); }
  let onAbort: () => void = () => {};
  const stop = new Promise<T>(resolve => { onAbort = () => resolve(aborted()); signal.addEventListener("abort", onAbort, { once: true }); });
  try { return await Promise.race([task, stop]); } finally { signal.removeEventListener("abort", onAbort); }
}
export function createBrowserMainControl(options: { browser: () => AssistantBrowser | null; ensureWorkspace: () => Promise<void> }): (request: BrowserMainControlRequest, signal?: AbortSignal) => Promise<Record<string, unknown>> {
  return async (input, signal) => {
    const request = parseBrowserClaim(input);
    const unavailable = () => browserError(request, "BROWSER_UNAVAILABLE");
    const unknown = () => browserError(request, "BROWSER_ACTION_OUTCOME_UNKNOWN");
    if (signal?.aborted) return unavailable();
    if (["browser_open", "browser_ensure", "browser_select", "browser_show"].includes(request.action)) {
      try { await abortable(options.ensureWorkspace(), signal, () => undefined); } catch { return unavailable(); }
      if (signal?.aborted) return unavailable();
    }
    const browser = options.browser();
    if (!browser) return unavailable();
    const run = async (): Promise<Record<string, unknown>> => {
      try {
        if (request.action === "browser_read") {
          const result = { schemaVersion: 1, operation: "read", code: "ok", snapshot: await browser.snapshot(request.pageId) };
          return browserControlResult(request, result);
        }
        let state: BrowserState;
        switch (request.action) {
          case "browser_state": state = browser.getState(); break;
          case "browser_show": state = browser.getState(); break;
          case "browser_open": state = await browser.open(request.url, "assistant"); break;
          case "browser_ensure": state = await browser.ensure(request.url, "assistant"); break;
          case "browser_select": state = browser.select(request.pageId, "assistant"); break;
          case "browser_navigate": state = await browser.navigate(request.pageId, request.url, "assistant"); break;
          case "browser_back": await browser.back(request.pageId, "assistant"); state = browser.getState(); break;
          case "browser_forward": await browser.forward(request.pageId, "assistant"); state = browser.getState(); break;
          case "browser_reload": await browser.reload(request.pageId, "assistant"); state = browser.getState(); break;
          case "browser_scroll": browser.scroll(request.pageId, request.direction, "assistant"); state = browser.getState(); break;
          case "browser_interact": {
            if (browser.getState().takeover) return browserError(request, "BROWSER_TAKEOVER_ACTIVE");
            const target = await browser.previewInteraction(request.pageId, request.snapshotId, request.elementRef);
            if (signal?.aborted) return unavailable();
            if (target.pageId !== request.pageId || target.snapshotId !== request.snapshotId || target.elementRef !== request.elementRef || target.url !== request.url || target.name !== request.elementName) return browserError(request, "BROWSER_TARGET_UNAVAILABLE");
            if (request.operation === "click") await browser.click(request.pageId, request.snapshotId, request.elementRef, "assistant");
            else await browser.fill(request.pageId, request.snapshotId, request.elementRef, request.value, "assistant");
            state = browser.getState(); break;
          }
        }
        return browserControlResult(request, { schemaVersion: 1, operation: request.action.slice(8), code: "ok", state });
      } catch (error) { return browserError(request, errorCode(error)); }
    };
    return abortable(run(), signal, unknown);
  };
}
