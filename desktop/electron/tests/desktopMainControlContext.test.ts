import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";
import { BackendControlTokenOwner, type BackendControlProcessIdentity } from "../src/protocol/backendControlToken.js";
import type { RuntimeSceneBridgeOptions } from "../src/lifecycle/runtimeSceneBridge.js";

type Context = { launcherOrigin: string; controlToken: string; desktopSessionId: string };
type ResolveOptions = { forceControlTokenRefresh?: boolean; signal?: AbortSignal };
type MirrorWork = { kind: string; run: (revision: number) => Promise<unknown> };

function harness() {
  const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
  const fragment = (begin: string, end: string) => source.slice(source.indexOf(begin), source.indexOf(end, source.indexOf(begin)));
  let identity: BackendControlProcessIdentity | null = { pid: 10, createTime: 100 };
  const env = { VIBELUTION_WORKSPACE_ROOT: "C:/workspace", VIBELUTION_WORKBENCH_URL: "http://127.0.0.1:8000", VIBELUTION_WEB_CONTROL_TOKEN: "obsolete-environment" };
  const fetchToken = vi.fn(async (_input: unknown) => `backend-${identity?.pid}-${identity?.createTime}`);
  const mirrorWork: MirrorWork[] = [];
  const register = vi.fn(async (_input: Context) => ({ revision: 1 }));
  const reportWindow = vi.fn(async (_input: Context) => ({ revision: 2 }));
  const bridges: { options: RuntimeSceneBridgeOptions; queue: string[] }[] = [];
  class Bridge {
    queue = ["retained-event"];
    constructor(readonly options: RuntimeSceneBridgeOptions) { bridges.push(this); }
  }
  const sandbox: Record<string, unknown> = {
    BackendControlTokenOwner, RuntimeSceneBridge: Bridge, performance,
    testBootstrap: { workbenchUrl: env.VIBELUTION_WORKBENCH_URL },
    desktopEnvironment: () => env,
    createDesktopPathsForApp: () => ({ workspaceRoot: env.VIBELUTION_WORKSPACE_ROOT }),
    launcherStatePath: (root: string) => root,
    readLauncherStateFile: () => ({ backendPid: identity?.pid ?? 0, backendCreateTime: identity?.createTime ?? 0 }),
    resolveWorkbenchUrl: (currentEnv: typeof env, fallback?: string) => currentEnv.VIBELUTION_WORKBENCH_URL || fallback,
    currentDesktopSessionId: () => "stable-session",
    fetchLauncherControlToken: fetchToken,
    RUNTIME_SCENE_MAX_BUFFERED_EVENTS: 5,
    desktopSessionMutations: { accepts: () => true, enqueue: async (_kind: string, run: () => Promise<void>) => run() },
    inProcessDesktopSessionStore: { register: () => ({ revision: 1 }), reportWindow: () => ({ revision: 2 }) },
    desktopSessionCapabilities: () => [],
    desktopSessionMirror: {
      register: (run: () => Promise<unknown>) => { mirrorWork.push({ kind: "register", run }); return Promise.resolve(); },
      mutate: (kind: string, run: MirrorWork["run"]) => { mirrorWork.push({ kind, run }); return Promise.resolve(); }
    },
    registerDesktopSession: register, reportDesktopWindowState: reportWindow,
    startDesktopSessionHeartbeatIfNeeded: () => undefined, stopDesktopSessionHeartbeat: () => undefined,
    scheduleTelemetryWithoutWaiting: () => undefined,
    electronStartupFields: (fields: unknown) => fields,
    electronStageElapsedMs: () => 0
  };
  const program = `
    let desktopActionContext = null, backendControlTokenOwner = null, runtimeSceneBridge = null;
    let runtimeSceneBridgeOpening = null;
    let currentWorkbenchUrl = "", launcherBootstrap = testBootstrap;
    let desktopSessionRegistered = false, desktopSessionRevision = 0, electronStartupStage = "";
    let desktopControlRecoveryPromise = null;
    ${fragment("function currentDesktopControlOrigin(", "async function recordElectronSupervisorEvent(")}
    ${fragment("async function persistManagedWindowState(", "function desktopSessionHeartbeatSupported(")}
    ${fragment("async function recoverDesktopControlContext(", "async function recoverWorkbenchCloseControlContext(")}
    ${fragment("function rememberLiveWorkbenchUrl(", "async function refreshLiveWorkbenchUrl(")}
    globalThis.api = {
      resolve: (options) => resolveDesktopActionLoopContext(testBootstrap, options),
      bridge: () => resolveRuntimeSceneBridge(testBootstrap),
      closeSnapshot: () => desktopControlContextForLocalClose(testBootstrap),
      context: () => desktopActionContext,
      remember: (url) => rememberLiveWorkbenchUrl(url),
      persist: () => persistManagedWindowState({workspaceRoot: "C:/workspace"}, testBootstrap, {role: "launcher"}),
      recover: () => recoverDesktopControlContext({workspaceRoot: "C:/workspace"}, testBootstrap, {snapshot: () => ({workbench: {role: "launcher"}})}, "test")
    };
  `;
  runInNewContext(transpileModule(program, { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText, sandbox);
  const api = sandbox.api as {
    resolve(options?: ResolveOptions): Promise<Context>;
    bridge(): Promise<Bridge>;
    closeSnapshot(): Context;
    context(): Context | null;
    remember(url: string): string;
    persist(): Promise<void>;
    recover(): Promise<void>;
  };
  return { ...api, env, fetchToken, mirrorWork, register, reportWindow, bridges, setIdentity: (value: BackendControlProcessIdentity | null) => { identity = value; } };
}

describe("Electron shared backend control context", () => {
  it("shares first construction and preserves the cold offline failure for the existing local fallback", async () => {
    const h = harness();
    h.setIdentity(null);
    h.fetchToken.mockRejectedValue(new Error("offline"));
    const results = await Promise.allSettled([h.bridge(), h.bridge()]);
    expect(results.map((result) => result.status)).toEqual(["rejected", "rejected"]);
    expect(h.bridges).toHaveLength(0);
    expect(h.fetchToken).toHaveBeenCalledOnce();
    expect(h.context()).toBeNull();
    h.setIdentity({ pid: 20, createTime: 200 });
    h.fetchToken.mockResolvedValue("available");
    const [first, second] = await Promise.all([h.bridge(), h.bridge()]);
    expect(first).toBe(second);
    expect(h.bridges).toHaveLength(1);
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
  });

  it("shares current credentials across main requests and event delivery, refreshing on real process change", async () => {
    const h = harness();
    const bridge = await h.bridge();
    const [main, event] = await Promise.all([h.resolve(), bridge.options.resolveControlContext!()]);
    expect(main.controlToken).toBe("backend-10-100");
    expect(event.controlToken).toBe(main.controlToken);
    expect(h.fetchToken).toHaveBeenCalledOnce();
    h.setIdentity({ pid: 10, createTime: 200 });
    const refreshed = await bridge.options.resolveControlContext!();
    expect(refreshed.controlToken).toBe("backend-10-200");
    expect((await h.resolve()).controlToken).toBe(refreshed.controlToken);
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.context()?.desktopSessionId).toBe("stable-session");
  });

  it("does not publish an old scope's delayed credentials over a newer origin", async () => {
    const h = harness();
    let finish!: (token: string) => void;
    h.fetchToken.mockImplementationOnce(() => new Promise<string>((resolve) => { finish = resolve; }));
    const old = h.resolve().catch((error: unknown) => error);
    await vi.waitFor(() => expect(h.fetchToken).toHaveBeenCalledOnce());
    h.env.VIBELUTION_WORKBENCH_URL = "http://127.0.0.1:8001";
    h.fetchToken.mockResolvedValue("new-origin");
    const current = await h.resolve();
    finish("old-origin");
    expect(String(await old)).toContain("scope changed");
    expect(h.context()).toEqual(current);
    expect(h.context()?.controlToken).toBe("new-origin");
  });

  it("resolves queued window and registration credentials at delivery rather than capture time", async () => {
    const h = harness();
    await h.resolve();
    await h.persist();
    expect(h.fetchToken).toHaveBeenCalledOnce();
    expect(h.mirrorWork.map((work) => work.kind)).toEqual(["register", "window"]);
    h.setIdentity({ pid: 20, createTime: 200 });
    await Promise.all(h.mirrorWork.map((work) => work.run(3)));
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.register).toHaveBeenCalledWith(expect.objectContaining({ controlToken: "backend-20-200", desktopSessionId: "stable-session" }));
    expect(h.reportWindow).toHaveBeenCalledWith(expect.objectContaining({ controlToken: "backend-20-200", desktopSessionId: "stable-session", revision: 3 }));
  });

  it("keeps local window truth and close receipts independent of an offline token endpoint", async () => {
    const h = harness();
    await h.resolve();
    h.setIdentity(null);
    h.fetchToken.mockRejectedValue(new Error("offline"));
    await h.persist();
    expect(h.closeSnapshot()).toEqual(expect.objectContaining({ controlToken: "backend-10-100", desktopSessionId: "stable-session" }));
    expect(h.fetchToken).toHaveBeenCalledOnce();
  });

  it("preserves the same event queue during forced control-context recovery", async () => {
    const h = harness();
    const bridge = await h.bridge();
    await h.resolve();
    h.setIdentity({ pid: 20, createTime: 200 });
    await h.recover();
    expect(await h.bridge()).toBe(bridge);
    expect(bridge.queue).toEqual(["retained-event"]);
    expect(h.bridges).toHaveLength(1);
    expect(h.context()?.controlToken).toBe("backend-20-200");
  });

  it("keeps the last confirmed close snapshot while a shared forced refresh is pending", async () => {
    const h = harness();
    const last = await h.resolve();
    let finish!: (token: string) => void;
    h.fetchToken.mockImplementationOnce(() => new Promise<string>((resolve) => { finish = resolve; }));
    const recovering = h.recover();
    await vi.waitFor(() => expect(h.fetchToken).toHaveBeenCalledTimes(2));
    expect(h.closeSnapshot()).toEqual(last);
    finish("refreshed-current");
    await recovering;
    expect(h.context()?.controlToken).toBe("refreshed-current");
  });

  it.each(["", "http://127.0.0.1:8000"])("keeps the existing bridge on the newly verified live origin after relocation (launch hint: %s)", async (hint) => {
    const h = harness();
    h.env.VIBELUTION_WORKBENCH_URL = hint;
    const bridge = await h.bridge();
    await h.resolve();
    h.setIdentity({ pid: 20, createTime: 200 });
    h.remember("http://127.0.0.1:8001");
    const context = await bridge.options.resolveControlContext!();
    expect(context.launcherOrigin).toBe("http://127.0.0.1:8001");
    expect(context.controlToken).toBe("backend-20-200");
    expect(h.fetchToken).toHaveBeenLastCalledWith({ launcherOrigin: "http://127.0.0.1:8001" });
    expect((await h.resolve()).launcherOrigin).toBe(context.launcherOrigin);
    expect(await h.bridge()).toBe(bridge);
  });

  it("rejects a late origin result even before another caller starts the new scope", async () => {
    const h = harness();
    let finish!: (token: string) => void;
    h.fetchToken.mockImplementationOnce(() => new Promise<string>((resolve) => { finish = resolve; }));
    const old = h.resolve().catch((error: unknown) => error);
    await vi.waitFor(() => expect(h.fetchToken).toHaveBeenCalledOnce());
    h.remember("http://127.0.0.1:8001");
    finish("old-origin");
    expect(String(await old)).toContain("scope changed");
    expect(h.context()).toBeNull();
  });
});
