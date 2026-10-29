import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";
import { desktopPetWindowExpandedBounds } from "../src/windows/petWindowBounds.js";
import { isDesktopPetWindowUrl } from "../src/windows/petWindow.js";
import { assertTrustedIpcSender } from "../src/security/ipcSenderValidation.js";
import { ProjectAdmission } from "../src/lifecycle/projectAdmission.js";

vi.mock("electron", () => ({}));

const ipcSource = readFileSync(fileURLToPath(new URL("../src/ipc.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

function resizeHandler(ownerDelivery = true, themeSender = false) {
  const guardStart = mainSource.indexOf("function assertDesktopPetIpcSender(");
  const guardEnd = mainSource.indexOf("\nipcMain.handle(IPC_CHANNELS.setDesktopPetExpanded", guardStart);
  const resizeEnd = mainSource.indexOf("\n});", guardEnd) + "\n});".length;
  const openStart = mainSource.indexOf("ipcMain.handle(IPC_CHANNELS.openConversationFromPet");
  const openEnd = mainSource.indexOf("\n});", openStart) + "\n});".length;
  const source = mainSource.slice(guardStart, resizeEnd) + "\n" + mainSource.slice(openStart, openEnd);
  let handler: (event: unknown, expanded: unknown) => unknown = () => undefined;
  let contextHandler: (event: unknown) => unknown = () => undefined;
  let openHandler: (event: unknown, sessionId: unknown) => Promise<unknown> = async () => undefined;
  const sendToWorkbench = vi.fn(() => true);
  const focusAndSendToWorkbenchOrigin = vi.fn(() => ownerDelivery);
  const setBounds = vi.fn();
  const window = { getBounds: () => ({ x: 500, y: 600, width: 300, height: 330 }), isDestroyed: () => false, setBounds };
  const pet = { open: true, url: "http://127.0.0.1:8001/desktop-assistant" };
  const admission = new ProjectAdmission();
  runInNewContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, {
    URL,
    withProjectAdmission: (root: () => string, work: Parameters<ProjectAdmission["observe"]>[1]) => admission.observe(root, work),
    registeredAdmissionRoot: (root: string) => root,
    instanceAdmissionRoot: (_instanceId: string) => "C:/pet-project",
    createDesktopPathsForApp: () => ({ workspaceRoot: "C:/pet-project" }),
    IPC_CHANNELS: { setDesktopPetExpanded: "pet:window-expanded", getDesktopAssistantContext: "pet:assistant-context",
      openConversationFromPet: "pet:open-conversation", conversationNotificationOpened: "conversation:opened" },
    ipcMain: { handle: (channel: string, callback: typeof handler) => {
      if (channel === "pet:window-expanded") handler = callback;
      else if (channel === "pet:assistant-context") contextHandler = callback as typeof contextHandler;
      else openHandler = callback as typeof openHandler;
    } },
    windowProvider: { snapshot: () => ({ pet, workbench: { open: true, url: pet.url } }), instanceWindowStates: () => [], focusWorkbench: async () => ({ open: true }), sendToWorkbench, focusAndSendToWorkbenchOrigin },
    launcherAssistantWindow: { isThemeSender: () => themeSender },
    trustedIpcOrigins: () => ["http://127.0.0.1:8000"],
    assertTrustedIpcSender,
    identifyDebugWindow: (pid: number) => ({ role: pid === 9 ? "desktop-pet" : "main-workbench" }),
    isDesktopPetWindowUrl,
    BrowserWindow: { fromWebContents: () => window },
    screen: { getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 1000, height: 900 } }) },
    desktopPetWindowExpandedBounds,
    activeDesktopPetWindowDrag: {},
  });
  const frame = { url: pet.url };
  const event = { senderFrame: frame, sender: { mainFrame: frame, getOSProcessId: () => 9 } };
  return { handler, contextHandler, openHandler, sendToWorkbench, focusAndSendToWorkbenchOrigin, setBounds, event };
}

describe("desktop pet fixed-bounds drag IPC", () => {
  it("marks assistant conversation navigation from the verified source while preserving pet payloads", async () => {
    const { openHandler, sendToWorkbench, focusAndSendToWorkbenchOrigin, event } = resizeHandler();
    const opening = openHandler(event, "session-owned");
    event.senderFrame.url = "http://127.0.0.1:8001/desktop-pet";
    await expect(opening).resolves.toEqual({ schemaVersion: 1, opened: true });
    expect(focusAndSendToWorkbenchOrigin).toHaveBeenCalledWith("http://127.0.0.1:8001", "conversation:opened", { schemaVersion: 1, sessionId: "session-owned", source: "desktop-assistant" });
    expect(sendToWorkbench).not.toHaveBeenCalled();
    await openHandler(event, "session-old-pet");
    expect(sendToWorkbench).toHaveBeenLastCalledWith("conversation:opened", { schemaVersion: 1, sessionId: "session-old-pet" });
  });
  it("does not deliver an assistant session to main when no matching workbench owner exists", async () => {
    const { openHandler, sendToWorkbench, event } = resizeHandler(false);
    await expect(openHandler(event, "session-foreign")).resolves.toEqual({ schemaVersion: 1, opened: false });
    expect(sendToWorkbench).not.toHaveBeenCalled();
  });
  it("returns native assistant context only for the owned assistant route", () => {
    const { contextHandler, event } = resizeHandler();
    expect(contextHandler(event)).toEqual({ role: "desktop-assistant", mode: "assistant" });
    event.senderFrame.url = "http://127.0.0.1:8001/desktop-pet";
    expect(() => contextHandler(event)).toThrow("blocked desktop assistant context sender");
    event.senderFrame.url = "http://127.0.0.1:8001/desktop-assistant/nested";
    expect(() => contextHandler(event)).toThrow("blocked desktop pet ipc sender");
    event.senderFrame.url = "http://127.0.0.1:8001/desktop-assistant";
    expect(() => contextHandler({ ...event, sender: { ...event.sender, getOSProcessId: () => 10 } })).toThrow("blocked desktop pet ipc sender");
  });
  it("executes bounded resize for the owned branch pet and rejects other frames, roles and free bounds", () => {
    const { handler, setBounds, event } = resizeHandler();
    expect(handler(event, true)).toEqual({ expanded: true, width: 400, height: 530 });
    expect(setBounds).toHaveBeenCalledWith({ x: 500, y: 370, width: 400, height: 530 }, false);
    expect(() => handler(event, { width: 3000, height: 3000 })).toThrow("Invalid desktop pet expanded state");
    expect(() => handler({ ...event, senderFrame: { url: event.senderFrame.url } }, false)).toThrow("blocked desktop pet ipc sender");
    expect(() => handler({ ...event, sender: { ...event.sender, getOSProcessId: () => 10 } }, false)).toThrow("blocked desktop pet ipc sender");
    expect(() => handler({ ...event, senderFrame: { url: "https://evil.test/desktop-assistant" } }, false)).toThrow("origin");
    expect(setBounds).toHaveBeenCalledTimes(1);
  });
  it("admits the unified launcher assistant main frame through the theme sender identity", () => {
    const assistantFrame = { url: "http://127.0.0.1:8001/launcher-assistant" };
    const assistantEvent = { senderFrame: assistantFrame, sender: { mainFrame: assistantFrame, getOSProcessId: () => 10 } };
    const admitted = resizeHandler(true, true);
    expect(admitted.handler(assistantEvent, true)).toEqual({ expanded: true, width: 400, height: 530 });
    expect(admitted.setBounds).toHaveBeenCalledTimes(1);
    expect(() => resizeHandler(true, false).handler(assistantEvent, true)).toThrow("blocked desktop pet ipc sender");
  });
  it("exposes drag operations only through the desktop-pet preload branch", () => {
    expect(ipcSource).toContain('beginDesktopPetWindowDrag: "pet:window-drag-begin"');
    expect(ipcSource).toContain('moveDesktopPetWindowDrag: "pet:window-drag-move"');
    expect(ipcSource).toContain('endDesktopPetWindowDrag: "pet:window-drag-end"');
    expect(preloadSource).toContain("...(isDesktopPetWindow");
    expect(preloadSource).toContain("ipcRenderer.send(IPC_CHANNELS.moveDesktopPetWindowDrag, point)");
  });

  it("moves the owning BrowserWindow with fixed bounds in the main process", () => {
    expect(mainSource).toContain("BrowserWindow.fromWebContents(event.sender)");
    expect(mainSource).toContain("const { x, y, width, height } = window.getBounds()");
    expect(mainSource).toContain("desktopPetWindowExpandedBounds(current, screen.getDisplayMatching(current).workArea, expanded)");
    expect(mainSource).not.toContain("beginDesktopPetWindowDrag(rawPoint, window.getBounds())");
    expect(mainSource).toContain("window.setBounds(desktopPetWindowBoundsAt(active.drag, rawPoint), false)");
    expect(mainSource).not.toContain("window.moveBy(update.delta.screenX");
  });
  it("restricts resizing to boolean presets from the registered pet main frame", () => {
    expect(ipcSource).toContain('setDesktopPetExpanded: "pet:window-expanded"');
    // The pet expand channel may only be exposed by the desktop-pet branch and
    // the unified launcher-assistant branch that reuses the pet IPC surface.
    const assistantBranchStart = preloadSource.indexOf("if (isLauncherAssistantWindow)");
    const assistantBranchEnd = preloadSource.indexOf("if (!isLauncherAssistantWindow)");
    const petBranchStart = preloadSource.indexOf("...(isDesktopPetWindow");
    expect(preloadSource.slice(petBranchStart)).toContain("ipcRenderer.invoke(IPC_CHANNELS.setDesktopPetExpanded, expanded)");
    expect(preloadSource.slice(assistantBranchStart, assistantBranchEnd)).toContain("ipcRenderer.invoke(IPC_CHANNELS.setDesktopPetExpanded, expanded)");
    expect(preloadSource.slice(0, assistantBranchStart)).not.toContain("setDesktopPetExpanded");
    expect(preloadSource.slice(assistantBranchEnd, petBranchStart)).not.toContain("setDesktopPetExpanded");
    expect(mainSource).toContain('identity.role !== "desktop-pet"');
    expect(mainSource).toContain("event.senderFrame !== event.sender.mainFrame");
    expect(mainSource).toContain('typeof expanded !== "boolean"');
  });
});
