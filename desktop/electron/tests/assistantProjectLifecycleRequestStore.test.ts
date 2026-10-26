import { createHash } from "node:crypto";
import { fsyncSync, linkSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssistantProjectLifecycleRequestStore, AssistantProjectLifecycleRequestStoreError,
  type LifecycleRequestIdentity } from "../src/assistant/projectLifecycleRequestStore.js";

vi.mock("node:fs", async importOriginal => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, fsyncSync: vi.fn(actual.fsyncSync), renameSync: vi.fn(actual.renameSync), writeFileSync: vi.fn(actual.writeFileSync) };
});

const roots: string[] = [];
function fixture(maxRequests?: number) {
  const root = mkdtempSync(join(tmpdir(), "assistant-lifecycle-requests-"));
  roots.push(root);
  const directory = join(root, "requests");
  return { root, directory, store: new AssistantProjectLifecycleRequestStore({ directory, maxRequests }) };
}
afterEach(() => {
  vi.clearAllMocks();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});
const request = (requestId = "request-1", operation: LifecycleRequestIdentity["operation"] = "start") =>
  ({ requestId, projectId: "project:uuid", operation });
const recordPath = (directory: string, id = "request-1") => join(directory, `${createHash("sha256").update(id).digest("hex")}.json`);
const nativeCommand = (operation: LifecycleRequestIdentity["operation"] = "start") =>
  ({ commandId: "cmd_20261026T010203Z_abcdef12", type: ({ start: "open", stop: "close", restart: "restart" } as const)[operation], operation });
const bindingFor = (root: string) => ({ workspaceRoot: root, runtimeManagerDir: join(root, "runtime-manager"), registryFingerprint: "a".repeat(64) });

describe("assistant lifecycle request references", () => {
  it("durably reserves once across store instances and never renews a reservation", async () => {
    const { store, directory } = fixture();
    const request = { requestId: "request-1", projectId: "project:uuid", operation: "start" as const };
    const other = new AssistantProjectLifecycleRequestStore({ directory });
    const results = await Promise.all([store.reserve(request), other.reserve(request)]);
    expect(results.map(result => result.created).sort()).toEqual([false, true]);
    const created = results.find(result => result.created)!;
    expect(created.reservationToken).toMatch(/^[a-f0-9]{64}$/);
    expect(created.record).toEqual({ schemaVersion: 1, request, binding: null, command: null });
    expect(results.find(result => !result.created)).not.toHaveProperty("reservationToken");
    const reopened = new AssistantProjectLifecycleRequestStore({ directory });
    expect(await reopened.get(request.requestId)).toEqual(created.record);
    expect(await reopened.reserve(request)).toEqual({ created: false, record: created.record });
    expect(readdirSync(directory)).toEqual([recordPath(directory).split(/[\\/]/).at(-1)]);
    expect(fsyncSync).toHaveBeenCalled();
    expect(JSON.stringify(created.record)).not.toContain(created.reservationToken);
  });

  it("rejects conflicting request identities without changing the original reservation", async () => {
    const { store, directory } = fixture();
    await store.reserve(request());
    const before = readFileSync(recordPath(directory), "utf8");
    for (const next of [{ ...request(), projectId: "other" }, request("request-1", "stop")]) {
      await expect(store.reserve(next)).rejects.toMatchObject({ code: "request_conflict" });
    }
    expect(readFileSync(recordPath(directory), "utf8")).toBe(before);
    expect(await store.get("missing")).toBeNull();
  });

  it("atomically binds only the creator token, keeps identical binding idempotent, and reads it after restart", async () => {
    const { store, root, directory } = fixture();
    const reserved = await store.reserve(request());
    const token = reserved.reservationToken!, binding = bindingFor(root), command = nativeCommand();
    const other = new AssistantProjectLifecycleRequestStore({ directory });
    await expect(other.bind(request(), token, binding, command)).rejects.toMatchObject({ code: "reservation_invalid" });
    await expect(store.bind(request(), "b".repeat(64), binding, command)).rejects.toMatchObject({ code: "reservation_invalid" });
    const bound = await store.bind(request(), token, binding, command);
    expect(bound).toEqual({ schemaVersion: 1, request: request(), binding, command });
    expect(renameSync).toHaveBeenCalledTimes(1);
    expect(await store.bind(request(), token, binding, command)).toEqual(bound);
    expect(renameSync).toHaveBeenCalledTimes(1);
    expect(await new AssistantProjectLifecycleRequestStore({ directory }).get("request-1")).toEqual(bound);
    await expect(store.bind(request(), token, { ...binding, registryFingerprint: "b".repeat(64) }, command))
      .rejects.toMatchObject({ code: "binding_conflict" });
    await expect(store.bind(request(), token, binding, { ...command, commandId: "cmd_other" }))
      .rejects.toMatchObject({ code: "binding_conflict" });
    expect(await store.get("request-1")).toEqual(bound);
  });

  it("accepts start joining native restart and rejects every other cross-operation binding", async () => {
    const { store, root } = fixture();
    for (const operation of ["start", "stop", "restart"] as const) {
      for (const native of ["start", "stop", "restart"] as const) {
        const input = request(`${operation}-${native}`, operation);
        const token = (await store.reserve(input)).reservationToken!;
        const attempt = store.bind(input, token, bindingFor(root), nativeCommand(native));
        if (operation === native || (operation === "start" && native === "restart")) await expect(attempt).resolves.toMatchObject({ command: nativeCommand(native) });
        else await expect(attempt).rejects.toMatchObject({ code: "request_invalid" });
      }
    }
  });

  it("rejects non-opaque inputs, accessors, inherited properties, extra fields, and open operations before writing", async () => {
    const { store, directory } = fixture();
    const getter = vi.fn(() => "start");
    const accessor = Object.defineProperty({ requestId: "safe", projectId: "project" }, "operation", { get: getter, enumerable: true });
    const invalid: unknown[] = [accessor, Object.assign(Object.create(request()), {}), { ...request(), extra: true },
      { ...request(), [Symbol("extra")]: true }, { ...request(), operation: "force-stop" }, { ...request(), requestId: 1 }];
    for (const id of ["", ".", "..", "a/b", "C:\\repo", "https://example.com", "file:repo", "white space", "x\0y", "a".repeat(161)]) {
      invalid.push({ ...request(), requestId: id }, { ...request(), projectId: id });
    }
    for (const input of invalid) await expect(store.reserve(input as LifecycleRequestIdentity)).rejects.toMatchObject({ code: "request_invalid" });
    expect(getter).not.toHaveBeenCalled();
    expect(readdirSync(directory)).toEqual([]);
  });

  it("captures input values and never exposes mutable internal records", async () => {
    const { store, root } = fixture();
    const input = request(), reserved = await store.reserve(input);
    input.projectId = "mutated";
    reserved.record.request.projectId = "mutated-again";
    const binding = bindingFor(root), command = nativeCommand();
    const bound = await store.bind(request(), reserved.reservationToken!, binding, command);
    binding.workspaceRoot = "mutated";
    command.commandId = "cmd_mutated";
    bound.command!.commandId = "cmd_mutated-again";
    expect(await store.get("request-1")).toMatchObject({ request: request(), binding: bindingFor(root), command: nativeCommand() });
  });

  it("validates binding paths, fingerprint, closed command schema and native command IDs", async () => {
    const { store, root } = fixture();
    const token = (await store.reserve(request())).reservationToken!, binding = bindingFor(root), command = nativeCommand();
    for (const invalid of [{ ...binding, workspaceRoot: "relative" }, { ...binding, runtimeManagerDir: "file:///tmp" },
      { ...binding, registryFingerprint: "not-a-hash" }, { ...binding, extra: true }]) {
      await expect(store.bind(request(), token, invalid, command)).rejects.toMatchObject({ code: "request_invalid" });
    }
    for (const invalid of [{ ...command, commandId: "../../cmd_bad" }, { ...command, commandId: "cmd_" },
      { ...command, commandId: "other_safe" }, { ...command, type: "restart" }, { ...command, extra: true }]) {
      await expect(store.bind(request(), token, binding, invalid as typeof command)).rejects.toMatchObject({ code: "request_invalid" });
    }
    expect((await store.get("request-1"))!.command).toBeNull();
  });

  it("enforces capacity without evicting or blocking replay of an existing ID", async () => {
    const { store, directory } = fixture(1);
    const original = await store.reserve(request());
    await expect(store.reserve(request("second"))).rejects.toMatchObject({ code: "request_limit_exceeded" });
    expect(await store.reserve(request())).toEqual({ created: false, record: original.record });
    expect(readdirSync(directory)).toHaveLength(1);
  });

  it.each(["truncated", "oversize", "schema", "identity", "hash", "token", "half-bound"])("fails closed on %s records without repairing or deleting", async kind => {
    const { store, directory } = fixture();
    await store.reserve(request());
    const path = recordPath(directory), stored = JSON.parse(readFileSync(path, "utf8"));
    let raw: string;
    if (kind === "truncated") raw = "{";
    else if (kind === "oversize") raw = " ".repeat(16 * 1024 + 1);
    else {
      if (kind === "schema") stored.extra = true;
      if (kind === "identity") stored.request.operation = "unknown";
      if (kind === "hash") stored.request.requestId = "different";
      if (kind === "token") stored.reservationToken = "bad";
      if (kind === "half-bound") stored.command = nativeCommand();
      raw = JSON.stringify(stored);
    }
    writeFileSync(path, raw);
    await expect(store.get("request-1")).rejects.toMatchObject({ code: "request_store_invalid" });
    await expect(store.reserve(request())).rejects.toMatchObject({ code: "request_store_invalid" });
    expect(() => new AssistantProjectLifecycleRequestStore({ directory })).toThrow("request_store_invalid");
    expect(readFileSync(path, "utf8")).toBe(raw);
  });

  it("rejects uncontrolled directory entries and linked record files", async () => {
    const { store, root, directory } = fixture();
    await store.reserve(request());
    const path = recordPath(directory), external = join(root, "external.json");
    renameSync(path, external);
    linkSync(external, path);
    await expect(store.get("request-1")).rejects.toMatchObject({ code: "request_store_invalid" });
    rmSync(path);
    writeFileSync(path, readFileSync(external));
    mkdirSync(join(directory, "uncontrolled"));
    await expect(store.reserve(request("second"))).rejects.toMatchObject({ code: "request_store_invalid" });
  });

  it("rejects linked directories and parent redirection before reading or writing", async () => {
    const { store, root, directory } = fixture();
    await store.reserve(request());
    const moved = join(root, "moved");
    renameSync(directory, moved);
    symlinkSync(moved, directory, process.platform === "win32" ? "junction" : "dir");
    await expect(store.get("request-1")).rejects.toMatchObject({ code: "request_store_invalid" });
    expect(() => new AssistantProjectLifecycleRequestStore({ directory })).toThrow("request_store_invalid");
    rmSync(directory);
    mkdirSync(directory);
    await expect(store.reserve(request("second"))).rejects.toMatchObject({ code: "request_store_invalid" });
    expect(readdirSync(directory)).toEqual([]);
  });

  it("rejects invalid UTF-8 instead of silently changing persisted binding identity", async () => {
    const { store, root, directory } = fixture();
    const token = (await store.reserve(request())).reservationToken!;
    await store.bind(request(), token, bindingFor(root), nativeCommand());
    const path = recordPath(directory), row = JSON.parse(readFileSync(path, "utf8"));
    row.binding.workspaceRoot += "UTF8_MARKER";
    const raw = Buffer.from(JSON.stringify(row)), marker = raw.indexOf("UTF8_MARKER");
    const corrupt = Buffer.concat([raw.subarray(0, marker), Buffer.from([0xff]), raw.subarray(marker + "UTF8_MARKER".length)]);
    writeFileSync(path, corrupt);
    await expect(store.get("request-1")).rejects.toMatchObject({ code: "request_store_invalid" });
    expect(readFileSync(path)).toEqual(corrupt);
  });

  it("detects a redirected ancestor and never creates records through it", async () => {
    const { root } = fixture();
    const parent = join(root, "parent"), directory = join(parent, "requests"), moved = join(root, "moved-parent");
    const store = new AssistantProjectLifecycleRequestStore({ directory });
    await store.reserve(request());
    renameSync(parent, moved);
    symlinkSync(moved, parent, process.platform === "win32" ? "junction" : "dir");
    await expect(store.reserve(request("second"))).rejects.toMatchObject({ code: "request_store_invalid" });
    expect(readdirSync(join(moved, "requests"))).toHaveLength(1);
    rmSync(parent);
  });

  it("rejects symlink records even if their targets are otherwise valid", async () => {
    const { store, root, directory } = fixture();
    await store.reserve(request());
    const path = recordPath(directory), target = join(root, "external.json");
    renameSync(path, target);
    symlinkSync(target, path, "file");
    await expect(store.get("request-1")).rejects.toMatchObject({ code: "request_store_invalid" });
    expect(readFileSync(target, "utf8")).toContain("request-1");
  });

  it("does not renew reservations after a failed file sync and sanitizes errors", async () => {
    const { store, directory } = fixture();
    vi.mocked(fsyncSync).mockImplementationOnce(() => { throw new Error("private-path/secret"); });
    let failure: unknown;
    try { await store.reserve(request()); } catch (error) { failure = error; }
    expect(failure).toBeInstanceOf(AssistantProjectLifecycleRequestStoreError);
    expect(failure).toMatchObject({ code: "request_store_write_failed", message: "request_store_write_failed" });
    expect(String(failure)).not.toContain("secret");
    expect(await new AssistantProjectLifecycleRequestStore({ directory }).reserve(request())).toMatchObject({ created: false });
    const diskToken = JSON.parse(readFileSync(recordPath(directory), "utf8")).reservationToken;
    await expect(store.bind(request(), diskToken, bindingFor(directory), nativeCommand())).rejects.toMatchObject({ code: "reservation_invalid" });
  });

  it("retains partial reservations after failed writes and conservatively refuses retry", async () => {
    const { store, directory } = fixture();
    const original = vi.mocked(writeFileSync).getMockImplementation()!;
    vi.mocked(writeFileSync).mockImplementationOnce((path, _data, options) => {
      original(path, "{", options);
      throw new Error("private write failure");
    });
    await expect(store.reserve(request())).rejects.toMatchObject({ code: "request_store_write_failed" });
    expect(readFileSync(recordPath(directory), "utf8")).toBe("{");
    await expect(store.reserve(request())).rejects.toMatchObject({ code: "request_store_invalid" });
  });

  it("keeps the old reservation when atomic binding publication fails", async () => {
    const { store, root, directory } = fixture();
    const token = (await store.reserve(request())).reservationToken!;
    const before = readFileSync(recordPath(directory), "utf8");
    vi.mocked(renameSync).mockImplementationOnce(() => { throw new Error("private rename failure"); });
    await expect(store.bind(request(), token, bindingFor(root), nativeCommand())).rejects.toMatchObject({ code: "request_store_write_failed" });
    expect(readFileSync(recordPath(directory), "utf8")).toBe(before);
    expect(readdirSync(directory)).toHaveLength(1);
    expect((await store.bind(request(), token, bindingFor(root), nativeCommand())).command).toEqual(nativeCommand());
  });

  it("keeps an unbound reservation when binding file sync fails and never replays dispatch", async () => {
    const { store, root, directory } = fixture();
    const token = (await store.reserve(request())).reservationToken!;
    vi.mocked(fsyncSync).mockImplementationOnce(() => { throw new Error("private binding sync failure"); });
    await expect(store.bind(request(), token, bindingFor(root), nativeCommand())).rejects.toMatchObject({ code: "request_store_write_failed" });
    const reopened = new AssistantProjectLifecycleRequestStore({ directory });
    expect(await reopened.reserve(request())).toEqual({ created: false, record: { schemaVersion: 1, request: request(), binding: null, command: null } });
    expect(readdirSync(directory)).toHaveLength(1);
    await expect(reopened.bind(request(), token, bindingFor(root), nativeCommand())).rejects.toMatchObject({ code: "reservation_invalid" });
  });
});
