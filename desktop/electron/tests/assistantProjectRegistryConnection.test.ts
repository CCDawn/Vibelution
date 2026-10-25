import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import type { AssistantProjectRegistrySnapshot } from "../src/assistant/projectRegistry.js";

const roots: string[] = [];
const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
};
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "assistant-registry-connection-")); roots.push(root);
  const filePath = join(root, "assistant", "projects.json");
  const directory = (name: string) => {
    const path = join(root, name); mkdirSync(join(path, ".vibelution"), { recursive: true });
    writeFileSync(join(path, ".vibelution", "project.json"), JSON.stringify({ projectId: "same-project" }));
    return path;
  };
  const integrationRoot = directory("integration");
  const row = (path: string, id = "worktree:task", checkedOut = true) => ({ id, path, checkedOut, alive: false });
  const payload = (items: unknown[], group = integrationRoot) => ({ schemaVersion: 1, integrationRoot: group, items });
  const connection = new AssistantProjectRegistryConnection(filePath);
  const host = { start: vi.fn(async () => undefined), stop: vi.fn(async () => undefined), updateProjects: vi.fn(async (_snapshot: AssistantProjectRegistrySnapshot) => undefined) };
  return { root, filePath, directory, integrationRoot, row, payload, connection, host };
}
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe("main-owned assistant registry connection", () => {
  it("grants checked-out inventory, revokes an authoritative empty group, and re-adds with a new UUID", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.start(() => f.host);
    await f.connection.reconcile(f.payload([f.row(project), f.row("", "branch:inactive", false)]));
    const first = f.host.updateProjects.mock.calls[0][0];
    const id = Object.keys(first.projects)[0];
    expect(id).toMatch(/^same-project:worktree:task:[a-f0-9]{12}:[a-f0-9]{24}:[a-f0-9-]{36}$/);
    expect(Object.values(first.projects)).toEqual([process.platform === "win32" ? realpathSync.native(project).toLowerCase() : realpathSync.native(project)]);
    await f.connection.reconcile(f.payload([]));
    expect(f.host.updateProjects.mock.calls[1][0]).toEqual({ schemaVersion: 1, revision: 2, projects: {} });
    await f.connection.reconcile(f.payload([f.row(project)]));
    expect(f.host.updateProjects.mock.calls[2][0].projects).not.toHaveProperty(id);
    expect(JSON.parse(readFileSync(f.filePath, "utf8")).registrations.map((r: any) => r.active)).toEqual([false, true]);
  });

  it("loads persisted roots before host.start without native inventory or a workspace", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const connection = new AssistantProjectRegistryConnection(f.filePath);
    let captured!: AssistantProjectRegistrySnapshot;
    await connection.start(snapshot => { captured = snapshot; expect(f.host.start).not.toHaveBeenCalled(); return f.host; });
    expect(captured.revision).toBe(1);
    expect(Object.values(captured.projects)).toHaveLength(1);
    expect(f.host.start).toHaveBeenCalledTimes(1);
  });

  it("constructs a host from the latest queued inventory and sends only increasing revisions", async () => {
    const f = fixture(), project = f.directory("task");
    const observation = f.connection.reconcile(f.payload([f.row(project)]));
    let captured!: AssistantProjectRegistrySnapshot;
    const startup = f.connection.start(snapshot => { captured = snapshot; return f.host; });
    await Promise.all([observation, startup]);
    expect(captured.revision).toBe(1);
    expect(Object.values(captured.projects)).toHaveLength(1);
    await f.connection.reconcile(f.payload([f.row(project)]));
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    await f.connection.reconcile(f.payload([]));
    expect(f.host.updateProjects.mock.calls[0][0].revision).toBe(2);
  });

  it("namespaces cloned project IDs by physical integration root and preserves other groups", async () => {
    const f = fixture(), a = f.directory("a"), b = f.directory("b");
    await f.connection.start(() => f.host);
    await f.connection.reconcile(f.payload([f.row(a)]));
    await f.connection.reconcile(f.payload([f.row(b)], b));
    expect(Object.keys(f.host.updateProjects.mock.calls[1][0].projects)).toHaveLength(2);
    await f.connection.reconcile(f.payload([]));
    expect(Object.values(f.host.updateProjects.mock.calls[2][0].projects)).toEqual([process.platform === "win32" ? realpathSync.native(b).toLowerCase() : realpathSync.native(b)]);
  });

  it.each([
    null,
    { schemaVersion: 1, integrationRoot: "relative", items: [] },
    { schemaVersion: 1, items: [] },
    "missing-row", "missing-id", "missing-checkedOut", "relative-path", "unchecked-malformed", "duplicate-id",
  ])("rejects malformed inventory without grants, revocation or a host call: %s", async invalid => {
    const f = fixture(), project = f.directory("task");
    await f.connection.start(() => f.host);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const before = readFileSync(f.filePath, "utf8");
    const badRows: Record<string, unknown[]> = {
      "missing-row": [f.row(project), null], "missing-id": [{ checkedOut: true, path: project }],
      "missing-checkedOut": [{ id: "task", path: project }], "relative-path": [f.row("relative")],
      "unchecked-malformed": [{ id: "branch", checkedOut: "false", path: "" }],
      "duplicate-id": [f.row(project), f.row(project)],
    };
    await expect(f.connection.reconcile(typeof invalid === "string" ? f.payload(badRows[invalid]) : invalid)).rejects.toThrow("ASSISTANT_INVENTORY_INVALID");
    expect(readFileSync(f.filePath, "utf8")).toBe(before);
    expect(f.host.updateProjects).toHaveBeenCalledTimes(1);
    expect(f.host.stop).not.toHaveBeenCalled();
  });

  it("serializes startup and each update, and resolves a revocation only after its matching ACK", async () => {
    const f = fixture(), project = f.directory("task"), startup = deferred(), ack = deferred();
    f.host.start.mockImplementation(() => startup.promise);
    const starting = f.connection.start(() => f.host);
    const granting = f.connection.reconcile(f.payload([f.row(project)]));
    await vi.waitFor(() => expect(f.host.start).toHaveBeenCalled());
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    startup.resolve(); await starting; await granting;
    f.host.updateProjects.mockImplementation(() => ack.promise);
    let revoked = false;
    const removing = f.connection.reconcile(f.payload([])).then(() => { revoked = true; });
    await vi.waitFor(() => expect(f.host.updateProjects).toHaveBeenCalledTimes(2));
    const third = f.connection.reconcile(f.payload([f.row(project)]));
    expect(revoked).toBe(false);
    expect(f.host.updateProjects).toHaveBeenCalledTimes(2);
    ack.resolve(); await removing; await third;
    expect(f.host.updateProjects.mock.calls.map(([snapshot]) => snapshot.revision)).toEqual([1, 2, 3]);
  });

  it("retires only its host after an unknown update, and never replays or restarts", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.start(() => f.host);
    f.host.updateProjects.mockRejectedValue(new Error("ASSISTANT_REGISTRY_UNCONFIRMED"));
    await expect(f.connection.reconcile(f.payload([f.row(project)]))).rejects.toThrow("ASSISTANT_REGISTRY_UNCONFIRMED");
    await expect(f.connection.reconcile(f.payload([]))).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED");
    await expect(f.connection.start(() => f.host)).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED");
    expect(f.host.stop).toHaveBeenCalledTimes(1);
    expect(f.host.updateProjects).toHaveBeenCalledTimes(1);
  });

  it("closes admission immediately on shutdown and does not replay a queued observation", async () => {
    const f = fixture(); await f.connection.start(() => f.host);
    const queued = f.connection.reconcile(f.payload([]));
    const stopped = f.connection.stop();
    await expect(queued).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED"); await stopped;
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    expect(f.host.stop).toHaveBeenCalledTimes(1);
  });

  it("retains its owned host for cleanup retry when retirement fails", async () => {
    const f = fixture(); await f.connection.start(() => f.host);
    f.host.stop.mockRejectedValueOnce(new Error("OWNED_JOB_RETIRE_FAILED"));
    await expect(f.connection.stop()).rejects.toThrow("OWNED_JOB_RETIRE_FAILED");
    await f.connection.stop();
    expect(f.host.stop).toHaveBeenCalledTimes(2);
  });

  it("fails closed on corrupt persisted grants and missing roots, and revokes deleted roots on valid inventory", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.reconcile(f.payload([f.row(project)]));
    rmSync(project, { recursive: true });
    expect(() => new AssistantProjectRegistryConnection(f.filePath)).toThrow("PROJECT_REGISTRY_RECONCILE_REQUIRED");
    await f.connection.reconcile(f.payload([f.row(project)]));
    let snapshot!: AssistantProjectRegistrySnapshot;
    await f.connection.start(value => { snapshot = value; return f.host; });
    expect(snapshot.projects).toEqual({});
    writeFileSync(f.filePath, "{broken");
    expect(() => new AssistantProjectRegistryConnection(f.filePath)).toThrow("PROJECT_REGISTRY_INVALID");
  });
});
