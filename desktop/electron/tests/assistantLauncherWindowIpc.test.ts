import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";
import { createAssistantLauncherEntry } from "../src/assistant/launcherEntry.js";
import { invokeAssistant } from "../src/assistant/assistantBridge.js";

const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const ast = ts.createSourceFile("main.ts", source, ts.ScriptTarget.Latest, true);

function handlers() {
  const callbacks = new Map<string, (...args: any[]) => any>();
  const close = vi.fn();
  const openLauncher = vi.fn(async () => undefined);
  const dialog = { showOpenDialog: vi.fn(async () => ({ canceled: false, filePaths: ["project"] })) };
  const context: Record<string, any> = {
    ipcMain: { handle: (channel: string, callback: (...args: any[]) => any) => callbacks.set(channel, callback) },
    IPC_CHANNELS: { launcherInvoke: "invoke", returnToDesktop: "return", selectProject: "select", assistantInvoke: "assistant" },
    assertTrustedIpcSender: vi.fn(), launcherIpcTrustedOrigins: () => [],
    isLauncherControlSender: (sender: any) => sender.registered === true,
    isTrustedLauncherControlFrame: (event: any) => event.sender.registered === true && event.senderFrame === event.sender.mainFrame && event.senderFrame.url === "vibelution-launcher://launcher/launcher/assistant",
    isWorkbenchMainSender: () => false, invokeAssistant,
    launcherAssistantHost: { start: vi.fn(async () => undefined), request: vi.fn(async () => ({ agentId: "resident" })) },
    launcherAssistantWindow: null, requestOpenLauncherFromAssistant: vi.fn(),
    BrowserWindow: { fromWebContents: () => ({ isDestroyed: () => false, close }) },
    launcherBootstrap: null, windowProvider: null, shutdownApproved: false, dialog,
    statSync: () => ({ isDirectory: () => true, isFile: () => true }), join: (...parts: string[]) => parts.join("/"),
    startProjectControlPlaneObservers: vi.fn(), flushPendingPublicDeepLinks: vi.fn(async () => undefined),
    resolveLauncherIpcHost: () => ({ invoke: async () => ({ ok: true, payload: "host" }) }),
  };
  context.ensureProjectControlPlane = vi.fn(async () => {
    context.windowProvider = { openLauncher }; context.launcherBootstrap = {}; return true;
  });
  const statements = ast.statements.filter(node => ts.isExpressionStatement(node) && ts.isCallExpression(node.expression)
    && node.expression.expression.getText(ast) === "ipcMain.handle"
    && ["IPC_CHANNELS.launcherInvoke", "IPC_CHANNELS.returnToDesktop", "IPC_CHANNELS.selectProject", "IPC_CHANNELS.assistantInvoke"]
      .includes(node.expression.arguments[0]?.getText(ast)));
  const code = `let assistantProjectSelection = null;\n${statements.map(node => node.getFullText(ast)).join("\n")}`;
  runInNewContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  const frame = { url: "vibelution-launcher://launcher/launcher/assistant" };
  const sender = { registered: true, mainFrame: frame };
  return { callbacks, context, sender, event: { sender, senderFrame: frame }, close, openLauncher, dialog };
}

describe("assistant Launcher window IPC", () => {
  it("opens one standalone control window before any project is selected", async () => {
    const declarations = ast.statements.filter(node => ts.isFunctionDeclaration(node)
      && ["standaloneAssistantLauncherProvider", "requestOpenLauncherFromAssistant"].includes(node.name?.text ?? ""));
    const openLauncher = vi.fn(async () => undefined);
    const hideFloat = vi.fn();
    const create = vi.fn(function () { return { openLauncher }; });
    const context: Record<string, any> = {
      assistantLauncherEntry: null, assistantLauncherWindowProvider: null, windowProvider: null,
      shutdownApproved: false, launcherAssistantWindow: { hideFloat }, createAssistantLauncherEntry,
      desktopEnvironment: () => ({}), resolveDesktopBundleRoot: () => "bundle", app: { getPath: () => "user" },
      process: { resourcesPath: "resources" }, ElectronWindowProvider: create,
      resolveLauncherWindowUrl: () => "vibelution-launcher://launcher/launcher/assistant", createLauncherWindow: vi.fn(),
      BrowserWindow: { getAllWindows: () => [] }, isLauncherControlSender: () => false,
    };
    const code = declarations.map(node => node.getFullText(ast)).join("\n").replaceAll("import.meta.url", '"file:///main.js"');
    const open = runInNewContext(`${ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText}\nrequestOpenLauncherFromAssistant`, context);
    await expect(open()).resolves.toMatchObject({ opened: true });
    await expect(open()).resolves.toMatchObject({ opened: true });
    expect(create).toHaveBeenCalledOnce();
    expect(openLauncher).toHaveBeenCalledTimes(2);
    expect(hideFloat).toHaveBeenCalledTimes(2);
  });
  it("returns to the desktop only for the registered main frame", () => {
    const f = handlers(); const invoke = f.callbacks.get("return")!;
    expect(() => invoke({ sender: f.sender, senderFrame: {} })).toThrow("blocked launcher window sender");
    expect(() => invoke({ sender: { registered: false, mainFrame: f.event.senderFrame }, senderFrame: f.event.senderFrame })).toThrow();
    invoke(f.event); expect(f.close).toHaveBeenCalledOnce();
  });
  it("distinguishes a missing project and connects a human-selected project without starting it", async () => {
    const f = handlers(); const invoke = f.callbacks.get("invoke")!, select = f.callbacks.get("select")!;
    expect(await invoke(f.event, { schemaVersion: 1, path: "branch-instances" })).toMatchObject({ ok: false, error: { code: "LAUNCHER_PROJECT_NOT_SELECTED" } });
    await expect(select(f.event)).resolves.toMatchObject({ connected: true });
    expect(f.context.ensureProjectControlPlane).toHaveBeenCalledExactlyOnceWith("project", true);
    expect(f.openLauncher).toHaveBeenCalledOnce();
    expect(f.context.startProjectControlPlaneObservers).toHaveBeenCalledOnce();
    expect(await invoke(f.event, { schemaVersion: 1, path: "branch-instances" })).toMatchObject({ ok: true });
  });
  it("rejects a registered window after foreign navigation for lifecycle and selection", async () => {
    const f = handlers(); const invoke = f.callbacks.get("invoke")!, select = f.callbacks.get("select")!, close = f.callbacks.get("return")!, assistant = f.callbacks.get("assistant")!;
    await expect(assistant(f.event, { operation: "panelAffairs", kind: "", status: "" })).resolves.toMatchObject({ agentId: "resident" });
    f.event.senderFrame.url = "https://example.com/launcher/assistant";
    await expect(invoke(f.event, { schemaVersion: 1, path: "start" })).rejects.toThrow("blocked launcher window sender");
    await expect(assistant(f.event, { operation: "panelAffairs", kind: "", status: "" })).rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    expect(() => select(f.event)).toThrow("blocked launcher window sender");
    expect(() => close(f.event)).toThrow("blocked launcher window sender");
    expect(f.dialog.showOpenDialog).not.toHaveBeenCalled();
    expect(f.context.launcherAssistantHost.request).toHaveBeenCalledTimes(1);
  });
  it("leaves the project unconnected on cancel and rejects unregistered senders", async () => {
    const f = handlers(); const select = f.callbacks.get("select")!;
    expect(() => select({ sender: f.sender, senderFrame: {} })).toThrow("blocked launcher window sender");
    f.dialog.showOpenDialog.mockResolvedValueOnce({ canceled: true, filePaths: [] });
    await expect(select(f.event)).resolves.toMatchObject({ connected: false });
    expect(f.context.ensureProjectControlPlane).not.toHaveBeenCalled();
  });
});
