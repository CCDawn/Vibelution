import { describe, expect, it, vi } from "vitest";
import type { IpcMainInvokeEvent } from "electron";
import { IPC_CHANNELS } from "../src/ipc.js";
import { assertLocalHttpUrl, isLiveWorkbenchWindowUrl } from "../src/security/urlPolicy.js";
import { assertTrustedIpcSender } from "../src/security/ipcSenderValidation.js";
import { resolveLauncherWindowUrl, resolveWorkbenchUrl } from "../src/windows/windowUrlResolver.js";
import {
  ElectronWindowProvider,
  shouldCancelWorkbenchInPageNavigation,
  type ElectronWindowLike,
  type ElectronWindowOpenDecision,
  type ElectronWindowOpenHandler
} from "../src/windows/electronWindowProvider.js";
import { closedWindowState } from "../src/windows/windowProviderTypes.js";
import type { DesktopPaths } from "../src/paths.js";

class FakeWindow implements ElectronWindowLike {
  readonly id: number;
  readonly webContents: ElectronWindowLike["webContents"];
  windowOpenHandler: ElectronWindowOpenHandler | null = null;
  focusCount = 0;
  closeCount = 0;
  showCount = 0;
  hideCount = 0;
  restoreCount = 0;
  destroyCount = 0;
  minimized = false;
  loadedUrls: string[] = [];
  overlayCalls: Array<{ icon: unknown; description: string }> = [];
  flashCalls: boolean[] = [];
  sentIpc: Array<{ channel: string; payload: unknown }> = [];
  title = "";
  private destroyed = false;
  private focused = false;
  private handlers = new Map<string, Array<(...args: unknown[]) => void>>();

  constructor(
    id: number,
    private url: string,
    rendererProcessId: number,
    private readonly closeEmitsClosed = true,
    private readonly navigationError: Error | null = null
  ) {
    this.id = id;
    this.webContents = {
      getOSProcessId: () => rendererProcessId,
      getURL: () => this.url,
      on: (event, listener) => {
        this.on(`webContents:${event}`, listener);
        return this.webContents;
      },
      setWindowOpenHandler: (handler) => {
        this.windowOpenHandler = handler;
      },
      send: (channel, payload) => {
        this.sentIpc.push({ channel, payload });
      }
    };
  }

  openRequest(url: string): ElectronWindowOpenDecision {
    if (this.windowOpenHandler === null) {
      throw new Error("no window open handler installed");
    }
    return this.windowOpenHandler({ url });
  }

  focus(): void {
    this.focusCount += 1;
    this.focused = true;
  }

  show(): void {
    this.showCount += 1;
    this.minimized = false;
  }

  hide(): void {
    this.hideCount += 1;
    this.focused = false;
  }

  isMinimized(): boolean {
    return this.minimized;
  }

  restore(): void {
    this.restoreCount += 1;
    this.minimized = false;
  }

  loadURL(url: string): Promise<void> {
    this.loadedUrls.push(url);
    if (this.navigationError !== null) {
      return Promise.reject(this.navigationError);
    }
    this.url = url;
    return Promise.resolve();
  }

  blur(): void {
    this.focused = false;
    this.emit("blur");
  }

  close(): void {
    this.closeCount += 1;
    if (!this.closeEmitsClosed) {
      return;
    }
    this.destroyed = true;
    this.emit("closed");
  }

  destroy(): void {
    this.destroyCount += 1;
    if (this.destroyed) {
      return;
    }
    this.destroyed = true;
    this.emit("closed");
  }

  setOverlayIcon(icon: unknown, description: string): void {
    this.overlayCalls.push({ icon, description });
  }

  setTitle(value: string): void {
    this.title = value;
  }

  flashFrame(flag: boolean): void {
    this.flashCalls.push(flag);
  }

  isDestroyed(): boolean {
    return this.destroyed;
  }

  isFocused(): boolean {
    return this.focused;
  }

  on(event: string, listener: (...args: unknown[]) => void): this {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), listener]);
    return this;
  }

  emit(event: string, ...args: unknown[]): void {
    for (const listener of this.handlers.get(event) ?? []) {
      listener(...args);
    }
  }
}

const desktopPaths: DesktopPaths = {
  schemaVersion: 1,
  desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
  resourcesRoot: "C:/Program Files/Vibelution/resources",
  workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
  userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
};

describe("Electron window provider state", () => {
  it("uses electron as the provider authority", () => {
    expect(closedWindowState("workbench")).toEqual({
      role: "workbench",
      provider: "electron",
      open: false,
      focused: false,
      windowId: 0,
      rendererProcessId: 0,
      url: ""
    });
  });

  it("reuses an open workbench window and focuses it", async () => {
    const windows: FakeWindow[] = [];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createWorkbenchWindow: (url) => {
        const window = new FakeWindow(42, url, 4242);
        windows.push(window);
        return window;
      },
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070)
    });

    const first = await provider.openOrFocusWorkbench();
    const second = await provider.openOrFocusWorkbench();

    expect(windows).toHaveLength(1);
    expect(windows[0].focusCount).toBe(2);
    expect(second).toEqual(first);
    expect(second).toMatchObject({
      role: "workbench",
      provider: "electron",
      open: true,
      focused: true,
      windowId: 42,
      rendererProcessId: 4242,
      url: "http://127.0.0.1:8000/"
    });
  });

  it("opens an isolated instance window without navigating the current workbench", async () => {
    const primary = new FakeWindow(42, "", 4242);
    const isolated = new FakeWindow(99, "", 9999);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8002", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: (url, _paths, options) => {
        if (String(url).includes(":8004")) {
          if (options?.title) {
            isolated.setTitle(options.title);
          }
          return isolated;
        }
        return primary;
      }
    });

    await provider.openOrFocusWorkbench("http://127.0.0.1:8002/");
    const instance = await provider.openOrFocusInstanceWorkbench({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8004/",
      title: "branch+task 台"
    });

    expect(primary.loadedUrls).toEqual(["http://127.0.0.1:8002/"]);
    expect(isolated.loadedUrls).toEqual(["http://127.0.0.1:8004/"]);
    expect(isolated.title).toBe("branch+task 台");
    expect(isolated.showCount).toBe(1);
    expect(instance).toMatchObject({
      open: true,
      instanceId: "worktree:task",
      title: "branch+task 台",
      url: "http://127.0.0.1:8004/",
      rendererProcessId: 9999
    });
    expect(provider.snapshot().workbench.url).toBe("http://127.0.0.1:8002/");

    await provider.closeInstanceWorkbench("worktree:task");
    expect(isolated.closeCount).toBe(1);
    expect(provider.snapshot().workbench.open).toBe(true);
  });

  it("navigates to a refreshed Workbench URL before revealing or reporting the window", async () => {
    const reports: Array<{ open: boolean; url: string }> = [];
    const workbenchWindow = new FakeWindow(42, "", 0);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      reportState: (state) => reports.push({ open: state.open, url: state.url })
    });

    const state = await provider.openOrFocusWorkbench("http://127.0.0.1:8002/");

    expect(workbenchWindow.loadedUrls).toEqual(["http://127.0.0.1:8002/"]);
    expect(workbenchWindow.showCount).toBe(1);
    expect(workbenchWindow.focusCount).toBe(1);
    expect(state).toMatchObject({
      role: "workbench",
      open: true,
      url: "http://127.0.0.1:8002/"
    });
    expect(reports).toEqual([{ open: true, url: "http://127.0.0.1:8002/" }]);
  });

  it("keeps a failed navigation hidden and permits the next open action to retry", async () => {
    const failedWindow = new FakeWindow(42, "", 0, true, new Error("ERR_CONNECTION_REFUSED"));
    const recoveredWindow = new FakeWindow(43, "", 4343);
    const factory = vi
      .fn<(url: string, paths: DesktopPaths) => FakeWindow>()
      .mockReturnValueOnce(failedWindow)
      .mockReturnValueOnce(recoveredWindow);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: factory
    });

    await expect(provider.openOrFocusWorkbench("http://127.0.0.1:8002/")).rejects.toThrow("ERR_CONNECTION_REFUSED");

    expect(failedWindow.showCount).toBe(0);
    expect(failedWindow.destroyCount).toBe(1);
    expect(provider.snapshot().workbench).toEqual(closedWindowState("workbench"));

    await expect(provider.openOrFocusWorkbench("http://127.0.0.1:8002/")).resolves.toMatchObject({
      open: true,
      url: "http://127.0.0.1:8002/"
    });
    expect(recoveredWindow.showCount).toBe(1);
    expect(factory).toHaveBeenCalledTimes(2);
  });

  it("cancels same-origin in-page workbench navigations after the first load", async () => {
    const workbenchWindow = new FakeWindow(42, "", 0);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8002", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow
    });

    await provider.openOrFocusWorkbench("http://127.0.0.1:8002/");
    const event = { preventDefault: vi.fn() };
    workbenchWindow.emit("webContents:will-navigate", event, "http://127.0.0.1:8002/teams");
    expect(event.preventDefault).toHaveBeenCalledTimes(1);

    event.preventDefault.mockClear();
    workbenchWindow.emit("webContents:will-navigate", event, "http://127.0.0.1:8002/");
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("does not report an optimistic closed state when BrowserWindow.close is cancelled", async () => {
    const reports: Array<{ open: boolean }> = [];
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242, false);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      reportState: (state) => {
        reports.push({ open: state.open });
      }
    });

    await provider.openOrFocusWorkbench();
    reports.length = 0;

    const stateAfterCloseRequest = await provider.closeWorkbench();

    expect(workbenchWindow.closeCount).toBe(1);
    expect(stateAfterCloseRequest.open).toBe(true);
    expect(reports).toEqual([]);

    workbenchWindow.emit("closed");

    expect(reports).toEqual([{ open: false }]);
  });

  it("intercepts a workbench X until the transactional close is explicitly authorized", async () => {
    const closeRequests: string[] = [];
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242, false);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      shouldInterceptWorkbenchClose: () => true,
      hungCloseDestroyAfterMs: 0,
      onWorkbenchCloseRequest: () => {
        closeRequests.push("workbench");
      }
    });
    await provider.openOrFocusWorkbench();

    const closeEvent = { preventDefault: vi.fn() };
    workbenchWindow.emit("close", closeEvent);

    expect(closeEvent.preventDefault).toHaveBeenCalledTimes(1);
    expect(closeRequests).toEqual(["workbench"]);
    expect(workbenchWindow.closeCount).toBe(0);
    expect(provider.isWorkbenchCloseInFlight()).toBe(true);

    await provider.approveWorkbenchCloseOnce();

    expect(workbenchWindow.closeCount).toBe(1);
    expect(workbenchWindow.destroyCount).toBe(1);
    expect(workbenchWindow.isDestroyed()).toBe(true);
    expect(provider.isWorkbenchCloseInFlight()).toBe(false);
  });

  it("does not start a Workbench close transaction after shell exit is approved", async () => {
    let shellExitApproved = false;
    const closeRequests: string[] = [];
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242, false);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      shouldInterceptWorkbenchClose: () => !shellExitApproved,
      onWorkbenchCloseRequest: () => {
        closeRequests.push("workbench");
      }
    });
    await provider.openOrFocusWorkbench();
    shellExitApproved = true;

    const closeEvent = { preventDefault: vi.fn() };
    workbenchWindow.emit("close", closeEvent);

    expect(closeEvent.preventDefault).not.toHaveBeenCalled();
    expect(closeRequests).toEqual([]);
    expect(provider.isWorkbenchCloseInFlight()).toBe(false);
  });

  it("destroys an authorized Workbench window when close is ignored by a hung renderer", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242, false);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      shouldInterceptWorkbenchClose: () => true,
      hungCloseDestroyAfterMs: 0
    });
    await provider.openOrFocusWorkbench();

    const state = await provider.approveWorkbenchCloseOnce();

    expect(workbenchWindow.closeCount).toBe(1);
    expect(workbenchWindow.destroyCount).toBe(1);
    expect(workbenchWindow.isDestroyed()).toBe(true);
    expect(state.open).toBe(false);
    expect(provider.snapshot().workbench.open).toBe(false);
  });

  it("does not let a programmatic Workbench close bypass the transactional interceptor", async () => {
    const closeRequests: string[] = [];
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242, false);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      shouldInterceptWorkbenchClose: () => true,
      onWorkbenchCloseRequest: () => {
        closeRequests.push("workbench");
      }
    });
    await provider.openOrFocusWorkbench();

    const state = await provider.closeWorkbench();

    expect(closeRequests).toEqual(["workbench"]);
    expect(workbenchWindow.closeCount).toBe(0);
    expect(state.open).toBe(true);
  });

  it("waits for the closed window state report before sending the final close callback", async () => {
    let releaseReport: (() => void) | null = null;
    let closeCallbacks = 0;
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      reportState: (state) => {
        if (!state.open) {
          return new Promise<void>((resolve) => {
            releaseReport = resolve;
          });
        }
      },
      onWorkbenchClosed: () => {
        closeCallbacks += 1;
      }
    });
    await provider.openOrFocusWorkbench();

    workbenchWindow.emit("closed");

    expect(closeCallbacks).toBe(0);
    releaseReport?.();
    await Promise.resolve();
    await Promise.resolve();

    expect(closeCallbacks).toBe(1);
  });

  it("still sends the final close callback when the closed window state report fails", async () => {
    let closeCallbacks = 0;
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      reportState: (state) => {
        if (!state.open) {
          return Promise.reject(new Error("launcher state report unavailable"));
        }
      },
      onWorkbenchClosed: () => {
        closeCallbacks += 1;
      }
    });
    await provider.openOrFocusWorkbench();

    workbenchWindow.emit("closed");
    await Promise.resolve();
    await Promise.resolve();

    expect(closeCallbacks).toBe(1);
  });

  it("reports Windows session-end signals without treating them as a confirmed window close", async () => {
    const sessionEndEvents: string[] = [];
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      onOsSessionEnd: (event, role) => sessionEndEvents.push(`${event}:${role}`)
    });

    await provider.openOrFocusWorkbench();
    workbenchWindow.emit("query-session-end");
    workbenchWindow.emit("session-end");

    expect(sessionEndEvents).toEqual(["query-session-end:workbench", "session-end:workbench"]);
    expect(provider.snapshot().workbench.open).toBe(true);
  });

  it("reuses an open launcher window and focuses it for public deep links", async () => {
    const windows: FakeWindow[] = [];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => {
        const window = new FakeWindow(7, url, 7070);
        windows.push(window);
        return window;
      },
      createWorkbenchWindow: (url) => new FakeWindow(42, url, 4242)
    });

    const first = await provider.openLauncher();
    const second = await provider.openLauncher();
    const [left, right] = await Promise.all([provider.openLauncher(), provider.openLauncher()]);

    expect(windows).toHaveLength(1);
    expect(windows[0].showCount).toBeGreaterThanOrEqual(3);
    expect(windows[0].focusCount).toBeGreaterThanOrEqual(3);
    expect(left).toEqual(right);
    expect(second).toEqual(first);
    expect(second).toMatchObject({
      role: "launcher",
      provider: "electron",
      open: true,
      focused: true,
      windowId: 7,
      rendererProcessId: 7070,
      url: "http://127.0.0.1:8765/launcher"
    });
  });

  it("restores a hidden or minimized launcher instead of creating a second window", async () => {
    const launcherWindow = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: () => launcherWindow,
      createWorkbenchWindow: (url) => new FakeWindow(42, url, 4242),
      shouldInterceptLauncherClose: () => true
    });

    await provider.openLauncher();
    launcherWindow.emit("close", { preventDefault: vi.fn() });
    launcherWindow.minimized = true;
    launcherWindow.showCount = 0;
    launcherWindow.focusCount = 0;
    launcherWindow.restoreCount = 0;

    const restored = await provider.openLauncher();

    expect(launcherWindow.hideCount).toBe(1);
    expect(launcherWindow.restoreCount).toBe(1);
    expect(launcherWindow.showCount).toBe(1);
    expect(launcherWindow.focusCount).toBe(1);
    expect(launcherWindow.isDestroyed()).toBe(false);
    expect(restored).toMatchObject({ role: "launcher", open: true, focused: true, windowId: 7 });
  });

  it("hides Launcher on X so the tray control center remains alive", async () => {
    const launcherWindow = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const reports: Array<{ role: string; open: boolean; focused: boolean }> = [];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: () => launcherWindow,
      createWorkbenchWindow: (url) => new FakeWindow(42, url, 4242),
      shouldInterceptLauncherClose: () => true,
      reportState: (state) => {
        reports.push({ role: state.role, open: state.open, focused: state.focused });
      },
    });
    await provider.openLauncher();
    reports.length = 0;

    const closeEvent = { preventDefault: vi.fn() };
    launcherWindow.emit("close", closeEvent);

    expect(closeEvent.preventDefault).toHaveBeenCalledTimes(1);
    expect(launcherWindow.hideCount).toBe(1);
    expect(launcherWindow.isDestroyed()).toBe(false);
    expect(reports).toEqual([{ role: "launcher", open: true, focused: false }]);
  });

  it("adopts one existing launcher window and destroys extras", async () => {
    const first = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const extra = new FakeWindow(8, "http://127.0.0.1:8765/launcher", 8080);
    let created = 0;
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => {
        created += 1;
        return new FakeWindow(9, url, 9090);
      },
      createWorkbenchWindow: (url) => new FakeWindow(42, url, 4242),
      listLauncherWindows: () => [first, extra]
    });

    const state = await provider.openLauncher();

    expect(created).toBe(0);
    expect(state.windowId).toBe(7);
    expect(first.showCount).toBe(1);
    expect(extra.destroyCount).toBe(1);
    expect(extra.isDestroyed()).toBe(true);
  });

  it("adopts one existing workbench window and destroys extras", async () => {
    const first = new FakeWindow(42, "http://127.0.0.1:8002/teams", 4242);
    const extra = new FakeWindow(43, "http://127.0.0.1:8002/chat", 4343);
    let created = 0;
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8002", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: (url) => {
        created += 1;
        return new FakeWindow(44, url, 4444);
      },
      listWorkbenchWindows: () => [first, extra].filter((window) => !window.isDestroyed())
    });

    const state = await provider.openOrFocusWorkbench("http://127.0.0.1:8002/");

    expect(created).toBe(0);
    expect(state.windowId).toBe(42);
    expect(first.loadedUrls).toEqual(["http://127.0.0.1:8002/"]);
    expect(extra.destroyCount).toBe(1);
    expect(extra.isDestroyed()).toBe(true);
    expect(provider.snapshot().workbench).toMatchObject({
      open: true,
      windowId: 42,
      url: "http://127.0.0.1:8002/"
    });
  });

  it("reports a leftover workbench window as open and closes it without creating another", async () => {
    const leftover = new FakeWindow(42, "http://127.0.0.1:8002/teams", 4242);
    const reports: Array<{ role: string; open: boolean; windowId?: number }> = [];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8002", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: (url) => new FakeWindow(99, url, 9999),
      listWorkbenchWindows: () => (leftover.isDestroyed() ? [] : [leftover]),
      reportState: (state) => reports.push({ role: state.role, open: state.open, windowId: state.windowId }),
      hungCloseDestroyAfterMs: 0
    });

    await provider.openLauncher();
    expect(provider.snapshot().workbench).toMatchObject({
      open: true,
      windowId: 42,
      url: "http://127.0.0.1:8002/teams"
    });
    expect(reports).toEqual(
      expect.arrayContaining([{ role: "workbench", open: true, windowId: 42 }])
    );

    await provider.approveWorkbenchCloseOnce();
    expect(leftover.isDestroyed()).toBe(true);
    expect(provider.snapshot().workbench.open).toBe(false);
  });

  it("does not destroy an isolated instance window while sweeping leftover workbench windows", async () => {
    const leftover = new FakeWindow(42, "http://127.0.0.1:8002/teams", 4242);
    const isolated = new FakeWindow(99, "http://127.0.0.1:8004/", 9999);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8002", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: (url, _paths, options) => {
        if (String(url).includes(":8004")) {
          if (options?.title) {
            isolated.setTitle(options.title);
          }
          return isolated;
        }
        return leftover;
      },
      listWorkbenchWindows: () => [leftover, isolated].filter((window) => !window.isDestroyed())
    });

    await provider.openOrFocusInstanceWorkbench({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8004/",
      title: "branch+task 台"
    });
    const state = await provider.openOrFocusWorkbench("http://127.0.0.1:8002/");

    expect(state.windowId).toBe(42);
    expect(isolated.isDestroyed()).toBe(false);
    expect(provider.snapshot().workbench.windowId).toBe(42);
  });

  it("treats a leftover workbench on a different loopback port as the live current window", async () => {
    const leftover = new FakeWindow(42, "http://127.0.0.1:8002/chat", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => new FakeWindow(99, "http://127.0.0.1:8000/", 9999),
      listWorkbenchWindows: (origin) =>
        [leftover].filter((window) => !window.isDestroyed() && isLiveWorkbenchWindowUrl(window.webContents.getURL(), origin))
    });

    await provider.openLauncher();
    expect(provider.snapshot().workbench).toMatchObject({
      open: true,
      windowId: 42,
      url: "http://127.0.0.1:8002/chat"
    });
  });

  it("keeps an owned workbench window when live listing later returns empty", async () => {
    const leftover = new FakeWindow(42, "http://127.0.0.1:8002/chat", 4242);
    let live: FakeWindow[] = [leftover];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => new FakeWindow(99, "http://127.0.0.1:8000/", 9999),
      listWorkbenchWindows: (origin) =>
        live.filter((window) => !window.isDestroyed() && isLiveWorkbenchWindowUrl(window.webContents.getURL(), origin))
    });

    await provider.openLauncher();
    expect(provider.snapshot().workbench.windowId).toBe(42);
    live = [];
    expect(provider.snapshot().workbench).toMatchObject({
      open: true,
      windowId: 42,
      url: "http://127.0.0.1:8002/chat"
    });
  });

  it("closes only Workbench while Launcher remains available", async () => {
    const launcherWindow = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242, false);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: () => launcherWindow,
      createWorkbenchWindow: () => workbenchWindow,
      shouldInterceptLauncherClose: () => true,
      shouldInterceptWorkbenchClose: () => true,
      hungCloseDestroyAfterMs: 0
    });
    await provider.openLauncher();
    await provider.openOrFocusWorkbench();

    workbenchWindow.emit("close", { preventDefault: vi.fn() });
    await provider.approveWorkbenchCloseOnce();

    expect(workbenchWindow.closeCount).toBe(1);
    expect(workbenchWindow.isDestroyed()).toBe(true);
    expect(launcherWindow.isDestroyed()).toBe(false);
    const launcherState = await provider.openLauncher();
    expect(launcherState).toMatchObject({ role: "launcher", open: true, focused: true });
  });

  it("reports workbench focus without exposing the raw BrowserWindow", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow
    });

    expect(provider.isWorkbenchFocused()).toBe(false);

    await provider.openOrFocusWorkbench();

    expect(provider.isWorkbenchFocused()).toBe(true);

    workbenchWindow.blur();

    expect(provider.isWorkbenchFocused()).toBe(false);
  });

  it("sends notification click payloads to the workbench renderer", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow
    });

    expect(provider.sendToWorkbench("launcher:conversation-notification-opened", { sessionId: "session-1" })).toBe(false);

    await provider.openOrFocusWorkbench();

    expect(provider.sendToWorkbench("launcher:conversation-notification-opened", {
      schemaVersion: 1,
      sessionId: "session-1"
    })).toBe(true);
    expect(workbenchWindow.sentIpc).toEqual([
      {
        channel: "launcher:conversation-notification-opened",
        payload: { schemaVersion: 1, sessionId: "session-1" }
      }
    ]);
  });

  it("applies and clears workbench taskbar attention", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow
    });
    await provider.openOrFocusWorkbench();

    const overlayIcon = { marker: "badge-1" };
    provider.setWorkbenchAttention({ unreadCount: 1, overlayIcon, description: "1 completed conversation", flash: true });

    expect(workbenchWindow.overlayCalls).toEqual([{ icon: overlayIcon, description: "1 completed conversation" }]);
    expect(workbenchWindow.flashCalls).toEqual([true]);

    provider.setWorkbenchAttention({ unreadCount: 0 });

    expect(workbenchWindow.overlayCalls.at(-1)).toEqual({ icon: null, description: "" });
    expect(workbenchWindow.flashCalls.at(-1)).toBe(false);
  });

  it("clears workbench attention when the workbench regains focus", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow
    });

    await provider.openOrFocusWorkbench();
    provider.setWorkbenchAttention({ unreadCount: 3, overlayIcon: { marker: "badge-3" }, description: "3 completed conversations", flash: true });

    workbenchWindow.emit("focus");

    expect(workbenchWindow.overlayCalls.at(-1)).toEqual({ icon: null, description: "" });
    expect(workbenchWindow.flashCalls.at(-1)).toBe(false);
  });

  it("invokes the focus attention-clear callback when the workbench regains focus", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const onWorkbenchFocusAttentionClear = vi.fn();
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
      onWorkbenchFocusAttentionClear,
    });

    await provider.openOrFocusWorkbench();
    workbenchWindow.emit("focus");

    expect(onWorkbenchFocusAttentionClear).toHaveBeenCalledTimes(1);
  });
});

describe("Launcher new-window requests", () => {
  it("routes a launcher request for the managed workbench URL into the managed workbench window", async () => {
    const launcherWindow = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const workbenchWindows: FakeWindow[] = [];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: () => launcherWindow,
      createWorkbenchWindow: (url) => {
        const window = new FakeWindow(42, url, 4242);
        workbenchWindows.push(window);
        return window;
      }
    });
    await provider.openLauncher();

    expect(launcherWindow.windowOpenHandler).not.toBeNull();
    const decision = launcherWindow.openRequest("http://127.0.0.1:8000/");

    expect(decision).toEqual({ action: "deny" });
    await vi.waitFor(() => expect(workbenchWindows).toHaveLength(1));
    expect(provider.isWorkbenchFocused()).toBe(true);
  });

  it("delegates managed workbench links to the lifecycle-owned open request", async () => {
    const launcherWindow = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const createWorkbenchWindow = vi.fn();
    const onWorkbenchOpenRequest = vi.fn(async () => undefined);
    const provider = new ElectronWindowProvider(
      desktopPaths,
      "http://127.0.0.1:8765/launcher",
      "http://127.0.0.1:8000",
      {
        createLauncherWindow: () => launcherWindow,
        createWorkbenchWindow,
        onWorkbenchOpenRequest
      }
    );
    await provider.openLauncher();

    expect(launcherWindow.openRequest("http://127.0.0.1:8000/")).toEqual({ action: "deny" });
    await vi.waitFor(() => expect(onWorkbenchOpenRequest).toHaveBeenCalledOnce());
    expect(createWorkbenchWindow).not.toHaveBeenCalled();
  });

  it("reuses the managed workbench window for repeated workbench-origin requests", async () => {
    const launcherWindow = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const workbenchWindows: FakeWindow[] = [];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: () => launcherWindow,
      createWorkbenchWindow: (url) => {
        const window = new FakeWindow(42, url, 4242);
        workbenchWindows.push(window);
        return window;
      }
    });
    await provider.openLauncher();

    launcherWindow.openRequest("http://127.0.0.1:8000/");
    await vi.waitFor(() => expect(workbenchWindows).toHaveLength(1));
    const focusCountAfterFirst = workbenchWindows[0].focusCount;

    const decision = launcherWindow.openRequest("http://127.0.0.1:8000/some/path");

    expect(decision).toEqual({ action: "deny" });
    await vi.waitFor(() => expect(workbenchWindows[0].focusCount).toBeGreaterThan(focusCountAfterFirst));
    expect(workbenchWindows).toHaveLength(1);
  });

  it("denies launcher new-window requests outside the workbench origin without opening a window", async () => {
    const launcherWindow = new FakeWindow(7, "http://127.0.0.1:8765/launcher", 7070);
    const workbenchWindows: FakeWindow[] = [];
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: () => launcherWindow,
      createWorkbenchWindow: (url) => {
        const window = new FakeWindow(42, url, 4242);
        workbenchWindows.push(window);
        return window;
      }
    });
    await provider.openLauncher();

    expect(launcherWindow.openRequest("https://example.com/open")).toEqual({ action: "deny" });
    expect(launcherWindow.openRequest("http://127.0.0.1:9000/")).toEqual({ action: "deny" });
    expect(() => launcherWindow.openRequest("not a url")).not.toThrow();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(workbenchWindows).toHaveLength(0);
    expect(provider.isWorkbenchFocused()).toBe(false);
  });

  it("denies workbench window.open and reuses the current window", async () => {
    const workbenchWindow = new FakeWindow(42, "", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8002", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow
    });

    await provider.openOrFocusWorkbench("http://127.0.0.1:8002/");
    const focusCount = workbenchWindow.focusCount;

    expect(workbenchWindow.windowOpenHandler).not.toBeNull();
    expect(workbenchWindow.openRequest("http://127.0.0.1:8002/teams")).toEqual({ action: "deny" });
    await vi.waitFor(() => expect(workbenchWindow.focusCount).toBeGreaterThan(focusCount));
    expect(workbenchWindow.openRequest("https://example.com/open")).toEqual({ action: "deny" });
  });
});

describe("Electron URL policy", () => {
  it("allows local HTTP URLs from the expected origin", () => {
    expect(assertLocalHttpUrl("http://127.0.0.1:8765/launcher", "http://127.0.0.1:8765")).toBe(
      "http://127.0.0.1:8765/launcher"
    );
  });

  it("blocks non-local or unexpected origins", () => {
    expect(() => assertLocalHttpUrl("https://example.com", "https://example.com")).toThrow("blocked non-local URL");
    expect(() => assertLocalHttpUrl("http://127.0.0.1:8765/launcher", "http://127.0.0.1:9000")).toThrow(
      "blocked unexpected origin"
    );
  });
});

describe("resolveLauncherWindowUrl", () => {
  it("defaults the launcher window to the packaged app protocol", () => {
    expect(resolveLauncherWindowUrl({ NODE_ENV: "production" } as NodeJS.ProcessEnv)).toBe(
      "vibelution-launcher://launcher/launcher"
    );
  });

  it("accepts an explicit development override", () => {
    expect(resolveLauncherWindowUrl({ VIBELUTION_LAUNCHER_URL: "http://127.0.0.1:9000/launcher" } as NodeJS.ProcessEnv)).toBe(
      "http://127.0.0.1:9000/launcher"
    );
  });
});

describe("resolveWorkbenchUrl", () => {
  it("prefers a live status URL over the development default", () => {
    expect(
      resolveWorkbenchUrl({ NODE_ENV: "development" } as NodeJS.ProcessEnv, "http://127.0.0.1:8002/")
    ).toBe("http://127.0.0.1:8002/");
  });

  it("does not silently hard-code a production port", () => {
    expect(() => resolveWorkbenchUrl({ NODE_ENV: "production" } as NodeJS.ProcessEnv)).toThrow(
      "Workbench URL is not resolved"
    );
  });
});

describe("IPC channels", () => {
  it("keeps the bridge narrow", () => {
    expect(Object.keys(IPC_CHANNELS).sort()).toEqual([
      "conversationNotificationOpened",
      "focusWorkbenchWindow",
      "getDesktopShellSummary",
      "getLauncherState",
      "getVersion",
      "launcherInvoke",
      "launcherStateChanged",
      "notifyConversationCompleted",
      "refreshLauncherState",
      "requestDesktopShellExit"
    ]);
  });

  it("rejects sender frames outside the launcher and workbench origins", () => {
    expect(() =>
      assertTrustedIpcSender(fakeIpcEvent("http://127.0.0.1:8765/launcher"), [
        "http://127.0.0.1:8765",
        "http://127.0.0.1:8000"
      ])
    ).not.toThrow();
    expect(() =>
      assertTrustedIpcSender(fakeIpcEvent("https://example.com/launcher"), [
        "http://127.0.0.1:8765",
        "http://127.0.0.1:8000"
      ])
    ).toThrow("blocked ipc sender origin: https://example.com");
    expect(() =>
      assertTrustedIpcSender({ senderFrame: null } as IpcMainInvokeEvent, ["http://127.0.0.1:8765"])
    ).toThrow("blocked ipc sender origin: <unknown>");
  });
});

describe("shouldCancelWorkbenchInPageNavigation", () => {
  it("allows the first load, reloads, and cross-origin navigations", () => {
    expect(
      shouldCancelWorkbenchInPageNavigation({
        readyUrl: null,
        currentUrl: "http://127.0.0.1:8002/",
        nextUrl: "http://127.0.0.1:8002/teams"
      })
    ).toBe(false);
    expect(
      shouldCancelWorkbenchInPageNavigation({
        readyUrl: "http://127.0.0.1:8002/",
        currentUrl: "http://127.0.0.1:8002/",
        nextUrl: "http://127.0.0.1:8002/"
      })
    ).toBe(false);
    expect(
      shouldCancelWorkbenchInPageNavigation({
        readyUrl: "http://127.0.0.1:8002/",
        currentUrl: "http://127.0.0.1:8002/",
        nextUrl: "https://example.com/teams"
      })
    ).toBe(false);
  });

  it("cancels same-origin path changes that would replace the SPA document", () => {
    expect(
      shouldCancelWorkbenchInPageNavigation({
        readyUrl: "http://127.0.0.1:8002/",
        currentUrl: "http://127.0.0.1:8002/",
        nextUrl: "http://127.0.0.1:8002/teams"
      })
    ).toBe(true);
  });
});

function fakeIpcEvent(url: string): IpcMainInvokeEvent {
  return {
    senderFrame: { url }
  } as IpcMainInvokeEvent;
}
