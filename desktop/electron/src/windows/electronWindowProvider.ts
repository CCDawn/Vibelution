import type { DesktopPaths } from "../paths.js";
import { isLauncherAppUrl, launcherAppOriginFor } from "../protocol/launcherAppProtocol.js";
import { assertLocalHttpUrl } from "../security/urlPolicy.js";
import { closedWindowState, type ElectronWindowRole, type ManagedWindowState } from "./windowProviderTypes.js";

type ElectronWindowEventListener = (...args: unknown[]) => void;

export type ElectronWindowOpenRequest = {
  url: string;
};

export type ElectronWindowOpenDecision = { action: "deny" } | { action: "allow" };

export type ElectronWindowOpenHandler = (details: ElectronWindowOpenRequest) => ElectronWindowOpenDecision;

export type ElectronWindowLike = {
  id: number;
  focus(): void;
  show(): void;
  hide(): void;
  close(): void;
  destroy(): void;
  loadURL(url: string): Promise<void>;
  isDestroyed(): boolean;
  isFocused(): boolean;
  isMinimized?(): boolean;
  restore?(): void;
  on(event: string, listener: ElectronWindowEventListener): unknown;
  setTitle?(title: string): void;
  setOverlayIcon?(icon: unknown, description: string): void;
  flashFrame?(flag: boolean): void;
  webContents: {
    getOSProcessId(): number;
    getURL(): string;
    on(event: string, listener: ElectronWindowEventListener): unknown;
    setWindowOpenHandler?(handler: ElectronWindowOpenHandler): void;
    send?(channel: string, payload: unknown): void;
  };
};

export type WorkbenchAttentionOptions = {
  unreadCount: number;
  overlayIcon?: unknown;
  description?: string;
  flash?: boolean;
};

export type ElectronWindowCreateOptions = {
  title?: string;
};

export type ElectronWindowFactory = (
  url: string,
  paths: DesktopPaths,
  options?: ElectronWindowCreateOptions
) => ElectronWindowLike;

export type ElectronWindowProviderOptions = {
  createLauncherWindow?: ElectronWindowFactory;
  createWorkbenchWindow?: ElectronWindowFactory;
  listLauncherWindows?: (launcherOrigin: string) => ElectronWindowLike[];
  listWorkbenchWindows?: (workbenchOrigin: string) => ElectronWindowLike[];
  reportState?: (state: ManagedWindowState) => void | Promise<void>;
  shouldInterceptLauncherClose?: () => boolean;
  shouldInterceptWorkbenchClose?: () => boolean;
  onWorkbenchCloseRequest?: () => void | Promise<void>;
  onWorkbenchClosed?: () => void | Promise<void>;
  onWorkbenchFocusAttentionClear?: () => void;
  onOsSessionEnd?: (event: "query-session-end" | "session-end", role: ElectronWindowRole) => void;
  hungCloseDestroyAfterMs?: number;
};

export const DEFAULT_HUNG_CLOSE_DESTROY_AFTER_MS = 500;

export function presentElectronWindow(window: ElectronWindowLike): void {
  if (typeof window.isMinimized === "function" && window.isMinimized() && typeof window.restore === "function") {
    window.restore();
  }
  window.show();
  window.focus();
}

function waitForWindowClosed(
  window: ElectronWindowLike,
  timeoutMs: number
): Promise<"closed" | "timeout"> {
  if (window.isDestroyed()) {
    return Promise.resolve("closed");
  }
  return new Promise((resolve) => {
    let settled = false;
    const finish = (reason: "closed" | "timeout") => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(reason);
    };
    const timer = setTimeout(() => finish("timeout"), Math.max(0, timeoutMs));
    window.on("closed", () => {
      clearTimeout(timer);
      finish("closed");
    });
  });
}

type InstanceWorkbenchEntry = {
  instanceId: string;
  url: string;
  title: string;
  window: ElectronWindowLike;
  readyUrl: string | null;
};

export class ElectronWindowProvider {
  private launcherWindow: ElectronWindowLike | null = null;
  private workbenchWindow: ElectronWindowLike | null = null;
  private readonly instanceWindows = new Map<string, InstanceWorkbenchEntry>();
  private readonly createLauncherWindow: ElectronWindowFactory;
  private readonly createWorkbenchWindow: ElectronWindowFactory;
  private readonly reportState: (state: ManagedWindowState) => void | Promise<void>;
  private readonly shouldInterceptLauncherClose: () => boolean;
  private readonly shouldInterceptWorkbenchClose: () => boolean;
  private readonly onWorkbenchCloseRequest: () => void | Promise<void>;
  private readonly onWorkbenchClosed: () => void | Promise<void>;
  private readonly onWorkbenchFocusAttentionClear: () => void;
  private readonly onOsSessionEnd: (event: "query-session-end" | "session-end", role: ElectronWindowRole) => void;
  private workbenchUrl: string;
  private workbenchReadyUrl: string | null = null;
  private workbenchNavigation: Promise<ManagedWindowState> | null = null;
  private workbenchCloseAuthorized = false;
  private workbenchCloseInFlight = false;
  private launcherOpen: Promise<ManagedWindowState> | null = null;
  private readonly attachedWindows = new Set<ElectronWindowLike>();
  private readonly listLauncherWindows: (launcherOrigin: string) => ElectronWindowLike[];
  private readonly listWorkbenchWindows: (workbenchOrigin: string) => ElectronWindowLike[];
  private readonly hungCloseDestroyAfterMs: number;

  constructor(
    private readonly paths: DesktopPaths,
    private readonly launcherUrl: string,
    workbenchUrl: string,
    options: ElectronWindowProviderOptions = {}
  ) {
    this.workbenchUrl = workbenchUrl;
    this.createLauncherWindow = options.createLauncherWindow ?? missingWindowFactory("launcher");
    this.createWorkbenchWindow = options.createWorkbenchWindow ?? missingWindowFactory("workbench");
    this.listLauncherWindows = options.listLauncherWindows ?? (() => []);
    this.listWorkbenchWindows = options.listWorkbenchWindows ?? (() => []);
    this.reportState = options.reportState ?? (() => undefined);
    this.shouldInterceptLauncherClose = options.shouldInterceptLauncherClose ?? (() => false);
    this.shouldInterceptWorkbenchClose = options.shouldInterceptWorkbenchClose ?? (() => false);
    this.onWorkbenchCloseRequest = options.onWorkbenchCloseRequest ?? (() => undefined);
    this.onWorkbenchClosed = options.onWorkbenchClosed ?? (() => undefined);
    this.onWorkbenchFocusAttentionClear = options.onWorkbenchFocusAttentionClear ?? (() => undefined);
    this.onOsSessionEnd = options.onOsSessionEnd ?? (() => undefined);
    this.hungCloseDestroyAfterMs =
      typeof options.hungCloseDestroyAfterMs === "number" && Number.isFinite(options.hungCloseDestroyAfterMs)
        ? Math.max(0, options.hungCloseDestroyAfterMs)
        : DEFAULT_HUNG_CLOSE_DESTROY_AFTER_MS;
  }

  async openLauncher(): Promise<ManagedWindowState> {
    if (this.launcherOpen) {
      return this.launcherOpen;
    }
    const pending = this.presentLauncher();
    this.launcherOpen = pending;
    try {
      return await pending;
    } finally {
      if (this.launcherOpen === pending) {
        this.launcherOpen = null;
      }
    }
  }

  private async presentLauncher(): Promise<ManagedWindowState> {
    const launcherOrigin = launcherAppOriginFor(this.launcherUrl);
    const safeUrl = launcherWindowUrl(this.launcherUrl);
    const existing = this.listLauncherWindows(launcherOrigin).filter((window) => !window.isDestroyed());
    if (this.launcherWindow && !this.launcherWindow.isDestroyed()) {
      this.discardExtraLauncherWindows(existing, this.launcherWindow);
      presentElectronWindow(this.launcherWindow);
      this.reportLeftoverWorkbenchIfPresent();
      return this.reportAndReturn(this.stateFor("launcher"));
    }
    const adopted = existing[0] ?? null;
    if (adopted) {
      this.launcherWindow = adopted;
      this.attachWindowEvents("launcher", adopted);
      this.discardExtraLauncherWindows(existing, adopted);
      presentElectronWindow(adopted);
      this.reportLeftoverWorkbenchIfPresent();
      return this.reportAndReturn(this.stateFor("launcher"));
    }
    this.launcherWindow = this.createLauncherWindow(safeUrl, this.paths);
    this.attachWindowEvents("launcher", this.launcherWindow);
    presentElectronWindow(this.launcherWindow);
    this.reportLeftoverWorkbenchIfPresent();
    return this.reportAndReturn(this.stateFor("launcher"));
  }

  private discardExtraLauncherWindows(windows: ElectronWindowLike[], keep: ElectronWindowLike): void {
    for (const window of windows) {
      if (window === keep || window === this.workbenchWindow || window.isDestroyed()) {
        continue;
      }
      try {
        window.destroy();
      } catch {
        // An extra Launcher window is disposable; keep presenting the owned one.
      }
    }
  }

  async openOrFocusWorkbench(workbenchUrl = this.workbenchUrl): Promise<ManagedWindowState> {
    const safeUrl = localWorkbenchUrl(workbenchUrl);
    this.workbenchUrl = safeUrl;
    if (this.workbenchNavigation !== null) {
      await this.workbenchNavigation;
      return this.openOrFocusWorkbench(safeUrl);
    }

    const navigation = Promise.resolve().then(() => this.navigateWorkbench(safeUrl));
    this.workbenchNavigation = navigation;
    try {
      return await navigation;
    } finally {
      if (this.workbenchNavigation === navigation) {
        this.workbenchNavigation = null;
      }
    }
  }

  async openOrFocusInstanceWorkbench(input: {
    instanceId: string;
    url: string;
    title?: string;
  }): Promise<ManagedWindowState> {
    const instanceId = String(input.instanceId || "").trim();
    const title = String(input.title || "").trim();
    const safeUrl = localWorkbenchUrl(input.url);
    if (!instanceId) {
      throw new Error("instance workbench requires instanceId");
    }
    let entry = this.instanceWindows.get(instanceId);
    let window = entry?.window;
    if (!window || window.isDestroyed()) {
      window = this.createWorkbenchWindow(safeUrl, this.paths, title ? { title } : undefined);
      if (typeof window.setTitle === "function" && title) {
        window.setTitle(title);
      }
      this.lockInstanceWindowTitle(window, title);
      this.attachInstanceWindowEvents(instanceId, window);
      entry = { instanceId, url: safeUrl, title, window, readyUrl: null };
      this.instanceWindows.set(instanceId, entry);
    } else if (entry && title) {
      entry.title = title;
      if (typeof window.setTitle === "function") {
        window.setTitle(title);
      }
    }
    if (!entry) {
      throw new Error("instance workbench window was not created");
    }

    if (entry.readyUrl !== safeUrl) {
      window.hide();
      try {
        await window.loadURL(safeUrl);
        if (window.isDestroyed()) {
          throw new Error("Instance workbench window closed before navigation completed");
        }
        entry.readyUrl = safeUrl;
        entry.url = safeUrl;
      } catch (error: unknown) {
        this.discardInstanceWindow(instanceId, window);
        throw navigationFailure(safeUrl, error);
      }
    }

    presentElectronWindow(window);
    if (typeof window.setTitle === "function" && title) {
      window.setTitle(title);
    }
    return this.instanceState(instanceId);
  }

  async closeInstanceWorkbench(instanceId: string): Promise<ManagedWindowState> {
    const id = String(instanceId || "").trim();
    const entry = this.instanceWindows.get(id);
    if (!entry || entry.window.isDestroyed()) {
      this.instanceWindows.delete(id);
      return { ...closedWindowState("workbench"), instanceId: id };
    }
    entry.window.close();
    if (!entry.window.isDestroyed()) {
      const outcome = await waitForWindowClosed(entry.window, this.hungCloseDestroyAfterMs);
      if (outcome === "timeout" && !entry.window.isDestroyed()) {
        try {
          entry.window.destroy();
        } catch {
          // A hung isolated window must not keep a stale renderer.
        }
      }
    }
    this.instanceWindows.delete(id);
    this.attachedWindows.delete(entry.window);
    return { ...closedWindowState("workbench"), instanceId: id };
  }

  async focusWorkbench(): Promise<ManagedWindowState> {
    this.reconcileCurrentWorkbenchWindow();
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      return this.reportAndReturn(closedWindowState("workbench"));
    }
    presentElectronWindow(this.workbenchWindow);
    return this.reportAndReturn(this.stateFor("workbench"));
  }

  isWorkbenchFocused(): boolean {
    return Boolean(
      this.workbenchReadyUrl !== null && this.workbenchWindow && !this.workbenchWindow.isDestroyed() && this.workbenchWindow.isFocused()
    );
  }

  sendToWorkbench(channel: string, payload: unknown): boolean {
    const window = this.workbenchWindow;
    if (!window || window.isDestroyed() || this.workbenchReadyUrl === null) {
      return false;
    }
    if (typeof window.webContents.send !== "function") {
      return false;
    }
    window.webContents.send(channel, payload);
    return true;
  }

  setWorkbenchAttention(options: WorkbenchAttentionOptions): void {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed() || this.workbenchReadyUrl === null) {
      return;
    }

    const unreadCount = Number.isFinite(options.unreadCount) ? Math.max(0, Math.round(options.unreadCount)) : 0;
    const hasUnread = unreadCount > 0;
    const description = hasUnread
      ? options.description || `${unreadCount} completed conversation${unreadCount === 1 ? "" : "s"}`
      : "";

    if (typeof this.workbenchWindow.setOverlayIcon === "function") {
      this.workbenchWindow.setOverlayIcon(hasUnread ? options.overlayIcon ?? null : null, description);
    }

    if (typeof this.workbenchWindow.flashFrame === "function") {
      this.workbenchWindow.flashFrame(Boolean(options.flash && hasUnread));
    }
  }

  async closeWorkbench(): Promise<ManagedWindowState> {
    this.reconcileCurrentWorkbenchWindow();
    const workbenchWindow = this.workbenchWindow;
    if (!workbenchWindow || workbenchWindow.isDestroyed()) {
      this.discardExtraWorkbenchWindows(this.listLiveWorkbenchWindows(), null);
      return this.reportAndReturn(closedWindowState("workbench"));
    }
    if (this.shouldInterceptWorkbenchClose() && !this.workbenchCloseAuthorized) {
      this.requestWorkbenchCloseTransaction();
      return this.stateFor("workbench");
    }
    workbenchWindow.close();
    return this.stateFor("workbench");
  }

  async approveWorkbenchCloseOnce(): Promise<ManagedWindowState> {
    this.reconcileCurrentWorkbenchWindow();
    const workbenchWindow = this.workbenchWindow;
    if (!workbenchWindow || workbenchWindow.isDestroyed()) {
      this.discardExtraWorkbenchWindows(this.listLiveWorkbenchWindows(), null);
      return this.reportAndReturn(closedWindowState("workbench"));
    }
    this.workbenchCloseAuthorized = true;
    workbenchWindow.close();
    if (!workbenchWindow.isDestroyed()) {
      const outcome = await waitForWindowClosed(workbenchWindow, this.hungCloseDestroyAfterMs);
      if (outcome === "timeout" && !workbenchWindow.isDestroyed()) {
        try {
          workbenchWindow.destroy();
        } catch {
          // A hung renderer must not keep an authorized Workbench window open.
        }
      }
    }
    if (!workbenchWindow.isDestroyed()) {
      this.workbenchCloseAuthorized = false;
      this.workbenchCloseInFlight = false;
    }
    this.discardExtraWorkbenchWindows(this.listLiveWorkbenchWindows(), this.workbenchWindow);
    return this.stateFor("workbench");
  }

  isWorkbenchCloseInFlight(): boolean {
    return this.workbenchCloseInFlight;
  }

  instanceWindowStates(): Array<{ instanceId: string; open: boolean; rendererProcessId: number }> {
    const states: Array<{ instanceId: string; open: boolean; rendererProcessId: number }> = [];
    for (const [instanceId, entry] of this.instanceWindows) {
      const window = entry.window;
      if (!window || window.isDestroyed() || !entry.readyUrl) {
        continue;
      }
      states.push({
        instanceId,
        open: true,
        rendererProcessId: window.webContents.getOSProcessId()
      });
    }
    return states;
  }

  workbenchDialogParent(): ElectronWindowLike | null {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      return null;
    }
    return this.workbenchWindow;
  }

  snapshot(): { launcher: ManagedWindowState; workbench: ManagedWindowState } {
    this.reconcileCurrentWorkbenchWindow();
    return {
      launcher: this.stateFor("launcher"),
      workbench: this.stateFor("workbench")
    };
  }

  private attachInstanceWindowEvents(instanceId: string, window: ElectronWindowLike): void {
    if (this.attachedWindows.has(window)) {
      return;
    }
    this.attachedWindows.add(window);
    window.on("closed", () => {
      this.attachedWindows.delete(window);
      const entry = this.instanceWindows.get(instanceId);
      if (entry?.window === window) {
        this.instanceWindows.delete(instanceId);
      }
    });
    window.on("query-session-end", () => this.onOsSessionEnd("query-session-end", "workbench"));
    window.on("session-end", () => this.onOsSessionEnd("session-end", "workbench"));
  }

  private lockInstanceWindowTitle(window: ElectronWindowLike, title: string): void {
    if (!title) {
      return;
    }
    window.on("page-title-updated", (event) => {
      preventWindowClose(event);
      if (typeof window.setTitle === "function") {
        window.setTitle(title);
      }
    });
  }

  private instanceState(instanceId: string): ManagedWindowState {
    const entry = this.instanceWindows.get(instanceId);
    const window = entry?.window;
    if (!window || window.isDestroyed() || !entry?.readyUrl) {
      return { ...closedWindowState("workbench"), instanceId };
    }
    return {
      role: "workbench",
      provider: "electron",
      open: true,
      focused: window.isFocused(),
      windowId: window.id,
      rendererProcessId: window.webContents.getOSProcessId(),
      url: window.webContents.getURL(),
      instanceId,
      title: entry.title
    };
  }

  private discardInstanceWindow(instanceId: string, window: ElectronWindowLike): void {
    const entry = this.instanceWindows.get(instanceId);
    if (entry?.window === window) {
      this.instanceWindows.delete(instanceId);
    }
    this.attachedWindows.delete(window);
    if (!window.isDestroyed()) {
      try {
        window.destroy();
      } catch {
        // Preserve the original navigation failure for the desktop action result.
      }
    }
  }

  private attachWindowEvents(role: ElectronWindowRole, window: ElectronWindowLike): void {
    if (this.attachedWindows.has(window)) {
      return;
    }
    this.attachedWindows.add(window);
    if (role === "launcher") {
      this.interceptLauncherWindowOpenRequests(window);
      window.on("close", (event) => {
        if (!this.shouldInterceptLauncherClose()) {
          return;
        }
        preventWindowClose(event);
        window.hide();
        void this.reportState(this.stateFor("launcher"));
      });
    }
    if (role === "workbench") {
      this.interceptWorkbenchWindowOpenRequests(window);
      window.on("close", (event) => {
        if (this.workbenchCloseAuthorized || !this.shouldInterceptWorkbenchClose()) {
          return;
        }
        preventWindowClose(event);
        this.requestWorkbenchCloseTransaction();
      });
    }
    window.on("closed", () => {
      this.attachedWindows.delete(window);
      const wasLauncher = role === "launcher" && this.launcherWindow === window;
      const wasWorkbench = role === "workbench" && this.workbenchWindow === window;
      if (wasLauncher) {
        this.launcherWindow = null;
      }
      if (wasWorkbench) {
        this.workbenchWindow = null;
        this.workbenchReadyUrl = null;
        this.workbenchCloseAuthorized = false;
        this.workbenchCloseInFlight = false;
      }
      if (!wasLauncher && !wasWorkbench) {
        return;
      }
      const report = this.reportState(closedWindowState(role));
      if (wasWorkbench) {
        void Promise.resolve(report)
          .catch(() => undefined)
          .then(() => this.onWorkbenchClosed())
          .catch(() => undefined);
      }
    });
    window.on("focus", () => {
      if (role === "workbench") {
        this.onWorkbenchFocusAttentionClear();
        this.setWorkbenchAttention({ unreadCount: 0 });
      }
      void this.reportState(this.stateFor(role));
    });
    window.on("blur", () => void this.reportState(this.stateFor(role)));
    window.on("unresponsive", () => void this.reportState(this.stateFor(role)));
    window.webContents.on("render-process-gone", () => void this.reportState(this.stateFor(role)));
    if (role === "workbench") {
      window.webContents.on("will-navigate", (event, url) => {
        if (
          shouldCancelWorkbenchInPageNavigation({
            readyUrl: this.workbenchReadyUrl,
            currentUrl: window.webContents.getURL(),
            nextUrl: String(url ?? ""),
          })
        ) {
          preventWindowClose(event);
        }
      });
    }
    window.on("query-session-end", () => this.onOsSessionEnd("query-session-end", role));
    window.on("session-end", () => this.onOsSessionEnd("session-end", role));
  }

  private async navigateWorkbench(safeUrl: string): Promise<ManagedWindowState> {
    let workbenchWindow = this.reconcileCurrentWorkbenchWindow();
    if (!workbenchWindow || workbenchWindow.isDestroyed()) {
      workbenchWindow = this.createWorkbenchWindow(safeUrl, this.paths);
      this.workbenchWindow = workbenchWindow;
      this.workbenchReadyUrl = null;
      this.attachWindowEvents("workbench", workbenchWindow);
    }
    this.discardExtraWorkbenchWindows(this.listLiveWorkbenchWindows(), workbenchWindow);

    if (this.workbenchReadyUrl !== safeUrl) {
      this.workbenchReadyUrl = null;
      workbenchWindow.hide();
      try {
        await workbenchWindow.loadURL(safeUrl);
        if (workbenchWindow.isDestroyed() || this.workbenchWindow !== workbenchWindow) {
          throw new Error("Workbench window closed before navigation completed");
        }
        this.workbenchReadyUrl = safeUrl;
      } catch (error: unknown) {
        this.discardFailedWorkbenchWindow(workbenchWindow);
        throw navigationFailure(safeUrl, error);
      }
    }

    presentElectronWindow(workbenchWindow);
    return this.reportAndReturn(this.stateFor("workbench"));
  }

  private discardFailedWorkbenchWindow(window: ElectronWindowLike): void {
    if (this.workbenchWindow === window) {
      this.workbenchWindow = null;
      this.workbenchReadyUrl = null;
      this.workbenchCloseAuthorized = false;
      this.workbenchCloseInFlight = false;
    }
    if (!window.isDestroyed()) {
      try {
        window.destroy();
      } catch {
        // Preserve the original navigation failure for the desktop action result.
      }
    }
  }

  private requestWorkbenchCloseTransaction(): void {
    if (this.workbenchCloseInFlight) {
      return;
    }
    this.workbenchCloseInFlight = true;
    void Promise.resolve(this.onWorkbenchCloseRequest()).finally(() => {
      if (!this.workbenchCloseAuthorized) {
        this.workbenchCloseInFlight = false;
      }
    });
  }

  private interceptLauncherWindowOpenRequests(window: ElectronWindowLike): void {
    if (typeof window.webContents.setWindowOpenHandler !== "function") {
      return;
    }
    const workbenchOrigin = new URL(this.workbenchUrl).origin;
    window.webContents.setWindowOpenHandler((details) => {
      if (isManagedWorkbenchUrl(details.url, workbenchOrigin)) {
        void this.openOrFocusWorkbench().catch(() => undefined);
      }
      return { action: "deny" };
    });
  }

  private interceptWorkbenchWindowOpenRequests(window: ElectronWindowLike): void {
    if (typeof window.webContents.setWindowOpenHandler !== "function") {
      return;
    }
    const workbenchOrigin = new URL(this.workbenchUrl).origin;
    window.webContents.setWindowOpenHandler((details) => {
      if (isManagedWorkbenchUrl(details.url, workbenchOrigin)) {
        void this.openOrFocusWorkbench().catch(() => undefined);
      }
      return { action: "deny" };
    });
  }

  private reportLeftoverWorkbenchIfPresent(): void {
    this.reconcileCurrentWorkbenchWindow();
    const workbench = this.stateFor("workbench");
    if (workbench.open) {
      void this.reportState(workbench);
    }
  }

  private reconcileCurrentWorkbenchWindow(): ElectronWindowLike | null {
    if (this.workbenchWindow && !this.workbenchWindow.isDestroyed()) {
      return this.workbenchWindow;
    }
    this.workbenchWindow = null;
    const adopted = this.listLiveWorkbenchWindows()[0] ?? null;
    if (!adopted) {
      this.workbenchReadyUrl = null;
      return null;
    }
    this.workbenchWindow = adopted;
    this.attachWindowEvents("workbench", adopted);
    const currentUrl = adopted.webContents.getURL().trim();
    this.workbenchReadyUrl = currentUrl || null;
    return adopted;
  }

  private listLiveWorkbenchWindows(): ElectronWindowLike[] {
    let origin = "";
    try {
      origin = new URL(this.workbenchUrl).origin;
    } catch {
      return [];
    }
    const ownedInstances = new Set(
      [...this.instanceWindows.values()].map((entry) => entry.window)
    );
    return this.listWorkbenchWindows(origin).filter((window) => {
      if (!window || window.isDestroyed()) {
        return false;
      }
      if (window === this.launcherWindow) {
        return false;
      }
      return !ownedInstances.has(window);
    });
  }

  private discardExtraWorkbenchWindows(windows: ElectronWindowLike[], keep: ElectronWindowLike | null): void {
    for (const window of windows) {
      if (window === keep || window === this.launcherWindow || window.isDestroyed()) {
        continue;
      }
      let ownedInstance = false;
      for (const entry of this.instanceWindows.values()) {
        if (entry.window === window) {
          ownedInstance = true;
          break;
        }
      }
      if (ownedInstance) {
        continue;
      }
      try {
        window.destroy();
      } catch {
        // An extra Workbench window is disposable; keep presenting the owned one.
      }
    }
  }

  private stateFor(role: ElectronWindowRole): ManagedWindowState {
    const window = role === "launcher" ? this.launcherWindow : this.workbenchWindow;
    if (!window || window.isDestroyed()) {
      return closedWindowState(role);
    }
    if (role === "workbench" && this.workbenchReadyUrl === null && !window.webContents.getURL().trim()) {
      return closedWindowState(role);
    }
    return {
      role,
      provider: "electron",
      open: true,
      focused: window.isFocused(),
      windowId: window.id,
      rendererProcessId: window.webContents.getOSProcessId(),
      url: window.webContents.getURL()
    };
  }

  private async reportAndReturn(state: ManagedWindowState): Promise<ManagedWindowState> {
    await this.reportState(state);
    return state;
  }
}

function missingWindowFactory(role: ElectronWindowRole): ElectronWindowFactory {
  return () => {
    throw new Error(`missing ${role} window factory`);
  };
}

export function shouldCancelWorkbenchInPageNavigation(options: {
  readyUrl: string | null;
  currentUrl: string;
  nextUrl: string;
}): boolean {
  if (!options.readyUrl) {
    return false;
  }
  try {
    const current = new URL(options.currentUrl);
    const next = new URL(options.nextUrl);
    if (current.origin !== next.origin) {
      return false;
    }
    const currentKey = `${current.pathname}${current.search}${current.hash}`;
    const nextKey = `${next.pathname}${next.search}${next.hash}`;
    return currentKey !== nextKey;
  } catch {
    return false;
  }
}

function isManagedWorkbenchUrl(requestUrl: string, workbenchOrigin: string): boolean {
  try {
    return new URL(requestUrl).origin === workbenchOrigin;
  } catch {
    return false;
  }
}

function localWorkbenchUrl(value: string): string {
  const origin = new URL(value).origin;
  return assertLocalHttpUrl(value, origin);
}

function launcherWindowUrl(value: string): string {
  if (isLauncherAppUrl(value)) {
    return value;
  }
  const origin = new URL(value).origin;
  return assertLocalHttpUrl(value, origin);
}

function navigationFailure(url: string, error: unknown): Error {
  const origin = new URL(url).origin;
  const detail = error instanceof Error ? error.message : String(error);
  return new Error(`Workbench navigation failed for ${origin}: ${detail.slice(0, 300)}`);
}

function preventWindowClose(event: unknown): void {
  if (typeof event === "object" && event !== null && "preventDefault" in event) {
    const preventDefault = (event as { preventDefault?: unknown }).preventDefault;
    if (typeof preventDefault === "function") {
      preventDefault.call(event);
    }
  }
}
