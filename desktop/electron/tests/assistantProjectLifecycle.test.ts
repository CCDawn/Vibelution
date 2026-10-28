import { mkdtempSync, mkdirSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAssistantProjectLifecycle, type AssistantProjectLifecycleOptions } from "../src/assistant/projectLifecycle.js";

const A = "project-a:11111111-1111-4111-8111-111111111111";
const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });

function setup() {
  const temp = mkdtempSync(join(tmpdir(), "assistant-project-lifecycle-")); roots.push(temp);
  const path = join(temp, "project"); mkdirSync(path);
  const physical = realpathSync.native(path);
  const root = process.platform === "win32" ? physical.toLowerCase() : physical;
  let snapshot = { schemaVersion: 1 as const, revision: 1, projects: { [A]: root } as Record<string, string> };
  const run = vi.fn(async () => ({ schemaVersion: 1 as const, accepted: true, operation: "start" }));
  const resolveRuntime = vi.fn(async () => null);
  const readStatus = vi.fn(async () => ({ state: "stopped", activeWorkCount: 0, token: "SECRET" }));
  const options: AssistantProjectLifecycleOptions = { getPermissionSnapshot: () => snapshot, resolveRuntimeContext: resolveRuntime, readStatus, runLifecycle: run };
  return { root, run, resolveRuntime, readStatus, options, facade: createAssistantProjectLifecycle(options), change: (next: typeof snapshot) => { snapshot = next; }, snapshot: () => snapshot };
}

describe("registered project lifecycle facade", () => {
  it.each(["start", "stop", "restart"] as const)("blocks new assistant %s before the native runner", async operation => {
    const f = setup(), onCommand = vi.fn();
    expect(await f.facade.dispatch({ projectId: A, operation }, { onCommand })).toEqual({
      schemaVersion: 1, projectId: A, operation, accepted: false, code: "prerequisite_required",
    });
    expect(f.resolveRuntime).not.toHaveBeenCalled();
    expect(f.run).not.toHaveBeenCalled();
    expect(onCommand).not.toHaveBeenCalled();
  });

  it("retains read-only status and trusted binding without exposing native details", async () => {
    const f = setup();
    expect(await f.facade.dispatch({ projectId: A, operation: "status" })).toEqual({ schemaVersion: 1, projectId: A, operation: "status", accepted: true, code: "status", status: { state: "stopped", activeWorkCount: 0 } });
    expect(f.facade.bindingFor(A)).toMatchObject({ workspaceRoot: f.root, registryFingerprint: expect.stringMatching(/^[a-f0-9]{64}$/) });
    expect(f.resolveRuntime).not.toHaveBeenCalled(); expect(f.run).not.toHaveBeenCalled();
  });

  it("rejects invalid and unregistered writes before reaching native execution", async () => {
    const f = setup(), getter = vi.fn(() => A);
    for (const input of [null, [], {}, { projectId: A, operation: "force-stop" }, { projectId: A, operation: "stop", force: true }, { projectId: A, operation: "start", get extra() { return getter(); } }]) {
      expect((await f.facade.dispatch(input)).code).toBe("invalid_request");
    }
    expect(getter).not.toHaveBeenCalled();
    expect((await f.facade.dispatch({ projectId: "unknown", operation: "start" })).code).toBe("project_unavailable");
    expect(f.run).not.toHaveBeenCalled();
  });

  it("rechecks authorization after status I/O", async () => {
    const f = setup(); let finish!: () => void, entered!: () => void;
    const gate = new Promise<void>(resolve => { finish = resolve; });
    const started = new Promise<void>(resolve => { entered = resolve; });
    f.readStatus.mockImplementation(async () => { entered(); await gate; return { state: "stopped", activeWorkCount: 0, token: "SECRET" }; });
    const result = f.facade.dispatch({ projectId: A, operation: "status" });
    await started; f.change({ ...f.snapshot(), revision: 2 }); finish();
    expect((await result).code).toBe("registration_changed"); expect(f.run).not.toHaveBeenCalled();
  });

  it("rejects changed physical roots before status or writes", async () => {
    const f = setup(); f.options.realPath = () => join(f.root, "other");
    const facade = createAssistantProjectLifecycle(f.options);
    expect((await facade.dispatch({ projectId: A, operation: "status" })).code).toBe("registration_changed");
    expect((await facade.dispatch({ projectId: A, operation: "stop" })).code).toBe("registration_changed");
    expect(f.readStatus).not.toHaveBeenCalled(); expect(f.run).not.toHaveBeenCalled();
  });
});
