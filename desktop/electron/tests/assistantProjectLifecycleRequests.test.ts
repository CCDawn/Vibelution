import { linkSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAssistantProjectLifecycle } from "../src/assistant/projectLifecycle.js";
import { createAssistantProjectLifecycleRequests } from "../src/assistant/projectLifecycleRequests.js";
import { AssistantProjectLifecycleRequestStore } from "../src/assistant/projectLifecycleRequestStore.js";
import { mainLineCommandResultPath } from "../src/lifecycle/mainLine/commandEvidence.js";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });
function setup(realNative = false) {
  const temp = realpathSync.native(mkdtempSync(join(tmpdir(), "assistant-lifecycle-requests-"))); roots.push(temp);
  const root = process.platform === "win32" ? temp.toLowerCase() : temp;
  const runtimeManagerDir = join(root, ".runtime", "runtime-manager");
  const directory = join(root, "requests");
  let revision = 1;
  const execute = vi.fn(async (command) => {
    const blocked = realNative && command.operation === "stop";
    const queued = realNative && command.operation === "restart";
    const accepted = !blocked;
    const code = blocked ? "active_work_blocked" : queued ? "restart_queued" : undefined;
    mkdirSync(join(runtimeManagerDir, "results"), { recursive: true });
    writeFileSync(mainLineCommandResultPath(runtimeManagerDir, command.commandId), JSON.stringify({
      schemaVersion: 1, source: "electron_main", commandId: command.commandId, type: command.type,
      operation: command.operation, accepted, ok: accepted, completed: true, ...(code ? { code } : {}),
      message: `${root} SECRET`, startedAt: "2026-10-26T00:00:00Z", settledAt: "2026-10-26T00:00:01Z", runMs: 1000,
    }));
    return { schemaVersion: 1 as const, accepted, code, operation: command.operation, commandId: command.commandId };
  });
  const realFacade = createAssistantProjectLifecycle({
    getPermissionSnapshot: () => ({ schemaVersion: 1, revision, projects: { synthetic: root } }),
    resolveNativeRuntimeManagerDir: () => runtimeManagerDir,
    resolveRuntimeContext: async () => ({ workspaceRoot: root, runtimeManagerDir, pythonPath: join(root, "python.exe"), operatorConfigPath: join(root, "test.toml") }),
    readStatus: async () => ({ state: "stopped" }),
  });
  // Isolate the receipt controller with a synthetic native facade: production
  // facade writes are suspended, while historical native receipts remain valid.
  let commandSequence = 0;
  const facade: typeof realFacade = { ...realFacade, dispatch: async (input, execution) => {
    const request = input as { projectId: string; operation: "start" | "stop" | "restart" };
    const command = { commandId: `cmd_fixture_${++commandSequence}`, operation: request.operation,
      type: ({ start: "open", stop: "close", restart: "restart" } as const)[request.operation], noBrowser: true };
    await execution?.onCommand?.(realFacade.bindingFor(request.projectId), command);
    const result = await execute(command);
    return { schemaVersion: 1, projectId: request.projectId, operation: request.operation,
      accepted: result.accepted, code: result.code ?? (result.accepted ? "accepted" : "rejected") };
  } };
  const make = () => createAssistantProjectLifecycleRequests({ facade, store: new AssistantProjectLifecycleRequestStore({ directory }) });
  const request = { requestId: "synthetic-request", projectId: "synthetic", operation: "restart" as const };
  return { root, directory, runtimeManagerDir, facade, execute, request, make, revoke: () => { revision++; } };
}

describe("assistant durable lifecycle request recovery", () => {
  it("reads historical active-work settlements after recreation, keeping queued restart distinct", async () => {
    const f = setup(true);
    const stop = { ...f.request, requestId: "native-stop", operation: "stop" as const };
    const restart = { ...f.request, requestId: "native-restart" };
    await f.make().dispatch(stop);
    await vi.waitFor(async () => expect(await f.make().receipt(stop)).toMatchObject({ state: "rejected", accepted: false, code: "active_work_blocked" }));
    await f.make().dispatch(restart);
    await vi.waitFor(async () => expect(await f.make().receipt(restart)).toMatchObject({ state: "queued", accepted: true, code: "restart_queued" }));
    const before = await new AssistantProjectLifecycleRequestStore({ directory: f.directory }).get(restart.requestId);
    expect(await f.make().dispatch(restart)).toMatchObject({ state: "queued", code: "restart_queued" });
    expect(await new AssistantProjectLifecycleRequestStore({ directory: f.directory }).get(restart.requestId)).toEqual(before);
  });

  it("recovers the native receipt after controller/store recreation without redispatch", async () => {
    const f = setup();
    const first = await f.make().dispatch(f.request);
    expect(first).toMatchObject({ state: "completed", code: "accepted", accepted: true });
    expect(await f.make().dispatch(f.request)).toEqual(first);
    expect(await f.make().receipt(f.request)).toEqual(first);
    expect(f.execute).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(first)).not.toContain(f.root);
    expect(JSON.stringify(first)).not.toContain("SECRET");
    expect(JSON.stringify(first)).not.toContain("cmd_");
  });

  it("never replays a reservation left unbound by a crash", async () => {
    const f = setup();
    await new AssistantProjectLifecycleRequestStore({ directory: f.directory }).reserve(f.request);
    expect(await f.make().dispatch(f.request)).toMatchObject({ state: "unknown", code: "request_unbound" });
    expect(f.execute).not.toHaveBeenCalled();
  });

  it("checks project permission before reserving capacity or revealing an unbound request", async () => {
    const f = setup();
    const store = new AssistantProjectLifecycleRequestStore({ directory: f.directory, maxRequests: 1 });
    const controller = createAssistantProjectLifecycleRequests({ facade: f.facade, store });
    const denied = { ...f.request, requestId: "bogus-request", projectId: "unregistered" };
    expect(await controller.dispatch(denied)).toMatchObject({ state: "rejected", code: "project_unavailable" });
    expect(await store.get(denied.requestId)).toBeNull();
    expect(await controller.dispatch(f.request)).toMatchObject({ state: "completed" });
    const unavailable = { ...f.facade, bindingFor: () => { throw new Error("revoked"); } };
    expect(await createAssistantProjectLifecycleRequests({ facade: unavailable, store }).receipt(f.request))
      .toMatchObject({ state: "rejected", code: "project_unavailable" });
    expect(f.execute).toHaveBeenCalledTimes(1);
  });

  it("rejects request ID reuse for another operation and revocation of a bound receipt", async () => {
    const f = setup(), controller = f.make();
    await controller.dispatch(f.request);
    expect(await controller.dispatch({ ...f.request, operation: "stop" })).toMatchObject({ state: "rejected", code: "request_conflict" });
    f.revoke();
    expect(await controller.receipt(f.request)).toMatchObject({ state: "rejected", code: "registration_changed" });
    expect(f.execute).toHaveBeenCalledTimes(1);
  });

  it.each(["missing", "error", "timeout", "handoff", "wrong-command", "queued", "blocked"])("projects %s evidence without inventing completion", async kind => {
    const f = setup(), controller = f.make();
    await controller.dispatch(f.request);
    const row = await new AssistantProjectLifecycleRequestStore({ directory: f.directory }).get(f.request.requestId);
    const path = mainLineCommandResultPath(f.runtimeManagerDir, row!.command!.commandId);
    const raw = JSON.parse(readFileSync(path, "utf8"));
    if (kind === "missing") rmSync(path);
    else {
      if (kind === "error") raw.completed = false;
      if (kind === "timeout") raw.timedOut = true;
      if (kind === "handoff") raw.source = "daemon";
      if (kind === "wrong-command") raw.commandId = "cmd_other";
      if (kind === "queued") raw.code = "restart_queued";
      if (kind === "blocked") { raw.code = "active_work_blocked"; raw.accepted = false; raw.ok = false; }
      writeFileSync(path, JSON.stringify(raw));
    }
    const result = await f.make().dispatch(f.request);
    expect(result.state).toBe(kind === "queued" ? "queued" : kind === "blocked" ? "rejected" : "unknown");
    expect(f.execute).toHaveBeenCalledTimes(1);
  });

  it("does not reserve on read-only lookup and rejects extra authority or getters", async () => {
    const f = setup(), controller = f.make();
    expect((await controller.receipt(f.request)).state).toBe("not_found");
    expect(await new AssistantProjectLifecycleRequestStore({ directory: f.directory }).get(f.request.requestId)).toBeNull();
    const getter = vi.fn(() => f.request.requestId);
    for (const input of [{ ...f.request, force: true }, { ...f.request, get requestId() { return getter(); } }]) {
      expect((await controller.dispatch(input)).code).toBe("request_invalid");
    }
    expect(getter).not.toHaveBeenCalled();
    expect(f.execute).not.toHaveBeenCalled();
  });

  it.each(["hardlink", "junction", "invalid-utf8", "oversized"])("refuses %s native receipt evidence without replay", async kind => {
    const f = setup(), controller = f.make();
    await controller.dispatch(f.request);
    const row = await new AssistantProjectLifecycleRequestStore({ directory: f.directory }).get(f.request.requestId);
    const path = mainLineCommandResultPath(f.runtimeManagerDir, row!.command!.commandId);
    if (kind === "hardlink") linkSync(path, join(f.root, "linked.json"));
    if (kind === "junction") {
      const moved = join(f.root, "moved-results");
      renameSync(join(f.runtimeManagerDir, "results"), moved);
      symlinkSync(moved, join(f.runtimeManagerDir, "results"), process.platform === "win32" ? "junction" : "dir");
    }
    if (kind === "invalid-utf8") writeFileSync(path, Buffer.from([0xff, 0xfe]));
    if (kind === "oversized") writeFileSync(path, " ".repeat(65 * 1024));
    expect(await controller.dispatch(f.request)).toMatchObject({ state: "unknown", code: "receipt_unavailable" });
    expect(f.execute).toHaveBeenCalledTimes(1);
  });
});
