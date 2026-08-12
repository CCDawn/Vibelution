import type { DesktopPaths } from "../paths.js";
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
  on(event: string, listener: ElectronWindowEventListener): unknown;
  setOverlayIcon?(icon: unknown, description: string): void;
  flashFrame?(flag: boolean): void;
  webContents: {
    getOSProcessId(): number;
    getURL(): string;
    on(event: string, listener: ElectronWindowEventListener): unknown;
    setWindowOpenHandler?(handler: ElectronWindowOpenHandler): void;
  };
};

export type WorkbenchAttentionOptions = {
  unreadCount: number;
  overlayIcon?: unknown;
  description?: string;
  flash?: boolean;
};

export type ElectronWindowFactory = (url: string, paths: DesktopPaths) => ElectronWindowLike;

export type ElectronWindowProviderOptions = {
  createLauncherWindow?: ElectronWindowFactory;
  createWorkbenchWindow?: ElectronWindowFactory;
  reportState?: (state: ManagedWindowState) => void | Promise<void>;
  shouldInterceptLauncherClose?: () => boolean;
  shouldInterceptWorkbenchClose?: () => boolean;
  onWorkbenchCloseRequest?: () => void | Promise<void>;
  onWorkbenchClosed?: () => void | Promise<void>;
  onWorkbenchFocusAttentionClear?: () => void;
  onOsSessionEnd?: (event: "query-session-end" | "session-end", role: ElectronWindowRole) => void;
};

export class ElectronWindowProvider {
  private launcherWindow: ElectronWindowLike | null = null;
  private workbenchWindow: ElectronWindowLike | null = null;
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

  constructor(
    private readonly paths: DesktopPaths,
    private readonly launcherUrl: string,
    workbenchUrl: string,
    options: ElectronWindowProviderOptions = {}
  ) {
    this.workbenchUrl = workbenchUrl;
    this.createLauncherWindow = options.createLauncherWindow ?? missingWindowFactory("launcher");
    this.createWorkbenchWindow = options.createWorkbenchWindow ?? missingWindowFactory("workbench");
    this.reportState = options.reportState ?? (() => undefined);
    this.shouldInterceptLauncherClose = options.shouldInterceptLauncherClose ?? (() => false);
    this.shouldInterceptWorkbenchClose = options.shouldInterceptWorkbenchClose ?? (() => false);
    this.onWorkbenchCloseRequest = options.onWorkbenchCloseRequest ?? (() => undefined);
    this.onWorkbenchClosed = options.onWorkbenchClosed ?? (() => undefined);
    this.onWorkbenchFocusAttentionClear = options.onWorkbenchFocusAttentionClear ?? (() => undefined);
    this.onOsSessionEnd = options.onOsSessionEnd ?? (() => undefined);
  }

  async openLauncher(): Promise<ManagedWindowState> {
    const launcherOrigin = new URL(this.launcherUrl).origin;
    const safeUrl = assertLocalHttpUrl(this.launcherUrl, launcherOrigin);
    if (!this.launcherWindow || this.launcherWindow.isDestroyed()) {
      this.launcherWindow = this.createLauncherWindow(safeUrl, this.paths);
      this.attachWindowEvents("launcher", this.launcherWindow);
    }
    this.launcherWindow.focus();
    return this.reportAndReturn(this.stateFor("launcher"));
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

  async focusWorkbench(): Promise<ManagedWindowState> {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      return this.reportAndReturn(closedWindowState("workbench"));
    }
    this.workbenchWindow.focus();
    return this.reportAndReturn(this.stateFor("workbench"));
  }

  isWorkbenchFocused(): boolean {
    return Boolean(
      this.workbenchReadyUrl !== null && this.workbenchWindow && !this.workbenchWindow.isDestroyed() && this.workbenchWindow.isFocused()
    );
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
    const workbenchWindow = this.workbenchWindow;
    if (!workbenchWindow || workbenchWindow.isDestroyed()) {
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
    const workbenchWindow = this.workbenchWindow;
    if (!workbenchWindow || workbenchWindow.isDestroyed()) {
      return this.reportAndReturn(closedWindowState("workbench"));
    }
    this.workbenchCloseAuthorized = true;
    workbenchWindow.close();
    return this.stateFor("workbench");
  }

  isWorkbenchCloseInFlight(): boolean {
    return this.workbenchCloseInFlight;
  }

  workbenchDialogParent(): ElectronWindowLike | null {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      return null;
    }
    return this.workbenchWindow;
  }

  snapshot(): { launcher: ManagedWindowState; workbench: ManagedWindowState } {
    return {
      launcher: this.stateFor("launcher"),
      workbench: this.stateFor("workbench")
    };
  }

  private attachWindowEvents(role: ElectronWindowRole, window: ElectronWindowLike): void {
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
      window.on("close", (event) => {
        if (this.workbenchCloseAuthorized || !this.shouldInterceptWorkbenchClose()) {
          return;
        }
        preventWindowClose(event);
        this.requestWorkbenchCloseTransaction();
      });
    }
    window.on("closed", () => {
      if (role === "launcher" && this.launcherWindow === window) {
        this.launcherWindow = null;
      }
      if (role === "workbench" && this.workbenchWindow === window) {
        this.workbenchWindow = null;
        this.workbenchReadyUrl = null;
        this.workbenchCloseAuthorized = false;
        this.workbenchCloseInFlight = false;
      }
      const report = this.reportState(closedWindowState(role));
      if (role === "workbench") {
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
    let workbenchWindow = this.workbenchWindow;
    if (!workbenchWindow || workbenchWindow.isDestroyed()) {
      workbenchWindow = this.createWorkbenchWindow(safeUrl, this.paths);
      this.workbenchWindow = workbenchWindow;
      this.workbenchReadyUrl = null;
      this.attachWindowEvents("workbench", workbenchWindow);
    }

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

    workbenchWindow.show();
    workbenchWindow.focus();
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

  private stateFor(role: ElectronWindowRole): ManagedWindowState {
    const window = role === "launcher" ? this.launcherWindow : this.workbenchWindow;
    if (!window || window.isDestroyed()) {
      return closedWindowState(role);
    }
    if (role === "workbench" && this.workbenchReadyUrl === null) {
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
