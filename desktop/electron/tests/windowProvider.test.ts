import { describe, expect, it } from "vitest";
import { assertLocalHttpUrl } from "../src/security/urlPolicy.js";
import { resolveLauncherUrl } from "../src/windows/windowUrlResolver.js";
import { ElectronWindowProvider, type ElectronWindowLike } from "../src/windows/electronWindowProvider.js";
import { closedWindowState } from "../src/windows/windowProviderTypes.js";
import type { DesktopPaths } from "../src/paths.js";

class FakeWindow implements ElectronWindowLike {
  readonly id: number;
  readonly webContents: ElectronWindowLike["webContents"];
  focusCount = 0;
  closeCount = 0;
  private destroyed = false;
  private focused = false;
  private handlers = new Map<string, Array<() => void>>();

  constructor(id: number, private readonly url: string, rendererProcessId: number) {
    this.id = id;
    this.webContents = {
      getOSProcessId: () => rendererProcessId,
      getURL: () => this.url,
      on: (event, listener) => {
        this.on(`webContents:${event}`, listener);
        return this.webContents;
      }
    };
  }

  focus(): void {
    this.focusCount += 1;
    this.focused = true;
  }

  close(): void {
    this.closeCount += 1;
    this.destroyed = true;
    this.emit("closed");
  }

  isDestroyed(): boolean {
    return this.destroyed;
  }

  isFocused(): boolean {
    return this.focused;
  }

  on(event: string, listener: () => void): this {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), listener]);
    return this;
  }

  emit(event: string): void {
    for (const listener of this.handlers.get(event) ?? []) {
      listener();
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

describe("resolveLauncherUrl", () => {
  it("does not silently hard-code a production port", () => {
    expect(() => resolveLauncherUrl({ NODE_ENV: "production" } as NodeJS.ProcessEnv)).toThrow(
      "Launcher URL is not resolved"
    );
  });

  it("accepts an explicit development override", () => {
    expect(resolveLauncherUrl({ VIBELUTION_LAUNCHER_URL: "http://127.0.0.1:9000/launcher" } as NodeJS.ProcessEnv)).toBe(
      "http://127.0.0.1:9000/launcher"
    );
  });
});
