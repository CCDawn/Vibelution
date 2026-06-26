import type { DesktopPaths } from "../paths.js";
import { assertLocalHttpUrl } from "../security/urlPolicy.js";
import { closedWindowState, type ElectronWindowRole, type ManagedWindowState } from "./windowProviderTypes.js";

type ElectronWindowEventListener = (...args: unknown[]) => void;

export type ElectronWindowLike = {
  id: number;
  focus(): void;
  close(): void;
  isDestroyed(): boolean;
  isFocused(): boolean;
  on(event: string, listener: ElectronWindowEventListener): unknown;
  webContents: {
    getOSProcessId(): number;
    getURL(): string;
    on(event: string, listener: ElectronWindowEventListener): unknown;
  };
};

export type ElectronWindowFactory = (url: string, paths: DesktopPaths) => ElectronWindowLike;

export type ElectronWindowProviderOptions = {
  createLauncherWindow?: ElectronWindowFactory;
  createWorkbenchWindow?: ElectronWindowFactory;
  reportState?: (state: ManagedWindowState) => void | Promise<void>;
};

export class ElectronWindowProvider {
  private launcherWindow: ElectronWindowLike | null = null;
  private workbenchWindow: ElectronWindowLike | null = null;
  private readonly createLauncherWindow: ElectronWindowFactory;
  private readonly createWorkbenchWindow: ElectronWindowFactory;
  private readonly reportState: (state: ManagedWindowState) => void | Promise<void>;

  constructor(
    private readonly paths: DesktopPaths,
    private readonly launcherUrl: string,
    private readonly workbenchUrl: string,
    options: ElectronWindowProviderOptions = {}
  ) {
    this.createLauncherWindow = options.createLauncherWindow ?? missingWindowFactory("launcher");
    this.createWorkbenchWindow = options.createWorkbenchWindow ?? missingWindowFactory("workbench");
    this.reportState = options.reportState ?? (() => undefined);
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

  async openOrFocusWorkbench(): Promise<ManagedWindowState> {
    const workbenchOrigin = new URL(this.workbenchUrl).origin;
    const safeUrl = assertLocalHttpUrl(this.workbenchUrl, workbenchOrigin);
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      this.workbenchWindow = this.createWorkbenchWindow(safeUrl, this.paths);
      this.attachWindowEvents("workbench", this.workbenchWindow);
    }
    this.workbenchWindow.focus();
    return this.reportAndReturn(this.stateFor("workbench"));
  }

  async focusWorkbench(): Promise<ManagedWindowState> {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      return this.reportAndReturn(closedWindowState("workbench"));
    }
    this.workbenchWindow.focus();
    return this.reportAndReturn(this.stateFor("workbench"));
  }

  async closeWorkbench(): Promise<ManagedWindowState> {
    if (this.workbenchWindow && !this.workbenchWindow.isDestroyed()) {
      this.workbenchWindow.close();
    }
    return this.reportAndReturn(closedWindowState("workbench"));
  }

  snapshot(): { launcher: ManagedWindowState; workbench: ManagedWindowState } {
    return {
      launcher: this.stateFor("launcher"),
      workbench: this.stateFor("workbench")
    };
  }

  private attachWindowEvents(role: ElectronWindowRole, window: ElectronWindowLike): void {
    window.on("closed", () => {
      if (role === "launcher" && this.launcherWindow === window) {
        this.launcherWindow = null;
      }
      if (role === "workbench" && this.workbenchWindow === window) {
        this.workbenchWindow = null;
      }
      void this.reportState(closedWindowState(role));
    });
    window.on("focus", () => void this.reportState(this.stateFor(role)));
    window.on("blur", () => void this.reportState(this.stateFor(role)));
    window.on("unresponsive", () => void this.reportState(this.stateFor(role)));
    window.webContents.on("render-process-gone", () => void this.reportState(this.stateFor(role)));
  }

  private stateFor(role: ElectronWindowRole): ManagedWindowState {
    const window = role === "launcher" ? this.launcherWindow : this.workbenchWindow;
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
