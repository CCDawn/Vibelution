import { randomUUID } from "node:crypto";
import type { EventEmitter } from "node:events";
import { WebContentsView, session, type BrowserWindow } from "electron";
import { snapshotScript, targetScript } from "./pageScripts.js";

export type BrowserSource = "operator" | "assistant";
export type BrowserBounds = { x: number; y: number; width: number; height: number };
export type BrowserState = { pages: Array<{ id: string; url: string; title: string; loading: boolean; loadError?: boolean; canGoBack: boolean; canGoForward: boolean }>; activePageId: string | null; takeover: boolean };
export type BrowserSnapshot = { pageId: string; snapshotId: string; url: string; title: string; untrusted: true; text: string; elements: Array<{ ref: string; role: string; name: string }> };
export class AssistantBrowserError extends Error { constructor(public readonly code: string) { super(code); this.name = "AssistantBrowserError"; } }
type NavigationTask = { cancel: () => void };
type Page = { id: string; view: WebContentsView; generation: number; snapshotId: string | null; snapshotUrl: string | null; refs: Set<string>; loadError: boolean; lastNavigationUrl: string | null; activeLoad: NavigationTask | null };
const PARTITION = "persist:vibelution-assistant-browser";
const securedSessions = new WeakSet<object>();
const fail = (code: string): never => { throw new AssistantBrowserError(code); };
function validUrl(input: unknown): string {
  if (typeof input !== "string" || input.length > 8192 || /[\x00-\x1f\x7f]/.test(input)) return fail("BROWSER_URL_INVALID");
  try { const u = new URL(input); if (!["http:", "https:"].includes(u.protocol) || u.username || u.password || u.href.length > 8192) return fail("BROWSER_URL_INVALID"); return u.href; } catch { return fail("BROWSER_URL_INVALID"); }
}
function publicUrl(input: string): string {
  if (!input || input === "about:blank") return "";
  validUrl(input); return input;
}
const EXECUTION_TIMEOUT = Symbol("browser renderer timeout");
async function withExecutionDeadline<T>(task: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([task, new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(EXECUTION_TIMEOUT), 8_000); })]);
  } finally { if (timer !== undefined) clearTimeout(timer); }
}
function bounded(value: unknown, limit: number): string {
  if (typeof value !== "string") return "";
  let result = "";
  for (const part of value) {
    const code = part.charCodeAt(0);
    const safe = part.length === 1 && code >= 0xd800 && code <= 0xdfff ? "\ufffd" : part;
    if (result.length + safe.length > limit) break;
    result += safe;
  }
  return result;
}

/** Owned exclusively by the trusted main process; source must never come from a remote page. */
export class AssistantBrowser {
  private pages = new Map<string, Page>();
  private activePageId: string | null = null;
  private takingOver = false;
  private takeoverPending = false;
  private pendingTakeover: Promise<BrowserState> | null = null;
  private activeActions = 0;
  private actionWaiters: Array<() => void> = [];
  private bounds: BrowserBounds | null = null;
  private host: BrowserWindow | null = null;
  private attached: Page | null = null;
  private disposed = false;
  private readonly updateLayout = () => this.layout();
  constructor(private readonly options: { getHost: () => BrowserWindow | null; onChanged: (state: BrowserState) => void }) {
    const isolatedSession = session.fromPartition(PARTITION);
    if (!securedSessions.has(isolatedSession)) {
      isolatedSession.setPermissionCheckHandler(() => false);
      isolatedSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
      isolatedSession.on("will-download", event => event.preventDefault());
      securedSessions.add(isolatedSession);
    }
  }
  private requireSource(source: BrowserSource): void {
    if (source !== "operator" && source !== "assistant") fail("BROWSER_SOURCE_INVALID");
    if (this.disposed) fail("BROWSER_DISPOSED");
    if (source === "assistant" && (this.takingOver || this.takeoverPending)) fail("BROWSER_TAKEOVER_ACTIVE");
  }
  private beginAction(source: BrowserSource): () => void {
    this.requireSource(source);
    this.activeActions++;
    return () => {
      this.activeActions--;
      if (!this.activeActions) for (const resolve of this.actionWaiters.splice(0)) resolve();
    };
  }
  private getPage(id: string): Page { const p = this.pages.get(id); if (!p || p.view.webContents.isDestroyed()) return fail("BROWSER_PAGE_NOT_FOUND"); return p; }
  private invalidate(p: Page): void { p.generation++; p.snapshotId = null; p.snapshotUrl = null; p.refs.clear(); }
  private forgetDestroyedPage(p: Page): void {
    if (this.pages.get(p.id) !== p) return;
    p.activeLoad?.cancel(); this.invalidate(p); this.pages.delete(p.id);
    if (this.activePageId === p.id) this.activePageId = this.pages.keys().next().value ?? null;
    try { this.layout(); } catch { if (this.attached === p) this.attached = null; }
    this.changed();
  }
  private async closeTimedOutPage(p: Page): Promise<void> {
    const contents = p.view.webContents;
    if (!contents.isDestroyed()) {
      await new Promise<void>(resolve => {
        const destroyed = () => { if (contents.isDestroyed()) { contents.removeListener("destroyed", destroyed); resolve(); } };
        contents.on("destroyed", destroyed);
        try { contents.close({ waitForBeforeUnload: false }); } catch { /* Wait for actual destruction; do not release takeover early. */ }
        destroyed();
      });
    }
    this.forgetDestroyedPage(p);
  }
  private changed(): void { if (!this.disposed) { try { this.options.onChanged(this.getState()); } catch { /* UI observers cannot own browser lifetime. */ } } }
  getState(): BrowserState {
    return { pages: [...this.pages.values()].filter(p => !p.view.webContents.isDestroyed()).map(p => {
      const w = p.view.webContents; return { id: p.id, url: publicUrl(w.getURL()), title: bounded(w.getTitle(), 200), loading: w.isLoading(), loadError: p.loadError, canGoBack: w.navigationHistory.canGoBack(), canGoForward: w.navigationHistory.canGoForward() };
    }), activePageId: this.activePageId, takeover: this.takingOver };
  }
  async open(url: string, source: BrowserSource): Promise<BrowserState> {
    const done = this.beginAction(source); try { const target = validUrl(url); if (this.pages.size >= 4) fail("BROWSER_PAGE_LIMIT");
    const view = new WebContentsView({ webPreferences: { partition: PARTITION, nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, webviewTag: false } });
    const p: Page = { id: randomUUID(), view, generation: 0, snapshotId: null, snapshotUrl: null, refs: new Set(), loadError: false, lastNavigationUrl: null, activeLoad: null }; const w = view.webContents;
    w.setWindowOpenHandler(() => ({ action: "deny" }));
    w.on("will-attach-webview", event => event.preventDefault());
    w.on("will-frame-navigate", event => { try { validUrl(event.url); if (event.isMainFrame) p.activeLoad?.cancel(); } catch { event.preventDefault(); } });
    w.on("will-redirect", event => { try { validUrl(event.url); } catch { event.preventDefault(); } });
    w.on("did-start-navigation", (_event, url, _inPlace, mainFrame) => { if (mainFrame) { this.invalidate(p); p.lastNavigationUrl = url; p.loadError = false; this.changed(); } });
    w.on("did-redirect-navigation", (_event, url, _inPlace, mainFrame) => { if (mainFrame) p.lastNavigationUrl = url; });
    w.on("did-fail-load", (_event, code, _description, url, mainFrame) => { if (mainFrame && code !== -3 && (!p.lastNavigationUrl || p.lastNavigationUrl === url)) { p.loadError = true; this.changed(); } });
    for (const event of ["did-navigate", "did-navigate-in-page", "did-start-loading", "did-stop-loading", "page-title-updated"] as const) (w as EventEmitter).on(event, () => this.changed());
    w.on("destroyed", () => this.forgetDestroyedPage(p));
    this.pages.set(p.id, p); this.activePageId = p.id; this.layout(); this.changed();
    try { await this.load(p, target); } catch { return fail("BROWSER_NAVIGATION_FAILED"); }
    return this.getState(); } finally { done(); }
  }
  async ensure(url: string, source: BrowserSource): Promise<BrowserState> {
    this.requireSource(source); const target = validUrl(url);
    // Match only the current complete URL, never an earlier request or redirect alias.
    const existing = this.getState().pages.find(p => p.url && validUrl(p.url) === target);
    return existing ? this.select(existing.id, source) : this.open(target, source);
  }
  select(id: string, source: BrowserSource): BrowserState { this.requireSource(source); this.getPage(id); this.activePageId = id; this.layout(); this.changed(); return this.getState(); }
  async navigate(id: string, url: string, source: BrowserSource): Promise<BrowserState> { const done = this.beginAction(source); try { const p = this.getPage(id), target = validUrl(url); this.invalidate(p); try { await this.load(p, target); } catch { return fail("BROWSER_NAVIGATION_FAILED"); } return this.getState(); } finally { done(); } }
  private navigateUntilReady(p: Page, startNavigation: () => void | Promise<void>): Promise<void> {
    p.activeLoad?.cancel();
    const token: NavigationTask = { cancel: () => {} }; p.activeLoad = token;
    const w = p.view.webContents, emitter = w as EventEmitter;
    return new Promise<void>((resolve, reject) => {
      let started = false, sameDocument = false, committedUrl: string | null = null, completed = false;
      const finish = (ok: boolean) => {
        if (completed) return; completed = true; clearTimeout(timer);
        emitter.removeListener("did-start-navigation", onStart); emitter.removeListener("did-navigate", onCommit);
        emitter.removeListener("did-navigate-in-page", onInPage); emitter.removeListener("dom-ready", onDomReady);
        emitter.removeListener("did-fail-load", onFailure); emitter.removeListener("destroyed", onDestroyed);
        if (p.activeLoad === token) p.activeLoad = null;
        if (ok) resolve(); else reject(new AssistantBrowserError("BROWSER_NAVIGATION_FAILED"));
      };
      const ready = () => {
        if (p.activeLoad !== token || w.isDestroyed()) return false;
        try { return !!publicUrl(w.getURL()); } catch { return false; }
      };
      const onStart = (_event: unknown, _url: string, same: boolean, main: boolean) => {
        if (!main) return;
        if (p.activeLoad !== token) { finish(false); return; }
        if (!started) { started = true; sameDocument = same; return; }
        if (!same || sameDocument) finish(false);
      };
      const onCommit = (_event: unknown, url: string) => { if (started && p.activeLoad === token) committedUrl = url; };
      const onInPage = (_event: unknown, url: string, main: boolean) => {
        if (!started || !main || w.getURL() !== url) return;
        if (sameDocument) finish(ready()); else if (committedUrl !== null) committedUrl = url;
      };
      const onDomReady = () => { try { if (started && committedUrl !== null && w.getURL() === committedUrl) finish(ready()); } catch { finish(false); } };
      const onFailure = (_event: unknown, _code: number, _description: string, url: string, main: boolean) => { if (started && main && (!p.lastNavigationUrl || p.lastNavigationUrl === url)) finish(false); };
      const onDestroyed = () => finish(false);
      const timer = setTimeout(() => {
        const ownsLoad = p.activeLoad === token && !w.isDestroyed();
        if (ownsLoad) p.loadError = true;
        finish(false);
        if (ownsLoad) { try { w.stop(); } catch { /* already closed */ } this.changed(); }
      }, 15_000);
      token.cancel = () => finish(false);
      emitter.on("did-start-navigation", onStart); emitter.on("did-navigate", onCommit);
      emitter.on("did-navigate-in-page", onInPage); emitter.on("dom-ready", onDomReady);
      emitter.on("did-fail-load", onFailure); emitter.on("destroyed", onDestroyed);
      try {
        const completion = startNavigation();
        // Electron may reject after DOM-ready or after another navigation supersedes it.
        // Always consume that outcome, and ignore it after this operation has settled.
        if (completion) void completion.then(() => finish(ready()), error => {
          if (completed) return;
          const code = error && typeof error === "object" && "code" in error ? (error as { code?: unknown }).code : undefined;
          if (p.activeLoad === token && code !== "ERR_ABORTED" && code !== -3) { p.loadError = true; this.changed(); }
          finish(false);
        });
      } catch { finish(false); }
    });
  }
  private load(p: Page, target: string): Promise<void> {
    return this.navigateUntilReady(p, () => p.view.webContents.loadURL(target));
  }
  async snapshot(id: string): Promise<BrowserSnapshot> {
    const done = this.beginAction("assistant"); try {
    const p = this.getPage(id); if (!publicUrl(p.view.webContents.getURL())) return fail("BROWSER_URL_INVALID"); this.invalidate(p); const generation = p.generation, snapshotId = randomUUID();
    let data: unknown; try { data = await withExecutionDeadline(p.view.webContents.executeJavaScriptInIsolatedWorld(947, [{ code: snapshotScript(snapshotId) }])); }
    catch { if (this.pages.get(id) === p && p.generation === generation) this.invalidate(p); return fail("BROWSER_SNAPSHOT_FAILED"); }
    if (!this.pages.has(id) || p.generation !== generation) return fail("BROWSER_SNAPSHOT_STALE");
    if (!data || typeof data !== "object") return fail("BROWSER_SNAPSHOT_FAILED");
    const raw = data as { text?: unknown; elements?: unknown; viewportUnavailable?: unknown }; if (raw.viewportUnavailable === true) return fail("BROWSER_PAGE_NOT_VISIBLE"); if (!Array.isArray(raw.elements)) return fail("BROWSER_SNAPSHOT_FAILED");
    const elements = raw.elements.slice(0, 80).map((item: unknown) => { const e = item && typeof item === "object" ? item as Record<string, unknown> : {}; return { ref: bounded(e.ref, 3), role: bounded(e.role, 40), name: bounded(e.name, 160) }; }).filter(e => /^[1-9]\d{0,2}$/.test(e.ref));
    const result: BrowserSnapshot = { pageId: id, snapshotId, url: publicUrl(p.view.webContents.getURL()), title: bounded(p.view.webContents.getTitle(), 200), untrusted: true, text: bounded(raw.text, 8000), elements };
    // JSON encoding can expand control characters substantially. Leave room for the caller envelope.
    while (Buffer.byteLength(JSON.stringify(result), "utf8") > 120 * 1024 && result.elements.length) result.elements.pop();
    p.snapshotId = snapshotId; p.snapshotUrl = result.url; p.refs = new Set(result.elements.map(e => e.ref));
    return result; } finally { done(); }
  }
  private async target(id: string, snapshotId: string, ref: string, source: BrowserSource, operation: "click" | "fill" | "preview", value = ""): Promise<{ p: Page; result: Record<string, unknown> }> {
    this.requireSource(source); const p = this.getPage(id); if (p.snapshotId !== snapshotId || !p.refs.has(ref) || !/^[1-9]\d{0,2}$/.test(ref)) return fail("BROWSER_SNAPSHOT_STALE");
    if (this.activePageId !== id || !this.attached) return fail("BROWSER_PAGE_NOT_VISIBLE");
    const currentUrl = publicUrl(p.view.webContents.getURL()); if (!currentUrl) return fail("BROWSER_URL_INVALID");
    if (currentUrl !== p.snapshotUrl) return fail("BROWSER_SNAPSHOT_STALE");
    const generation = p.generation; let result: unknown;
    try { result = await withExecutionDeadline(p.view.webContents.executeJavaScriptInIsolatedWorld(947, [{ code: targetScript(ref, operation, value, snapshotId) }])); }
    catch (error) {
      if (this.pages.get(id) === p && p.generation === generation) this.invalidate(p);
      if (error === EXECUTION_TIMEOUT && operation !== "preview") await this.closeTimedOutPage(p);
      return fail(operation === "preview" ? "BROWSER_TARGET_UNAVAILABLE" : "BROWSER_ACTION_OUTCOME_UNKNOWN");
    }
    if (!this.pages.has(id) || p.generation !== generation || p.snapshotId !== snapshotId || this.activePageId !== id || this.attached !== p || p.view.webContents.getURL() !== currentUrl) return fail(operation === "preview" ? "BROWSER_SNAPSHOT_STALE" : "BROWSER_ACTION_OUTCOME_UNKNOWN");
    if (!result || typeof result !== "object") return fail("BROWSER_TARGET_UNAVAILABLE");
    return { p, result: result as Record<string, unknown> };
  }
  async previewInteraction(id: string, snapshotId: string, ref: string): Promise<{ pageId: string; snapshotId: string; elementRef: string; url: string; title: string; name: string; role: string }> {
    const { p, result } = await this.target(id, snapshotId, ref, "operator", "preview");
    if (typeof result.name !== "string" || typeof result.role !== "string") return fail("BROWSER_TARGET_UNAVAILABLE");
    return { pageId: id, snapshotId, elementRef: ref, url: publicUrl(p.view.webContents.getURL()), title: bounded(p.view.webContents.getTitle(), 200), name: bounded(result.name, 160), role: bounded(result.role, 40) };
  }
  async click(id: string, snapshotId: string, ref: string, source: BrowserSource): Promise<void> {
    const done = this.beginAction(source); try {
      const { p, result } = await this.target(id, snapshotId, ref, source, "click");
      if (result.invalidUrl === true) return fail("BROWSER_URL_INVALID");
      if (typeof result.navigateUrl === "string") {
        const url = validUrl(result.navigateUrl); this.invalidate(p);
        try { await this.load(p, url); } catch { /* Once navigation begins, its outcome requires a fresh snapshot. */ }
        return fail("BROWSER_ACTION_OUTCOME_UNKNOWN");
      }
      if (result.clicked !== true) fail("BROWSER_ACTION_OUTCOME_UNKNOWN");
    } finally { done(); }
  }
  async fill(id: string, snapshotId: string, ref: string, value: string, source: BrowserSource): Promise<void> {
    const done = this.beginAction(source); try {
      if (typeof value !== "string" || value.length > 4000) fail("BROWSER_VALUE_INVALID");
      const { result } = await this.target(id, snapshotId, ref, source, "fill", value);
      if (result.filled !== true) fail("BROWSER_ACTION_OUTCOME_UNKNOWN");
    } finally { done(); }
  }
  scroll(id: string, direction: "up" | "down", source: BrowserSource): void {
    this.requireSource(source); const p = this.getPage(id); if (direction !== "up" && direction !== "down") fail("BROWSER_DIRECTION_INVALID");
    if (this.attached !== p || !this.bounds) fail("BROWSER_PAGE_NOT_VISIBLE");
    p.view.webContents.sendInputEvent({ type: "mouseWheel", x: Math.floor(p.view.getBounds().width / 2), y: Math.floor(p.view.getBounds().height / 2), deltaX: 0, deltaY: direction === "down" ? -500 : 500, canScroll: true });
  }
  private async history(id: string, source: BrowserSource, operation: "back" | "forward" | "reload"): Promise<void> {
    const done = this.beginAction(source);
    try {
      const p = this.getPage(id), w = p.view.webContents;
      if ((operation === "back" && !w.navigationHistory.canGoBack()) || (operation === "forward" && !w.navigationHistory.canGoForward())) return;
      this.invalidate(p);
      await this.navigateUntilReady(p, () => {
        if (operation === "back") w.navigationHistory.goBack(); else if (operation === "forward") w.navigationHistory.goForward(); else w.reload();
      });
    } finally { done(); }
  }
  back(id: string, source: BrowserSource): Promise<void> { return this.history(id, source, "back"); }
  forward(id: string, source: BrowserSource): Promise<void> { return this.history(id, source, "forward"); }
  reload(id: string, source: BrowserSource): Promise<void> { return this.history(id, source, "reload"); }
  close(id: string, source: BrowserSource): BrowserState { this.requireSource(source); const p = this.getPage(id); p.activeLoad?.cancel(); this.invalidate(p); this.pages.delete(id); if (this.activePageId === id) this.activePageId = this.pages.keys().next().value ?? null; this.layout(); p.view.webContents.close(); this.changed(); return this.getState(); }
  requestTakeover(source: BrowserSource): Promise<BrowserState> {
    if (source !== "operator") return Promise.reject(new AssistantBrowserError("BROWSER_SOURCE_FORBIDDEN"));
    try { this.requireSource(source); } catch (error) { return Promise.reject(error); }
    if (this.pendingTakeover) return this.pendingTakeover;
    this.takeoverPending = true;
    const settled = this.activeActions ? new Promise<void>(resolve => this.actionWaiters.push(resolve)) : Promise.resolve();
    this.pendingTakeover = settled.then(async () => {
      await Promise.resolve(); // Allow completed action promises to settle before publishing takeover.
      if (this.disposed) return fail("BROWSER_DISPOSED");
      this.takingOver = true; this.takeoverPending = false; this.changed(); return this.getState();
    }).finally(() => { this.takeoverPending = false; this.pendingTakeover = null; });
    return this.pendingTakeover;
  }
  takeover(source: BrowserSource): BrowserState { this.requireSource(source); if (source !== "operator") return fail("BROWSER_SOURCE_FORBIDDEN"); this.takingOver = true; this.changed(); return this.getState(); }
  resume(source: BrowserSource): BrowserState { if (source !== "operator") return fail("BROWSER_SOURCE_FORBIDDEN"); this.requireSource(source); if (this.takeoverPending) return fail("BROWSER_TAKEOVER_ACTIVE"); this.takingOver = false; this.changed(); return this.getState(); }
  setBounds(bounds: BrowserBounds | null): void {
    if (bounds && (!Number.isSafeInteger(bounds.x) || !Number.isSafeInteger(bounds.y) || !Number.isSafeInteger(bounds.width) || !Number.isSafeInteger(bounds.height) || bounds.x < 0 || bounds.y < 0 || bounds.width <= 0 || bounds.height <= 0)) fail("BROWSER_BOUNDS_INVALID");
    this.bounds = bounds ? { ...bounds } : null; this.layout();
  }
  private layout(): void {
    const nextHost = this.disposed ? null : this.options.getHost();
    if (this.host !== nextHost) {
      if (this.host && !this.host.isDestroyed()) { if (this.attached) this.host.contentView.removeChildView(this.attached.view); for (const e of ["resize", "show", "hide", "minimize", "restore", "closed"] as const) (this.host as EventEmitter).removeListener(e, this.updateLayout); }
      this.attached = null; this.host = nextHost && !nextHost.isDestroyed() ? nextHost : null;
      if (this.host) for (const e of ["resize", "show", "hide", "minimize", "restore", "closed"] as const) (this.host as EventEmitter).on(e, this.updateLayout);
    }
    const host = this.host; const p = this.activePageId ? this.pages.get(this.activePageId) ?? null : null;
    const size = host && !host.isDestroyed() ? host.getContentSize() : [0, 0]; const b = this.bounds;
    const width = b ? Math.min(b.width, size[0] - b.x) : 0, height = b ? Math.min(b.height, size[1] - b.y) : 0;
    const wanted = host && !host.isDestroyed() && host.isVisible() && !host.isMinimized() && b && width > 0 && height > 0 ? p : null;
    if (this.attached !== wanted) { if (this.attached && host && !host.isDestroyed()) host.contentView.removeChildView(this.attached.view); this.attached = wanted; if (wanted && host) host.contentView.addChildView(wanted.view); }
    if (wanted && b) wanted.view.setBounds({ x: b.x, y: b.y, width, height });
  }
  dispose(): void { if (this.disposed) return; this.disposed = true; this.layout(); for (const p of this.pages.values()) { this.invalidate(p); if (!p.view.webContents.isDestroyed()) p.view.webContents.close(); } this.pages.clear(); this.activePageId = null; }
}
