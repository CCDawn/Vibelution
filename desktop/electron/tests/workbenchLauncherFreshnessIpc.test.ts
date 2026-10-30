import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { fileURLToPath } from "node:url";
import type { IpcMainInvokeEvent } from "electron";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";
import { assertTrustedIpcSender } from "../src/security/ipcSenderValidation.js";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const ipcSource = readFileSync(fileURLToPath(new URL("../src/ipc.ts", import.meta.url)), "utf8");

type InvokeHandler = (event: IpcMainInvokeEvent) => Promise<unknown>;

function extractIpcHandler(channel: string): string {
  const start = mainSource.indexOf(`ipcMain.handle(IPC_CHANNELS.${channel}`);
  expect(start, `handler for ${channel}`).toBeGreaterThanOrEqual(0);
  const end = mainSource.indexOf("\n});", start);
  expect(end, `end of handler for ${channel}`).toBeGreaterThan(start);
  return mainSource.slice(start, end + "\n});".length);
}

function launcherWindowHandlers(bindings: {
  currentLauncherUpdateFreshness: () => Promise<unknown>;
  openLauncher: () => Promise<unknown>;
}) {
  const handlers = new Map<string, InvokeHandler>();
  const source = [extractIpcHandler("getLauncherFreshness"), extractIpcHandler("showLauncherWindow")].join("\n");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 }
  }).outputText;
  runInNewContext(compiled, {
    IPC_CHANNELS: {
      getLauncherFreshness: "launcher:get-freshness",
      showLauncherWindow: "launcher:show-window"
    },
    ipcMain: {
      handle: (channel: string, handler: InvokeHandler) => handlers.set(channel, handler)
    },
    assertTrustedIpcSender,
    trustedIpcOrigins: () => ["vibelution-launcher://launcher", "http://127.0.0.1:8000"],
    currentLauncherUpdateFreshness: bindings.currentLauncherUpdateFreshness,
    windowProvider: bindings.openLauncher
      ? { openLauncher: bindings.openLauncher }
      : null
  });
  return handlers;
}

function trustedIpcOriginsForTest(event?: IpcMainInvokeEvent, trustedWorkbenchOrigin = vi.fn((): string | null => null)): string[] {
  const start = mainSource.indexOf("function trustedIpcOrigins(event?: IpcMainInvokeEvent): string[] {");
  const end = mainSource.indexOf("\n}\n\nasync function stopMainRuntimeForApprovedShutdown", start);
  expect(start).toBeGreaterThanOrEqual(0);
  expect(end).toBeGreaterThan(start);
  const source = mainSource.slice(start, end + 2);
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 }
  }).outputText;
  return runInNewContext(`${compiled}\ntrustedIpcOrigins(event)`, {
    event,
    windowProvider: { trustedWorkbenchOrigin },
    URL,
    desktopEnvironment: () => ({}),
    currentWorkbenchUrl: "http://127.0.0.1:8000/",
    resolveWorkbenchUrl: () => "http://127.0.0.1:8000/",
    launcherBootstrap: { workbenchUrl: "http://127.0.0.1:8000/" },
    resolveLauncherWindowUrl: () => "vibelution-launcher://launcher/launcher",
    launcherAppOriginFor: (rawUrl: string) => {
      const url = new URL(rawUrl);
      return `${url.protocol}//${url.host}`;
    }
  }) as string[];
}

function eventFor(url: string): IpcMainInvokeEvent {
  return { senderFrame: { url } } as unknown as IpcMainInvokeEvent;
}

describe("workbench Launcher awareness IPC", () => {
  it("adds a branch origin only for its registered main-frame sender", () => {
    const frame = { url: "http://127.0.0.1:8001/chat" };
    const event = { senderFrame: frame, sender: { mainFrame: frame } } as unknown as IpcMainInvokeEvent;
    const lookup = vi.fn(() => "http://127.0.0.1:8001");
    const origins = trustedIpcOriginsForTest(event, lookup);
    expect(() => assertTrustedIpcSender(event, origins)).not.toThrow();
    expect(lookup).toHaveBeenCalledWith(event.sender, frame.url);
    expect(() => assertTrustedIpcSender(event, trustedIpcOriginsForTest(event))).toThrow("blocked ipc sender origin");
    const subframe = { ...event, senderFrame: { url: frame.url } } as unknown as IpcMainInvokeEvent;
    lookup.mockClear();
    expect(() => assertTrustedIpcSender(subframe, trustedIpcOriginsForTest(subframe, lookup))).toThrow("blocked ipc sender origin");
    expect(lookup).not.toHaveBeenCalled();
    for (const channel of ["getDesktopShellSummary", "notifyConversationCompleted"]) {
      expect(extractIpcHandler(channel)).toContain("assertTrustedIpcSender(event, trustedIpcOrigins(event))");
    }
    for (const channel of ["launcherInvoke", "getLauncherState", "refreshLauncherState"]) {
      expect(extractIpcHandler(channel)).toContain("isTrustedLauncherControlFrame(event)");
    }
  });
  it("exposes only the two narrow Launcher awareness methods on main workbench preload", () => {
    expect(ipcSource).toContain('getLauncherFreshness: "launcher:get-freshness"');
    expect(ipcSource).toContain('showLauncherWindow: "launcher:show-window"');

    const workbenchStart = preloadSource.indexOf("...(!isLauncherControlWindow && !isDesktopPetWindow");
    const workbenchEnd = preloadSource.indexOf("} : {})", workbenchStart);
    const workbenchBranch = preloadSource.slice(workbenchStart, workbenchEnd);
    expect(workbenchBranch).toContain("getLauncherFreshness: () => ipcRenderer.invoke(IPC_CHANNELS.getLauncherFreshness)");
    expect(workbenchBranch).toContain("showLauncherWindow: () => ipcRenderer.invoke(IPC_CHANNELS.showLauncherWindow)");

    const launcherStart = preloadSource.indexOf("...(isLauncherControlWindow");
    const launcherEnd = preloadSource.indexOf("} : {})", launcherStart);
    expect(preloadSource.slice(launcherStart, launcherEnd)).not.toContain("getLauncherFreshness");
    expect(preloadSource.slice(launcherStart, launcherEnd)).not.toContain("showLauncherWindow");
  });

  it("serves freshness read-only to trusted workbench origins and rejects external origins", async () => {
    const allowedOrigins = trustedIpcOriginsForTest();
    expect(allowedOrigins).toEqual(["vibelution-launcher://launcher", "http://127.0.0.1:8000"]);
    const freshness = { current: false, shellStale: true, shellReason: "frontend_release_mismatch" };
    const readFreshness = vi.fn(async () => freshness);
    const openLauncher = vi.fn(async () => ({ role: "launcher", open: true }));
    const handlers = launcherWindowHandlers({ currentLauncherUpdateFreshness: readFreshness, openLauncher });
    const freshnessHandler = handlers.get("launcher:get-freshness");
    expect(freshnessHandler).toBeDefined();

    await expect(freshnessHandler!(eventFor("http://127.0.0.1:8000/finance"))).resolves.toBe(freshness);
    await expect(freshnessHandler!(eventFor("vibelution-launcher://launcher/launcher"))).resolves.toBe(freshness);
    expect(readFreshness).toHaveBeenCalledTimes(2);
    expect(openLauncher).not.toHaveBeenCalled();

    await expect(freshnessHandler!(eventFor("https://example.com/"))).rejects.toThrow("blocked ipc sender origin");
    expect(readFreshness).toHaveBeenCalledTimes(2);

    const body = extractIpcHandler("getLauncherFreshness");
    expect(body).toContain("assertTrustedIpcSender(event, trustedIpcOrigins(event))");
    expect(body).toContain("currentLauncherUpdateFreshness()");
    expect(body).not.toContain("resolveLauncherIpcHost");
    expect(body).not.toContain("orchestrateLauncherLifecycle");
  });

  it("opens or focuses the existing Launcher surface without adding lifecycle control", async () => {
    const freshness = vi.fn(async () => ({ current: true }));
    const openedState = { role: "launcher", open: true, focused: true };
    const openLauncher = vi.fn(async () => openedState);
    const handlers = launcherWindowHandlers({ currentLauncherUpdateFreshness: freshness, openLauncher });
    const showLauncherHandler = handlers.get("launcher:show-window");
    expect(showLauncherHandler).toBeDefined();

    await expect(showLauncherHandler!(eventFor("http://127.0.0.1:8000/"))).resolves.toBe(openedState);
    expect(openLauncher).toHaveBeenCalledOnce();
    expect(freshness).not.toHaveBeenCalled();

    const body = extractIpcHandler("showLauncherWindow");
    expect(body).toContain("assertTrustedIpcSender(event, trustedIpcOrigins(event))");
    expect(body).toContain("windowProvider.openLauncher()");
    expect(body).not.toContain("resolveLauncherIpcHost");
    expect(body).not.toContain("orchestrateLauncherLifecycle");
  });
});
