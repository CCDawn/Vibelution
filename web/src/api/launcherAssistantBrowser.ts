export type BrowserPage = { id: string; url: string; title: string; loading: boolean; canGoBack: boolean; canGoForward: boolean; loadError?: boolean };
export type BrowserState = { pages: BrowserPage[]; activePageId: string | null; takeover: boolean };
export type BrowserBounds = { x: number; y: number; width: number; height: number };
export type BrowserOperation = { operation: "state" | "takeover" | "resume" } | { operation: "open"; url: string }
  | { operation: "select" | "close" | "back" | "forward" | "reload"; pageId: string }
  | { operation: "navigate"; pageId: string; url: string } | { operation: "bounds"; bounds: BrowserBounds | null };
type Bridge = { invoke: (payload: BrowserOperation) => Promise<unknown>; onChanged: (listener: (state: unknown) => void) => () => void; onShow?: (listener: () => void) => () => void };
declare global { interface Window { vibelutionLauncherBrowser?: Bridge } }
const invalid = () => new Error("浏览器状态暂不可用，请重试。");
export function safeBrowserUrl(value: string): string {
  if (value.length > 8192) throw new Error("网页地址过长。");
  let url: URL;
  try { url = new URL(value); } catch { throw new Error("请输入完整的 http 或 https 网页地址。"); }
  if (!(["http:", "https:"].includes(url.protocol)) || url.username || url.password || url.href.length > 8192) throw new Error("请输入有效的 http 或 https 网页地址。");
  return url.href;
}
export function browserState(value: unknown): BrowserState {
  if (!value || typeof value !== "object") throw invalid();
  const state = value as Record<string, unknown>;
  if (!Array.isArray(state.pages) || state.pages.length > 4 || typeof state.takeover !== "boolean" || !(state.activePageId === null || typeof state.activePageId === "string")) throw invalid();
  const pages = state.pages.map((value): BrowserPage => {
    if (!value || typeof value !== "object") throw invalid();
    const page = value as Record<string, unknown>;
    if (typeof page.id !== "string" || !page.id || typeof page.url !== "string" || typeof page.title !== "string"
      || typeof page.loading !== "boolean" || typeof page.canGoBack !== "boolean" || typeof page.canGoForward !== "boolean"
      || !(page.loadError === undefined || typeof page.loadError === "boolean")) throw invalid();
    if (page.url) { try { safeBrowserUrl(page.url); } catch { throw invalid(); } }
    return { id: page.id, url: page.url, title: page.title, loading: page.loading,
      canGoBack: page.canGoBack, canGoForward: page.canGoForward, loadError: page.loadError as boolean | undefined };
  });
  if (new Set(pages.map(page => page.id)).size !== pages.length || (state.activePageId !== null && !pages.some(page => page.id === state.activePageId))) throw invalid();
  return { pages, activePageId: state.activePageId as string | null, takeover: state.takeover };
}
export function launcherBrowserBridge(): Bridge {
  const bridge = window.vibelutionLauncherBrowser;
  if (!bridge || typeof bridge.invoke !== "function" || typeof bridge.onChanged !== "function") throw invalid();
  return bridge;
}
