import type { DesktopPaths } from "../paths.js";
import { isLauncherAppUrl, launcherAppOriginFor } from "../protocol/launcherAppProtocol.js";
import { assertLocalHttpUrl } from "../security/urlPolicy.js";
import { isExternalOpenableUrl } from "../security/externalOpenPolicy.js";
import { desktopPetWindowUrl } from "./petWindow.js";
import { isWorkbenchErrorPageUrl, workbenchErrorPageDataUrl } from "./workbenchErrorPage.js";
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
  reload?(): void;
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
  createPetWindow?: ElectronWindowFactory;
  launcherContentVersion?: () => string;
  listLauncherWindows?: (launcherOrigin: string) => ElectronWindowLike[];
  listWorkbenchWindows?: (workbenchOrigin: string) => ElectronWindowLike[];
  reportState?: (state: ManagedWindowState) => void | Promise<void>;
  shouldInterceptLauncherClose?: () => boolean;
  shouldInterceptWorkbenchClose?: () => boolean;
  shouldInterceptInstanceClose?: (instanceId: string) => boolean;
  onWorkbenchCloseRequest?: () => void | Promise<void>;
  onWorkbenchClosed?: () => void | Promise<void>;
  onWorkbenchOpenRequest?: () => void | Promise<void>;
  openExternalUrl?: (url: string) => void | Promise<void>;
  onInstanceCloseRequest?: (instanceId: string) => void | Promise<void>;
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
  private petWindow: ElectronWindowLike | null = null;
  private readonly instanceWindows = new Map<string, InstanceWorkbenchEntry>();
  private readonly createLauncherWindow: ElectronWindowFactory;
  private readonly createWorkbenchWindow: ElectronWindowFactory;
  private readonly createPetWindow: ElectronWindowFactory;
  private readonly reportState: (state: ManagedWindowState) => void | Promise<void>;
  private readonly shouldInterceptLauncherClose: () => boolean;
  private readonly shouldInterceptWorkbenchClose: () => boolean;
  private readonly shouldInterceptInstanceClose: (instanceId: string) => boolean;
  private readonly onWorkbenchCloseRequest: () => void | Promise<void>;
  private readonly onWorkbenchClosed: () => void | Promise<void>;
  private readonly onWorkbenchOpenRequest: () => void | Promise<void>;
  private readonly openExternalUrl: (url: string) => void | Promise<void>;
  private readonly onInstanceCloseRequest: (instanceId: string) => void | Promise<void>;
  private readonly onWorkbenchFocusAttentionClear: () => void;
  private readonly onOsSessionEnd: (event: "query-session-end" | "session-end", role: ElectronWindowRole) => void;
  private workbenchUrl: string;
  private workbenchReadyUrl: string | null = null;
  private workbenchNavigation: Promise<ManagedWindowState> | null = null;
  private petNavigation: Promise<ManagedWindowState> | null = null;
  private petReadyUrl: string | null = null;
  private workbenchCloseAuthorized = false;
  private workbenchCloseInFlight = false;
  private readonly instanceCloseAuthorized = new Map<string, ElectronWindowLike>();
  private readonly instanceCloseInFlight = new Set<string>();
  private launcherOpen: Promise<ManagedWindowState> | null = null;
  private readonly launcherContentVersion?: () => string;
  private launcherLoadedVersion: string | null = null;
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
    this.createPetWindow = options.createPetWindow ?? missingWindowFactory("pet");
    this.listLauncherWindows = options.listLauncherWindows ?? (() => []);
    this.listWorkbenchWindows = options.listWorkbenchWindows ?? (() => []);
    this.reportState = options.reportState ?? (() => undefined);
    this.shouldInterceptLauncherClose = options.shouldInterceptLauncherClose ?? (() => false);
    this.shouldInterceptWorkbenchClose = options.shouldInterceptWorkbenchClose ?? (() => false);
    this.shouldInterceptInstanceClose = options.shouldInterceptInstanceClose
      ?? (options.onInstanceCloseRequest ? (() => true) : (() => false));
    this.onWorkbenchCloseRequest = options.onWorkbenchCloseRequest ?? (() => undefined);
    this.onWorkbenchClosed = options.onWorkbenchClosed ?? (() => undefined);
    this.onWorkbenchOpenRequest = options.onWorkbenchOpenRequest ?? (async () => {
      await this.openOrFocusWorkbench();
    });
    this.openExternalUrl = options.openExternalUrl ?? (() => undefined);
    this.onInstanceCloseRequest = options.onInstanceCloseRequest ?? (() => undefined);
    this.onWorkbenchFocusAttentionClear = options.onWorkbenchFocusAttentionClear ?? (() => undefined);
    this.onOsSessionEnd = options.onOsSessionEnd ?? (() => undefined);
    this.hungCloseDestroyAfterMs =
      typeof options.hungCloseDestroyAfterMs === "number" && Number.isFinite(options.hungCloseDestroyAfterMs)
        ? Math.max(0, options.hungCloseDestroyAfterMs)
        : DEFAULT_HUNG_CLOSE_DESTROY_AFTER_MS;
    this.launcherContentVersion = options.launcherContentVersion;
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

  /**
   * Reload an already-open launcher window when the active frontend release
   * changed since it was last presented (e.g. the builder switched
   * active.json while the shell stayed resident).  Returns true when a
   * reload was issued.
   */
  refreshLauncherIfReleaseChanged(): boolean {
    const window = this.launcherWindow;
    if (!window || window.isDestroyed()) {
      return false;
    }
    const version = this.currentLauncherContentVersion();
    if (!version || this.launcherLoadedVersion === version) {
      return false;
    }
    this.reloadLauncherIfStale(window, version);
    return true;
  }

  private async presentLauncher(): Promise<ManagedWindowState> {
    const launcherOrigin = launcherAppOriginFor(this.launcherUrl);
    const safeUrl = launcherWindowUrl(this.launcherUrl);
    const existing = this.listLauncherWindows(launcherOrigin).filter((window) => !window.isDestroyed());
    const contentVersion = this.currentLauncherContentVersion();
    if (this.launcherWindow && !this.launcherWindow.isDestroyed()) {
      this.reloadLauncherIfStale(this.launcherWindow, contentVersion);
      this.discardExtraLauncherWindows(existing, this.launcherWindow);
      presentElectronWindow(this.launcherWindow);
      this.reportLeftoverWorkbenchIfPresent();
      return this.reportAndReturn(this.stateFor("launcher"));
    }
    const adopted = existing[0] ?? null;
    if (adopted) {
      this.launcherWindow = adopted;
      this.attachWindowEvents("launcher", adopted);
      this.noteLauncherContentVersion(contentVersion);
      this.discardExtraLauncherWindows(existing, adopted);
      presentElectronWindow(adopted);
      this.reportLeftoverWorkbenchIfPresent();
      return this.reportAndReturn(this.stateFor("launcher"));
    }
    this.launcherWindow = this.createLauncherWindow(safeUrl, this.paths);
    this.attachWindowEvents("launcher", this.launcherWindow);
    this.noteLauncherContentVersion(contentVersion);
    presentElectronWindow(this.launcherWindow);
    this.reportLeftoverWorkbenchIfPresent();
    return this.reportAndReturn(this.stateFor("launcher"));
  }

  private currentLauncherContentVersion(): string {
    if (!this.launcherContentVersion) {
      return "";
    }
    try {
      return String(this.launcherContentVersion() ?? "");
    } catch {
      return "";
    }
  }

  private noteLauncherContentVersion(version: string): void {
    if (version) {
      this.launcherLoadedVersion = version;
    }
  }

  private reloadLauncherIfStale(window: ElectronWindowLike, version: string): void {
    if (!version) {
      return;
    }
    const loaded = this.launcherLoadedVersion;
    this.launcherLoadedVersion = version;
    if (loaded === null || loaded === version) {
      return;
    }
    try {
      window.reload?.();
    } catch {
      // A destroyed or mid-navigation window keeps its current document; the
      // next open re-checks the content version.
    }
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

  async openPet(workbenchUrl = this.workbenchUrl): Promise<ManagedWindowState> {
    const safeWorkbenchUrl = localWorkbenchUrl(workbenchUrl);
    const safeUrl = desktopPetWindowUrl(safeWorkbenchUrl);
    if (this.petNavigation !== null) {
      await this.petNavigation;
      return this.openPet(safeWorkbenchUrl);
    }
    const navigation = Promise.resolve().then(async () => {
      let window = this.petWindow;
      if (!window || window.isDestroyed()) {
        window = this.createPetWindow(safeUrl, this.paths);
        this.petWindow = window;
        this.petReadyUrl = null;
        this.attachWindowEvents("pet", window);
      }
      if (this.petReadyUrl !== safeUrl) {
        window.hide();
        try {
          await window.loadURL(safeUrl);
          if (window.isDestroyed() || this.petWindow !== window) {
            throw new Error("Desktop pet window closed before navigation completed");
          }
          this.petReadyUrl = safeUrl;
        } catch (error: unknown) {
          if (this.petWindow === window) {
            this.petWindow = null;
            this.petReadyUrl = null;
          }
          if (!window.isDestroyed()) {
            window.destroy();
          }
          throw navigationFailure(safeUrl, error);
        }
      }
      window.show();
      return this.stateFor("pet");
    });
    this.petNavigation = navigation;
    try {
      return await navigation;
    } finally {
      if (this.petNavigation === navigation) {
        this.petNavigation = null;
      }
    }
  }

  async closePet(): Promise<ManagedWindowState> {
    const window = this.petWindow;
    if (!window || window.isDestroyed()) {
      this.petWindow = null;
      this.petReadyUrl = null;
      return closedWindowState("pet");
    }
    window.close();
    return this.stateFor("pet");
  }

  async openOrFocusInstanceWorkbench(input: {
    instanceId: string;
    url: string;
    title?: string;
    /**
     * Hidden presentation (e2e lanes): load the workbench URL but skip
     * restore/show/focus so tests never steal the user's desktop focus. The
     * window still exists with a live renderer, so CDP can attach and the
     * instance registry still observes an open window. Default (undefined or
     * true) keeps the historical always-present behavior.
     */
    present?: boolean;
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
      this.attachInstanceWindowEvents(instanceId, window);
      entry = { instanceId, url: safeUrl, title, window, readyUrl: null };
      this.instanceWindows.set(instanceId, entry);
      this.lockInstanceWindowTitle(window, instanceId);
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

    if (input.present !== false) {
      presentElectronWindow(window);
    }
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
      this.instanceCloseAuthorized.delete(id);
      this.instanceCloseInFlight.delete(id);
      return { ...closedWindowState("workbench"), instanceId: id };
    }
    this.instanceCloseAuthorized.set(id, entry.window);
    try {
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
    } finally {
      if (this.instanceCloseAuthorized.get(id) === entry.window) {
        this.instanceCloseAuthorized.delete(id);
      }
      this.instanceCloseInFlight.delete(id);
      if (this.instanceWindows.get(id)?.window === entry.window) {
        this.instanceWindows.delete(id);
      }
      this.attachedWindows.delete(entry.window);
    }
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

  sendToLauncher(channel: string, payload: unknown): boolean {
    const window = this.launcherWindow;
    if (!window || window.isDestroyed() || typeof window.webContents.send !== "function") {
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

  instanceWindowStates(): Array<{ instanceId: string; open: boolean; rendererProcessId: number; url: string }> {
    const states: Array<{ instanceId: string; open: boolean; rendererProcessId: number; url: string }> = [];
    for (const [instanceId, entry] of this.instanceWindows) {
      const window = entry.window;
      if (!window || window.isDestroyed() || !entry.readyUrl) {
        continue;
      }
      states.push({
        instanceId,
        open: true,
        url: entry.readyUrl,
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

  snapshot(): { launcher: ManagedWindowState; workbench: ManagedWindowState; pet: ManagedWindowState } {
    this.reconcileCurrentWorkbenchWindow();
    return {
      launcher: this.stateFor("launcher"),
      workbench: this.stateFor("workbench"),
      pet: this.stateFor("pet")
    };
  }

  private attachInstanceWindowEvents(instanceId: string, window: ElectronWindowLike): void {
    if (this.attachedWindows.has(window)) {
      return;
    }
    this.attachedWindows.add(window);
    window.on("close", (event) => {
      const entry = this.instanceWindows.get(instanceId);
      if (
        entry?.window !== window
        || this.instanceCloseAuthorized.get(instanceId) === window
        || !this.shouldInterceptInstanceClose(instanceId)
      ) {
        return;
      }
      preventWindowClose(event);
      if (this.instanceCloseInFlight.has(instanceId)) {
        return;
      }
      this.instanceCloseInFlight.add(instanceId);
      void Promise.resolve(this.onInstanceCloseRequest(instanceId))
        .catch(() => undefined)
        .finally(() => {
          this.instanceCloseInFlight.delete(instanceId);
        });
    });
    window.on("closed", () => {
      this.attachedWindows.delete(window);
      if (this.instanceCloseAuthorized.get(instanceId) === window) {
        this.instanceCloseAuthorized.delete(instanceId);
      }
      this.instanceCloseInFlight.delete(instanceId);
      const entry = this.instanceWindows.get(instanceId);
      if (entry?.window === window) {
        this.instanceWindows.delete(instanceId);
      }
    });
    window.on("query-session-end", () => this.onOsSessionEnd("query-session-end", "workbench"));
    window.on("session-end", () => this.onOsSessionEnd("session-end", "workbench"));
  }

  private lockInstanceWindowTitle(window: ElectronWindowLike, instanceId: string): void {
    window.on("page-title-updated", (event) => {
      const title = this.instanceWindows.get(instanceId)?.title || "";
      if (!title) {
        return;
      }
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
    if (this.instanceCloseAuthorized.get(instanceId) === window) {
      this.instanceCloseAuthorized.delete(instanceId);
    }
    this.instanceCloseInFlight.delete(instanceId);
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
      const wasPet = role === "pet" && this.petWindow === window;
      if (wasLauncher) {
        this.launcherWindow = null;
      }
      if (wasWorkbench) {
        this.workbenchWindow = null;
        this.workbenchReadyUrl = null;
        this.workbenchCloseAuthorized = false;
        this.workbenchCloseInFlight = false;
      }
      if (wasPet) {
        this.petWindow = null;
        this.petReadyUrl = null;
      }
      if (!wasLauncher && !wasWorkbench && !wasPet) {
        return;
      }
      const report = role === "pet" ? undefined : this.reportState(closedWindowState(role));
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
      if (role !== "pet") {
        void this.reportState(this.stateFor(role));
      }
    });
    window.on("blur", () => role !== "pet" && void this.reportState(this.stateFor(role)));
    window.on("unresponsive", () => role !== "pet" && void this.reportState(this.stateFor(role)));
    window.webContents.on("render-process-gone", () => role !== "pet" && void this.reportState(this.stateFor(role)));
    if (role === "workbench") {
      window.webContents.on("will-navigate", (event, url) => {
        const nextUrl = String(url ?? "");
        const workbenchOrigin = new URL(this.workbenchUrl).origin;
        if (shouldRouteWorkbenchNavigationExternally({ workbenchOrigin, nextUrl })) {
          preventWindowClose(event);
          this.openExternalInSystemBrowser(nextUrl);
          return;
        }
        if (shouldCancelWorkbenchForeignNavigation({ workbenchOrigin, nextUrl })) {
          preventWindowClose(event);
          return;
        }
        if (
          shouldCancelWorkbenchInPageNavigation({
            readyUrl: this.workbenchReadyUrl,
            currentUrl: window.webContents.getURL(),
            nextUrl
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

    if (this.shouldReloadWorkbenchWindow(safeUrl)) {
      this.workbenchReadyUrl = null;
      workbenchWindow.hide();
      try {
        await workbenchWindow.loadURL(safeUrl);
        if (workbenchWindow.isDestroyed() || this.workbenchWindow !== workbenchWindow) {
          throw new Error("Workbench window closed before navigation completed");
        }
        this.workbenchReadyUrl = safeUrl;
      } catch (error: unknown) {
        // Never destroy the window out from under the user (a one-frame flash
        // with no explanation). Keep it alive, present the bilingual error
        // document, and rethrow the original failure so the desktop action
        // stays retryable and the log keeps the root cause.
        await this.presentWorkbenchErrorStatus({
          origin: originOfUrl(safeUrl),
          detail: navigationFailureDetail(error)
        });
        throw navigationFailure(safeUrl, error);
      }
    }

    presentElectronWindow(workbenchWindow);
    return this.reportAndReturn(this.stateFor("workbench"));
  }

  /**
   * Present the visible bilingual "backend unavailable" status in the
   * Workbench window instead of destroying it. Reused by the navigation
   * failure path and by main.ts when the backend start attempt itself failed
   * before any navigation could happen. Best-effort: if even the local error
   * document cannot load, the window stays hidden rather than masking the
   * original failure.
   */
  async presentWorkbenchErrorStatus(input: { origin: string; detail: string }): Promise<ManagedWindowState> {
    let workbenchWindow = this.reconcileCurrentWorkbenchWindow();
    if (!workbenchWindow || workbenchWindow.isDestroyed()) {
      workbenchWindow = this.createWorkbenchWindow(this.workbenchUrl, this.paths);
      this.workbenchWindow = workbenchWindow;
      this.workbenchReadyUrl = null;
      this.attachWindowEvents("workbench", workbenchWindow);
    }
    this.workbenchReadyUrl = null;
    try {
      await workbenchWindow.loadURL(workbenchErrorPageDataUrl(input));
    } catch {
      // The error document is best-effort; never mask the original failure.
    }
    presentElectronWindow(workbenchWindow);
    return this.reportAndReturn(this.stateFor("workbench"));
  }

  /**
   * Reload the workbench window only when the target actually moves it to
   * another origin (restore after close, backend port move). Same-origin path
   * differences belong to the frontend router: the user may have navigated to
   * a deep page (e.g. /teams?questionId=...), and repeated open/focus actions
   * (desktop open_workbench converge, pet handoff) must never force that page
   * back (SCI-049 pinning/bounce). Only tracked loads (workbenchReadyUrl)
   * count as "already there"; unknown URLs stay conservative and reload.
   */
  private shouldReloadWorkbenchWindow(safeUrl: string): boolean {
    if (!this.workbenchReadyUrl) {
      return true;
    }
    const currentOrigin = originOfUrl(this.workbenchReadyUrl);
    const targetOrigin = originOfUrl(safeUrl);
    if (!currentOrigin || !targetOrigin) {
      return true;
    }
    return currentOrigin !== targetOrigin;
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
        void Promise.resolve(this.onWorkbenchOpenRequest()).catch(() => undefined);
        return { action: "deny" };
      }
      if (isExternalOpenableUrl(details.url)) {
        this.openExternalInSystemBrowser(details.url);
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
        void Promise.resolve(this.onWorkbenchOpenRequest()).catch(() => undefined);
        return { action: "deny" };
      }
      if (isExternalOpenableUrl(details.url)) {
        this.openExternalInSystemBrowser(details.url);
      }
      return { action: "deny" };
    });
  }

  /**
   * Hand an http/https/mailto URL to the operating system browser. The
   * injected `openExternalUrl` is invoked defensively: a synchronous throw or
   * rejection must never escape into the window-open handler callback.
   */
  private openExternalInSystemBrowser(url: string): void {
    void Promise.resolve()
      .then(() => this.openExternalUrl(url))
      .catch(() => undefined);
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
      const url = this.workbenchWindow.webContents.getURL().trim();
      if (url) {
        this.syncWorkbenchUrlFromWindow(this.workbenchWindow);
      }
      return this.workbenchWindow;
    }
    const live = this.listLiveWorkbenchWindows().filter((window) => window.webContents.getURL().trim());
    const expectedOrigin = (() => {
      try {
        return new URL(this.workbenchUrl).origin;
      } catch {
        return "";
      }
    })();
    const adopted =
      live.find((window) => {
        try {
          return new URL(window.webContents.getURL()).origin === expectedOrigin;
        } catch {
          return false;
        }
      })
      ?? live[0]
      ?? null;
    if (!adopted) {
      this.workbenchWindow = null;
      this.workbenchReadyUrl = null;
      return null;
    }
    this.workbenchWindow = adopted;
    this.attachWindowEvents("workbench", adopted);
    this.syncWorkbenchUrlFromWindow(adopted);
    return adopted;
  }

  private syncWorkbenchUrlFromWindow(window: ElectronWindowLike): void {
    const currentUrl = window.webContents.getURL().trim();
    if (isWorkbenchErrorPageUrl(currentUrl)) {
      // The error document is not a ready Workbench page: keep the ready
      // marker unset so sends, attention overlays and focus tracking stay
      // disabled, and keep the previous workbench URL so the next open
      // reloads the real origin.
      this.workbenchReadyUrl = null;
      return;
    }
    this.workbenchReadyUrl = currentUrl || null;
    if (!currentUrl) {
      return;
    }
    try {
      this.workbenchUrl = localWorkbenchUrl(currentUrl);
    } catch {
      // Keep the previously resolved workbench URL if the live window URL is not loadable.
    }
  }

  private listLiveWorkbenchWindows(): ElectronWindowLike[] {
    let origin = "";
    try {
      origin = new URL(this.workbenchUrl).origin;
    } catch {
      origin = "http://127.0.0.1:8000";
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
    const window = role === "launcher"
      ? this.launcherWindow
      : role === "workbench"
        ? this.workbenchWindow
        : this.petWindow;
    if (!window || window.isDestroyed()) {
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

/**
 * Whether a workbench main-frame navigation must leave the app instead of
 * moving the window: an openable external URL (http/https/mailto) whose origin
 * differs from the workbench origin is routed to the system browser, and the
 * in-window navigation is cancelled so the product shell is never navigated
 * away. Same-origin and non-openable URLs stay with the existing policy.
 */
export function shouldRouteWorkbenchNavigationExternally(options: {
  workbenchOrigin: string;
  nextUrl: string;
}): boolean {
  if (!isExternalOpenableUrl(options.nextUrl)) {
    return false;
  }
  try {
    return new URL(options.nextUrl).origin !== options.workbenchOrigin;
  } catch {
    return false;
  }
}

/**
 * Whether a non-openable workbench navigation must be cancelled outright:
 * file:, about:, custom app protocols and other schemes whose origin differs
 * from the workbench must never replace the product document. Unparseable
 * targets keep the legacy behavior (Chromium rejects them anyway).
 */
export function shouldCancelWorkbenchForeignNavigation(options: {
  workbenchOrigin: string;
  nextUrl: string;
}): boolean {
  if (isExternalOpenableUrl(options.nextUrl)) {
    return false;
  }
  try {
    return new URL(options.nextUrl).origin !== options.workbenchOrigin;
  } catch {
    return false;
  }
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

function originOfUrl(value: string): string {
  try {
    return new URL(value).origin;
  } catch {
    return "";
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
  const detail = navigationFailureDetail(error);
  return new Error(`Workbench navigation failed for ${origin}: ${detail.slice(0, 300)}`);
}

function navigationFailureDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function preventWindowClose(event: unknown): void {
  if (typeof event === "object" && event !== null && "preventDefault" in event) {
    const preventDefault = (event as { preventDefault?: unknown }).preventDefault;
    if (typeof preventDefault === "function") {
      preventDefault.call(event);
    }
  }
}
