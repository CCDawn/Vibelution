import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";
import { assertTrustedIpcSender } from "../src/security/ipcSenderValidation.js";
import { ProjectAdmission } from "../src/lifecycle/projectAdmission.js";

vi.mock("electron", () => ({}));

const ipcSource = readFileSync(fileURLToPath(new URL("../src/ipc.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

function petIpcHandlers(themeSender = false) {
  const guardStart = mainSource.indexOf("function assertDesktopPetIpcSender(");
  const guardEnd = mainSource.indexOf("\nfunction desktopPetWindowFromEvent", guardStart);
  const openStart = mainSource.indexOf("ipcMain.handle(IPC_CHANNELS.openConversationFromPet");
  const openEnd = mainSource.indexOf("\n});", openStart) + "\n});".length;
  const source = mainSource.slice(guardStart, guardEnd) + "\n" + mainSource.slice(openStart, openEnd);
  let openHandler: (event: unknown, sessionId: unknown) => Promise<unknown> = async () => undefined;
  const sendToWorkbench = vi.fn(() => true);
  const admission = new ProjectAdmission();
  runInNewContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, {
    URL,
    withProjectAdmission: (root: () => string, work: Parameters<ProjectAdmission["observe"]>[1]) => admission.observe(root, work),
    registeredAdmissionRoot: (root: string) => root,
    instanceAdmissionRoot: (_instanceId: string) => "C:/pet-project",
    createDesktopPathsForApp: () => ({ workspaceRoot: "C:/pet-project" }),
    IPC_CHANNELS: { openConversationFromPet: "pet:open-conversation", conversationNotificationOpened: "conversation:opened" },
    ipcMain: { handle: (channel: string, callback: unknown) => {
      openHandler = callback as typeof openHandler;
    } },
    windowProvider: { snapshot: () => ({ workbench: { open: true, url: "http://127.0.0.1:8000/" } }), instanceWindowStates: () => [],
      focusWorkbench: async () => ({ open: true }), sendToWorkbench },
    launcherAssistantWindow: { isThemeSender: () => themeSender },
    trustedIpcOrigins: () => ["http://127.0.0.1:8000"],
    assertTrustedIpcSender,
    activeDesktopPetWindowDrag: {},
  });
  const frame = { url: "http://127.0.0.1:8000/launcher-assistant" };
  const event = { senderFrame: frame, sender: { mainFrame: frame, getOSProcessId: () => 9 } };
  return { openHandler, sendToWorkbench, event };
}

describe("desktop pet drag IPC surface", () => {
  it("focuses the workbench and forwards the opened session for admitted pet surfaces", async () => {
    const { openHandler, sendToWorkbench, event } = petIpcHandlers(true);
    await expect(openHandler(event, "session-owned")).resolves.toEqual({ schemaVersion: 1, opened: true });
    expect(sendToWorkbench).toHaveBeenCalledWith("conversation:opened", { schemaVersion: 1, sessionId: "session-owned" });
    await expect(openHandler(event, "../invalid")).rejects.toThrow("invalid desktop pet session id");
    await expect(petIpcHandlers(false).openHandler(event, "session-owned")).rejects.toThrow("blocked desktop pet ipc sender");
    expect(sendToWorkbench).toHaveBeenCalledTimes(1);
  });
  it("exposes drag operations only through the unified launcher-assistant preload branch", () => {
    expect(ipcSource).toContain('beginDesktopPetWindowDrag: "pet:window-drag-begin"');
    expect(ipcSource).toContain('moveDesktopPetWindowDrag: "pet:window-drag-move"');
    expect(ipcSource).toContain('endDesktopPetWindowDrag: "pet:window-drag-end"');
    const assistantBranchStart = preloadSource.indexOf("if (isLauncherAssistantWindow)");
    const assistantBranchEnd = preloadSource.indexOf("if (!isLauncherAssistantWindow)");
    expect(preloadSource.slice(assistantBranchStart, assistantBranchEnd)).toContain("ipcRenderer.send(IPC_CHANNELS.moveDesktopPetWindowDrag, point)");
    expect(preloadSource.slice(0, assistantBranchStart)).not.toContain("beginDesktopPetWindowDrag");
    expect(preloadSource.slice(assistantBranchEnd)).not.toContain("beginDesktopPetWindowDrag");
    // The settings-control and window-expanded channels retired with the old pet window.
    expect(preloadSource).not.toContain("setDesktopPetExpanded");
    expect(preloadSource).not.toContain("controlDesktopPet");
    expect(preloadSource).not.toContain("isDesktopPetWindow");
    expect(preloadSource).not.toContain("getDesktopAssistantContext");
  });
  it("moves the owning BrowserWindow with fixed bounds in the main process", () => {
    expect(mainSource).toContain("BrowserWindow.fromWebContents(event.sender)");
    expect(mainSource).toContain("const { x, y, width, height } = window.getBounds()");
    expect(mainSource).not.toContain("beginDesktopPetWindowDrag(rawPoint, window.getBounds())");
    expect(mainSource).toContain("window.setBounds(desktopPetWindowBoundsAt(active.drag, rawPoint), false)");
    expect(mainSource).not.toContain("window.moveBy(update.delta.screenX");
  });
  it("keeps the pet IPC surface behind the theme-sender identity gate", () => {
    // The guard keeps its main-process trust kernel: trusted origins first,
    // then the launcher-assistant identity admission, and nothing else passes.
    expect(mainSource).toContain("assertTrustedIpcSender(event as IpcMainInvokeEvent, trustedIpcOrigins())");
    expect(mainSource).toContain("launcherAssistantWindow?.isThemeSender(event)");
    expect(mainSource).toContain('throw new Error("blocked desktop pet ipc sender")');
    // The retired expand/settings-control handlers are gone for good.
    expect(mainSource).not.toContain("setDesktopPetExpanded");
    expect(mainSource).not.toContain("controlDesktopPet");
    expect(ipcSource).not.toContain("setDesktopPetExpanded");
    expect(ipcSource).not.toContain("controlDesktopPet");
  });
});
