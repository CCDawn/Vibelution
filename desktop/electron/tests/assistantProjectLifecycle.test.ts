import { mkdtempSync, mkdirSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAssistantProjectLifecycle, MAX_ASSISTANT_PROJECT_LIFECYCLE_CONTEXTS, type AssistantProjectLifecycleOptions } from "../src/assistant/projectLifecycle.js";
import { waitForMainLineIntentPersistence } from "../src/lifecycle/mainLine/commandQueue.js";
import { readMainLineIntent } from "../src/lifecycle/mainLine/commandIntent.js";
import { mainLineQueueOwnerPath } from "../src/lifecycle/mainLine/ownerMarker.js";
import { resolveRuntimeManagerDir } from "../src/lifecycle/projectStoragePaths.js";
import { existsSync } from "node:fs";
import { runWorkbenchLifecycle, type RunWorkbenchLifecycleInput } from "../src/process/workbenchLifecycle.js";

const A = "project-a:11111111-1111-4111-8111-111111111111";
const B = "project-b:22222222-2222-4222-8222-222222222222";
const roots: string[] = [];
const deferred = () => { let resolve!: () => void; const promise = new Promise<void>(done => { resolve = done; }); return { promise, resolve }; };
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }); });

function setup() {
  const temp = mkdtempSync(join(tmpdir(), "assistant-project-lifecycle-")); roots.push(temp);
  const root = (name: string) => { const path = join(temp, name); mkdirSync(path); const real = realpathSync.native(path); return process.platform === "win32" ? real.toLowerCase() : real; };
  const a = root("a"), b = root("b");
  let snapshot = { schemaVersion: 1 as const, revision: 1, projects: { [A]: a, [B]: b } as Record<string, string> };
  const runtime = (workspaceRoot: string) => ({ workspaceRoot, pythonPath: join(workspaceRoot, "target-python.exe"), operatorConfigPath: join(workspaceRoot, "operator.toml"), runtimeManagerDir: join(workspaceRoot, ".runtime", "runtime-manager") });
  const run = vi.fn(async (input: RunWorkbenchLifecycleInput) => input.queue!.submit({ operation: input.operation, signal: input.signal, noBrowser: true, execute: async command => {
    await waitForMainLineIntentPersistence(command);
    return { schemaVersion: 1 as const, accepted: true, operation: input.operation };
  } }));
  const readStatus = vi.fn(async () => ({ state: "stopped", activeWorkCount: 0, token: "SECRET", path: a }));
  const resolveRuntime = vi.fn(async ({ workspaceRoot }: { workspaceRoot: string }) => runtime(workspaceRoot));
  const options: AssistantProjectLifecycleOptions = { getPermissionSnapshot: () => snapshot, resolveRuntimeContext: resolveRuntime, readStatus, runLifecycle: run };
  return { a, b, runtime, run, readStatus, resolveRuntime, options, facade: createAssistantProjectLifecycle(options), change: (next: typeof snapshot) => { snapshot = next; }, snapshot: () => snapshot };
}

describe("registered project lifecycle facade", () => {
  it("binds trusted native metadata before execution and rechecks registration after the bind", async () => {
    const f = setup(), gate = deferred(), entered = deferred();
    const bind = vi.fn(async (_binding: unknown, _command: unknown) => { entered.resolve(); await gate.promise; });
    const pending = f.facade.dispatch({ projectId: A, operation: "start" }, { onCommand: bind });
    await Promise.race([entered.promise, new Promise(resolve => setTimeout(resolve, 30))]);
    expect(bind).toHaveBeenCalledTimes(1);
    expect(await readMainLineIntent(f.runtime(f.a).runtimeManagerDir)).toBeNull();
    const [binding, command] = bind.mock.calls[0] as unknown as [{ registryFingerprint: string; workspaceRoot: string }, { commandId: string }];
    expect(binding.workspaceRoot).toBe(f.a);
    expect(binding.registryFingerprint).toMatch(/^[a-f0-9]{64}$/);
    expect(command.commandId).toMatch(/^cmd_/);
    f.change({ ...f.snapshot(), revision: 2 });
    gate.resolve();
    expect((await pending).code).toBe("registration_changed");
    expect(await readMainLineIntent(f.runtime(f.a).runtimeManagerDir)).toBeNull();
  });
  it("constructs and reads a closed status without resolving Python or starting a project", async () => {
    const f = setup();
    expect(f.run).not.toHaveBeenCalled();
    expect(await f.facade.dispatch({ projectId: A, operation: "status" })).toEqual({ schemaVersion: 1, projectId: A, operation: "status", accepted: true, code: "status", status: { state: "stopped", activeWorkCount: 0 } });
    expect(f.resolveRuntime).not.toHaveBeenCalled(); expect(f.run).not.toHaveBeenCalled();
  });

  it.each([null, [], {}, { projectId: A, operation: "force-stop" }, { projectId: A, operation: "start", force: true }, { projectId: A, operation: "stop", interruptActiveWork: true }, { projectId: A, operation: "restart", root: "evil" }, { projectId: A, operation: "start", requestId: "fake-idempotency" }, { projectId: 2, operation: "start" }])("rejects malformed or extra caller capabilities: %j", async request => {
    const f = setup(); expect((await f.facade.dispatch(request)).code).toBe("invalid_request"); expect(f.run).not.toHaveBeenCalled(); expect(f.readStatus).not.toHaveBeenCalled();
  });

  it("captures caller schema before asynchronous resolution and uses target runtime and queue", async () => {
    const f = setup(), gate = deferred();
    f.resolveRuntime.mockImplementation(async ({ workspaceRoot }) => { await gate.promise; return f.runtime(workspaceRoot); });
    const request = { projectId: A, operation: "restart" };
    const result = f.facade.dispatch(request); request.projectId = B; request.operation = "stop"; gate.resolve();
    expect((await result).accepted).toBe(true);
    expect(f.run).toHaveBeenCalledWith(expect.objectContaining({ workspaceRoot: f.a, pythonPath: f.runtime(f.a).pythonPath, operatorConfigPath: f.runtime(f.a).operatorConfigPath, operation: "restart", interruptActiveWork: false, queue: expect.any(Object) }));
  });

  it("runs A/B concurrently with separate persistence and preserves same-A native join/serialization", async () => {
    const f = setup(), gate = deferred(), started = deferred(); const executed: string[] = [];
    f.options.runLifecycle = vi.fn(async (input: RunWorkbenchLifecycleInput) => input.queue!.submit({ operation: input.operation, signal: input.signal, noBrowser: true, execute: async command => {
      await waitForMainLineIntentPersistence(command); executed.push(`${input.workspaceRoot}:${input.operation}`);
      if (input.workspaceRoot === f.a && input.operation === "start") { started.resolve(); await gate.promise; }
      return { schemaVersion: 1, accepted: true, operation: input.operation };
    } }));
    const facade = createAssistantProjectLifecycle(f.options);
    const first = facade.dispatch({ projectId: A, operation: "start" }); await started.promise;
    const joined = facade.dispatch({ projectId: A, operation: "start" });
    const stop = facade.dispatch({ projectId: A, operation: "stop" });
    expect((await facade.dispatch({ projectId: B, operation: "restart" })).accepted).toBe(true);
    expect(executed).toEqual([`${f.a}:start`, `${f.b}:restart`]);
    gate.resolve(); await Promise.all([first, joined, stop]);
    expect(executed).toEqual([`${f.a}:start`, `${f.b}:restart`, `${f.a}:stop`]);
    expect((await readMainLineIntent(f.runtime(f.a).runtimeManagerDir))?.operation).toBe("stop");
    expect((await readMainLineIntent(f.runtime(f.b).runtimeManagerDir))?.operation).toBe("restart");
    expect(existsSync(mainLineQueueOwnerPath(f.runtime(f.a).runtimeManagerDir))).toBe(true);
    expect(existsSync(mainLineQueueOwnerPath(f.runtime(f.b).runtimeManagerDir))).toBe(true);
  });

  it.each(["revoke", "epoch", "redirect"])("fails closed when registration changes during context resolution: %s", async change => {
    const f = setup(), gate = deferred(); f.resolveRuntime.mockImplementation(async ({ workspaceRoot }) => { await gate.promise; return f.runtime(workspaceRoot); });
    const pending = f.facade.dispatch({ projectId: A, operation: "start" });
    const next = { ...f.snapshot(), projects: { ...f.snapshot().projects } };
    if (change === "revoke") delete next.projects[A]; if (change === "epoch") next.revision++; if (change === "redirect") next.projects[A] = f.b;
    f.change(next); gate.resolve(); expect((await pending).code).toBe("registration_changed"); expect(f.run).not.toHaveBeenCalled();
  });

  it.each(["revoke", "epoch", "redirect"])("rechecks registration at the actual native queue execute boundary: %s", async change => {
    const f = setup(), gate = deferred(), started = deferred(); const execute = vi.fn();
    f.options.runLifecycle = async input => input.queue!.submit({ operation: input.operation, execute: async () => {
      execute(input.operation); if (input.operation === "start") { started.resolve(); await gate.promise; }
      return { schemaVersion: 1, accepted: true, operation: input.operation };
    } });
    const facade = createAssistantProjectLifecycle(f.options);
    const first = facade.dispatch({ projectId: A, operation: "start" }); await started.promise;
    const pending = facade.dispatch({ projectId: A, operation: "stop" });
    await vi.waitFor(() => expect(f.resolveRuntime).toHaveBeenCalledTimes(1));
    await new Promise(resolve => setTimeout(resolve, 0));
    const next = { ...f.snapshot(), projects: { ...f.snapshot().projects } };
    if (change === "revoke") delete next.projects[A]; if (change === "epoch") next.revision++; if (change === "redirect") next.projects[A] = f.b;
    f.change(next); gate.resolve(); await first;
    expect((await pending).code).toBe("registration_changed"); expect(execute).toHaveBeenCalledTimes(1);
  });

  it("fails closed on physical root redirection and does not expose errors or native details", async () => {
    const f = setup(); f.options.realPath = () => f.b;
    expect((await createAssistantProjectLifecycle(f.options).dispatch({ projectId: A, operation: "start" })).code).toBe("registration_changed"); expect(f.run).not.toHaveBeenCalled();
    f.options.realPath = undefined; f.options.runLifecycle = async () => { throw new Error(`${f.a} SECRET token=abc`); };
    const failed = await createAssistantProjectLifecycle(f.options).dispatch({ projectId: A, operation: "stop" });
    expect(failed.code).toBe("lifecycle_failed"); expect(JSON.stringify(failed)).not.toContain(f.a); expect(JSON.stringify(failed)).not.toContain("SECRET");
    f.options.runLifecycle = async () => ({ schemaVersion: 1, accepted: false, operation: f.a, code: f.a, message: "SECRET", activeWorkRuns: [{ token: "SECRET" }] });
    expect(await createAssistantProjectLifecycle(f.options).dispatch({ projectId: A, operation: "stop" })).toEqual({ schemaVersion: 1, projectId: A, operation: "stop", accepted: false, code: "rejected" });
  });

  it("uses the real native runner with a target queue and keeps stop/restart active-work protection", async () => {
    const f = setup(), spawn = vi.fn(() => { throw new Error("must not spawn"); });
    f.options.runLifecycle = input => runWorkbenchLifecycle({ ...input, spawnImpl: spawn, readState: () => ({ backendPid: 0, backendPort: 8000 }), writeState: () => undefined, listActiveWork: () => [{ kind: "chat_turn", runId: "active-work", status: "running", sessionId: "session-1" }], connect: async () => false, pidAlive: () => false });
    const facade = createAssistantProjectLifecycle(f.options);
    for (const operation of ["stop", "restart"] as const) {
      const result = await facade.dispatch({ projectId: A, operation });
      expect(result).toMatchObject(operation === "stop" ? { accepted: false, code: "active_work_blocked" } : { accepted: true, code: "restart_queued" });
    }
    expect(spawn).not.toHaveBeenCalled();
  });

  it("keeps cancellation in A away from B and does not let cancelled work execute later", async () => {
    const f = setup(), gate = deferred(), started = deferred(), controller = new AbortController(); const executed: string[] = [];
    f.options.runLifecycle = input => input.queue!.submit({ operation: input.operation, signal: input.signal, execute: async () => {
      executed.push(input.workspaceRoot);
      if (input.workspaceRoot === f.a) { started.resolve(); await gate.promise; }
      return { schemaVersion: 1, accepted: true, operation: input.operation };
    } });
    const facade = createAssistantProjectLifecycle(f.options);
    const pending = facade.dispatch({ projectId: A, operation: "start" }, { signal: controller.signal }); await started.promise;
    const other = facade.dispatch({ projectId: B, operation: "start" });
    controller.abort(new Error("SECRET token/path"));
    expect((await pending).code).toBe("cancelled"); expect((await other).accepted).toBe(true);
    gate.resolve(); expect(executed).toEqual([f.a, f.b]);
  });

  it("rejects getters and symbols without evaluating caller code", async () => {
    const f = setup(), getter = vi.fn(() => A);
    const input = { operation: "start", get projectId() { return getter(); } };
    expect((await f.facade.dispatch(input)).code).toBe("invalid_request"); expect(getter).not.toHaveBeenCalled();
    expect((await f.facade.dispatch({ projectId: A, operation: "start", [Symbol("capability")]: 1 })).code).toBe("invalid_request");
  });

  it("fails unknown registrations and unresolved target runtimes without spawn or assistant Python fallback", async () => {
    const f = setup();
    expect((await f.facade.dispatch({ projectId: "unknown", operation: "start" })).code).toBe("project_unavailable");
    expect(f.resolveRuntime).not.toHaveBeenCalled();
    f.options.resolveRuntimeContext = async () => null;
    expect((await createAssistantProjectLifecycle(f.options).dispatch({ projectId: A, operation: "start" })).code).toBe("prerequisite_required"); expect(f.run).not.toHaveBeenCalled();
  });

  it("bounds retained contexts across registration epochs without cancelling existing work or blocking status", async () => {
    const f = setup(); f.options.runLifecycle = vi.fn(async (input: RunWorkbenchLifecycleInput) => ({ schemaVersion: 1 as const, accepted: true, operation: input.operation }));
    const facade = createAssistantProjectLifecycle(f.options);
    for (let index = 0; index <= MAX_ASSISTANT_PROJECT_LIFECYCLE_CONTEXTS; index++) {
      const projectId = `registered-${index}`;
      f.change({ schemaVersion: 1, revision: index + 1, projects: { [projectId]: f.a } });
      const result = await facade.dispatch({ projectId, operation: "start" });
      expect(result.code).toBe(index === MAX_ASSISTANT_PROJECT_LIFECYCLE_CONTEXTS ? "context_limit" : "accepted");
    }
    expect(f.options.runLifecycle).toHaveBeenCalledTimes(MAX_ASSISTANT_PROJECT_LIFECYCLE_CONTEXTS);
    expect((await facade.dispatch({ projectId: `registered-${MAX_ASSISTANT_PROJECT_LIFECYCLE_CONTEXTS}`, operation: "status" })).code).toBe("status");
  });

  it("checks physical root identity again after a command waits in its queue", async () => {
    const f = setup(), gate = deferred(), started = deferred(); let redirect = false; const execute = vi.fn();
    f.options.realPath = root => redirect && root === f.a ? f.b : root;
    f.options.runLifecycle = input => input.queue!.submit({ operation: input.operation, execute: async () => {
      execute(input.operation); if (input.operation === "start") { started.resolve(); await gate.promise; }
      return { schemaVersion: 1, accepted: true, operation: input.operation };
    } });
    const facade = createAssistantProjectLifecycle(f.options);
    const first = facade.dispatch({ projectId: A, operation: "start" }); await started.promise;
    const next = facade.dispatch({ projectId: A, operation: "stop" }); await new Promise(resolve => setTimeout(resolve, 0));
    redirect = true; gate.resolve(); await first;
    expect((await next).code).toBe("registration_changed"); expect(execute).toHaveBeenCalledTimes(1);
  });

  it.each(["another-project", "legacy"])("rejects a runtime resolver directory outside the default native storage owner: %s", async kind => {
    const f = setup();
    f.resolveRuntime.mockImplementation(async ({ workspaceRoot }) => ({ ...f.runtime(workspaceRoot), runtimeManagerDir: kind === "another-project" ? f.runtime(f.b).runtimeManagerDir : join(workspaceRoot, "legacy-runtime-manager") }));
    expect((await f.facade.dispatch({ projectId: A, operation: "start" })).code).toBe("storage_owner_changed");
    expect(f.run).not.toHaveBeenCalled();
    expect(existsSync(f.runtime(f.b).runtimeManagerDir)).toBe(false);
    expect(existsSync(join(f.a, "legacy-runtime-manager"))).toBe(false);
  });

  it("fails cached dispatches and status when the native owner changes without creating a parallel queue", async () => {
    const f = setup(); const previous = join(f.a, "native-owner-0"), next = join(f.a, "native-owner-1"); let owner = previous;
    f.options.resolveNativeRuntimeManagerDir = root => root === f.a ? owner : resolveRuntimeManagerDir(root);
    f.resolveRuntime.mockImplementation(async ({ workspaceRoot }) => ({ ...f.runtime(workspaceRoot), runtimeManagerDir: owner }));
    const facade = createAssistantProjectLifecycle(f.options);
    expect((await facade.dispatch({ projectId: A, operation: "start" })).accepted).toBe(true);
    owner = next;
    expect((await facade.dispatch({ projectId: A, operation: "restart" })).code).toBe("storage_owner_changed");
    expect((await facade.dispatch({ projectId: A, operation: "status" })).code).toBe("storage_owner_changed");
    expect(f.run).toHaveBeenCalledTimes(1); expect(f.resolveRuntime).toHaveBeenCalledTimes(1);
    expect((await readMainLineIntent(previous))?.operation).toBe("start"); expect(existsSync(next)).toBe(false);
  });

  it("fails a queued execute if the native storage owner migrates after admission", async () => {
    const f = setup(), gate = deferred(), started = deferred(), queued = deferred(); const execute = vi.fn();
    const previous = f.runtime(f.a).runtimeManagerDir, next = join(f.a, "native-owner-1"); let owner = previous;
    f.options.resolveNativeRuntimeManagerDir = root => root === f.a ? owner : resolveRuntimeManagerDir(root);
    f.options.runLifecycle = async input => {
      const result = input.queue!.submit({ operation: input.operation, execute: async command => {
        await waitForMainLineIntentPersistence(command);
        execute(input.operation); if (input.operation === "start") { started.resolve(); await gate.promise; }
        return { schemaVersion: 1, accepted: true, operation: input.operation };
      } });
      if (input.operation === "stop") queued.resolve();
      return result;
    };
    const facade = createAssistantProjectLifecycle(f.options);
    const first = facade.dispatch({ projectId: A, operation: "start" }); await started.promise;
    const pending = facade.dispatch({ projectId: A, operation: "stop" }); await queued.promise;
    owner = next; gate.resolve(); await first;
    expect((await pending).code).toBe("storage_owner_changed"); expect(execute).toHaveBeenCalledTimes(1); expect(existsSync(next)).toBe(false);
    expect((await facade.dispatch({ projectId: B, operation: "start" })).accepted).toBe(true);
  });
});
