import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";
import { findVibelutionDeepLinkArg, parsePublicVibelutionDeepLink } from "../src/protocol/deepLink.js";

const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const ast = ts.createSourceFile("main.ts", source, ts.ScriptTarget.Latest, true);
const names = ["handlePublicDeepLinkUrl", "flushPendingPublicDeepLinks", "completeAssistantOnlyStartup"];
const declarations = ast.statements.filter(node => ts.isFunctionDeclaration(node) && names.includes(node.name?.text ?? ""));
if (declarations.length !== names.length) throw new Error("Missing deep link handler");

function fixture() {
  const context: Record<string, any> = {
    pendingPublicDeepLinks: [], residentDeepLinksReady: false, windowProvider: null,
    launcherBootstrap: null, findVibelutionDeepLinkArg, parsePublicVibelutionDeepLink,
    requestOpenLauncherFromAssistant: vi.fn(async () => ({ opened: true })),
    recordElectronSupervisorEvent: vi.fn(async () => undefined),
  };
  const js = ts.transpileModule(declarations.map(node => node.getFullText(ast)).join("\n"),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  runInNewContext(js, context);
  return context;
}

describe("assistant-only deep links", () => {
  it("opens the cold-start focus link after the resident starts", async () => {
    const ctx = fixture();
    let ready!: () => void;
    const startup = new Promise<void>(resolve => { ready = resolve; });
    const completion = ctx.completeAssistantOnlyStartup(startup, ["app.exe", "vibelution://launcher/focus"]);
    expect(ctx.requestOpenLauncherFromAssistant).not.toHaveBeenCalled();
    ready(); await completion;
    expect(ctx.requestOpenLauncherFromAssistant).toHaveBeenCalledOnce();
    expect(ctx.recordElectronSupervisorEvent).toHaveBeenCalledWith(null, expect.objectContaining({ eventCode: "electron.deep_link.accepted" }));
  });
  it("drains links received during startup and handles later links without a project", async () => {
    const ctx = fixture();
    await ctx.handlePublicDeepLinkUrl("vibelution://launcher/focus", "second_instance");
    expect(ctx.requestOpenLauncherFromAssistant).not.toHaveBeenCalled();
    await ctx.completeAssistantOnlyStartup(Promise.resolve(), []);
    expect(ctx.requestOpenLauncherFromAssistant).toHaveBeenCalledTimes(1);
    await ctx.handlePublicDeepLinkUrl("vibelution://launcher/focus", "open_url");
    expect(ctx.requestOpenLauncherFromAssistant).toHaveBeenCalledTimes(2);
  });
  it("retains project-provider handling and rejects non-public routes", async () => {
    const ctx = fixture();
    const openLauncher = vi.fn(async () => undefined);
    ctx.windowProvider = { openLauncher };
    await ctx.handlePublicDeepLinkUrl("vibelution://launcher/focus", "second_instance");
    await ctx.handlePublicDeepLinkUrl("vibelution://workbench/open?path=test", "second_instance");
    expect(openLauncher).toHaveBeenCalledTimes(2);
    expect(ctx.requestOpenLauncherFromAssistant).not.toHaveBeenCalled();
    expect(ctx.recordElectronSupervisorEvent).toHaveBeenLastCalledWith(null, expect.objectContaining({ eventCode: "electron.deep_link.rejected" }));
  });
});
