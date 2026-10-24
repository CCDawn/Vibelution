import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdtemp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { createConnection, createServer, type Socket } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { startNativeLauncherStartTransport, type NativeStartResult } from "../src/process/nativeLauncherStart.js";

type Metadata = {
  schemaVersion: number; protocolVersion: number; workspaceRoot: string;
  pid: number; createTime: number; executable: string; pipeName: string; token: string;
};
const roots: string[] = [];
const transports: Array<{ close(): Promise<void> }> = [];
const clients = new Set<Socket>();
const identity = { pid: process.pid, createTime: 123.456, executable: process.execPath };
const delay = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, failed) => { resolve = done; reject = failed; });
  return { promise, resolve, reject };
}
async function fixture(onStart = vi.fn(async (): Promise<NativeStartResult> => ({
  accepted: true, commandId: "command-final", code: "healthy", message: "Started.",
}))) {
  const root = await mkdtemp(join(tmpdir(), "vib-native-"));
  roots.push(root);
  const runtimeDir = join(root, "runtime");
  const socketPath = process.platform === "win32" ? undefined : join(root, "start.sock");
  const transport = await startNativeLauncherStartTransport({ workspaceRoot: root, runtimeDir, identity, onStart, socketPath });
  transports.push(transport);
  const metadataPath = join(runtimeDir, "native-start-transport.json");
  const metadata = JSON.parse(await readFile(metadataPath, "utf8")) as Metadata;
  const endpoint = process.platform === "win32" ? `\\\\.\\pipe\\${metadata.pipeName}` : socketPath!;
  return { root, runtimeDir, metadataPath, metadata, endpoint, onStart, transport };
}
async function connect(endpoint: string): Promise<Socket> {
  const socket = createConnection(endpoint);
  clients.add(socket);
  socket.on("error", () => {});
  socket.on("close", () => clients.delete(socket));
  await new Promise<void>((done, failed) => {
    socket.once("connect", done);
    socket.once("error", failed);
  });
  return socket;
}
function readResponse(socket: Socket): Promise<Record<string, unknown> | null> {
  return new Promise((done, failed) => {
    let bytes = Buffer.alloc(0);
    socket.on("data", (chunk: Buffer) => { bytes = Buffer.concat([bytes, chunk]); });
    socket.once("close", () => {
      if (!bytes.length) { done(null); return; }
      try {
        expect(bytes.length).toBeLessThanOrEqual(8192);
        expect(bytes.toString("utf8").split("\n")).toHaveLength(2);
        done(JSON.parse(bytes.toString("utf8")) as Record<string, unknown>);
      } catch (error) { failed(error); }
    });
    socket.on("end", () => socket.end());
  });
}
function request(metadata: Metadata, overrides: Record<string, unknown> = {}) {
  return { schemaVersion: 1, protocolVersion: 1, requestId: `launch_${randomUUID().replaceAll("-", "")}`,
    workspaceRoot: metadata.workspaceRoot, operation: "start", token: metadata.token, ...overrides };
}
async function exchange(f: Awaited<ReturnType<typeof fixture>>, body: unknown) {
  const socket = await connect(f.endpoint);
  const response = readResponse(socket);
  socket.write(`${JSON.stringify(body)}\n`);
  return response;
}

afterEach(async () => {
  for (const socket of clients) socket.destroy();
  await Promise.all(transports.splice(0).map((transport) => transport.close().catch(() => {})));
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});

describe("native Launcher start local transport", () => {
  it("publishes complete flat identity only after a real listener exists and removes its own metadata", async () => {
    const f = await fixture();
    expect(f.metadata).toMatchObject({ schemaVersion: 1, protocolVersion: 1, workspaceRoot: resolve(f.root), ...identity });
    expect(f.metadata.token).toMatch(/^[a-f0-9]{64}$/);
    expect(f.metadata.pipeName).toMatch(new RegExp(`^vibelution-native-start-${process.pid}-[a-f0-9-]+$`));
    expect(await readdir(f.runtimeDir)).toEqual(["native-start-transport.json"]);
    if (process.platform !== "win32") expect((await stat(f.metadataPath)).mode & 0o777).toBe(0o600);
    const body = request(f.metadata);
    expect(await exchange(f, body)).toMatchObject({ schemaVersion: 1, protocolVersion: 1,
      requestId: body.requestId, workspaceRoot: f.root, accepted: true, commandId: "command-final", code: "healthy" });
    await f.transport.close();
    await expect(readFile(f.metadataPath)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(connect(f.endpoint)).rejects.toBeDefined();
  });

  it.each([
    { token: "0".repeat(64) }, { token: "invalid" }, { workspaceRoot: "relative" },
    { workspaceRoot: resolve(tmpdir(), "another-workspace") }, { protocolVersion: 2 }, { schemaVersion: 2 },
    { operation: "stop" }, { operation: "start", action: "start" }, { hidden: false }, { force: false },
    { extra: "ignored" }, { requestId: "launch_invalid" }, { token: undefined },
  ])("rejects untrusted or extra request fields without dispatch: %j", async (overrides) => {
    const f = await fixture();
    expect(await exchange(f, request(f.metadata, overrides))).toMatchObject({ accepted: false, code: "native_invalid_request" });
    expect(f.onStart).not.toHaveBeenCalled();
  });

  it("normalizes Windows workspace case and retains original request correlation", async () => {
    const f = await fixture();
    const body = request(f.metadata, { workspaceRoot: process.platform === "win32" ? f.root.toUpperCase() : f.root });
    expect(await exchange(f, body)).toMatchObject({ accepted: true, requestId: body.requestId, workspaceRoot: f.root });
  });

  it("accepts fragmented UTF-8 JSON and handles multiple frames on one socket exactly once", async () => {
    const f = await fixture();
    const body = request(f.metadata, { workspaceRoot: `${f.root}${sep}文${sep}..` });
    const bytes = Buffer.from(`${JSON.stringify(body)}\n${JSON.stringify(body)}\n`);
    const splitInsideCharacter = bytes.indexOf(Buffer.from("文")) + 1;
    const socket = await connect(f.endpoint);
    const response = readResponse(socket);
    socket.write(bytes.subarray(0, splitInsideCharacter));
    await delay(15);
    expect(f.onStart).not.toHaveBeenCalled();
    socket.write(bytes.subarray(splitInsideCharacter));
    expect(await response).toMatchObject({ accepted: true, requestId: body.requestId });
    expect(f.onStart).toHaveBeenCalledOnce();
  });

  it.each([Buffer.alloc(2049, 32), Buffer.concat([Buffer.from([0xff]), Buffer.from("\n")]), Buffer.from("[]\n")])(
    "rejects oversized, malformed UTF-8, and non-object frames", async (bytes) => {
      const f = await fixture();
      const socket = await connect(f.endpoint);
      const response = readResponse(socket);
      socket.write(bytes);
      expect(await response).toMatchObject({ accepted: false, code: "native_invalid_request" });
      expect(f.onStart).not.toHaveBeenCalled();
    },
  );

  it("ends an idle incomplete frame, with no callback", async () => {
    const f = await fixture();
    const socket = await connect(f.endpoint);
    const response = readResponse(socket);
    socket.write("{");
    expect(await response).toBeNull();
    expect(f.onStart).not.toHaveBeenCalled();
  });

  it("waits for the owner's final result beyond the read idle deadline", async () => {
    const final = deferred<NativeStartResult>();
    const f = await fixture(vi.fn(() => final.promise));
    const socket = await connect(f.endpoint);
    let responded = false;
    const response = readResponse(socket).then((value) => { responded = true; return value; });
    const body = request(f.metadata);
    socket.write(`${JSON.stringify(body)}\n`);
    await vi.waitFor(() => expect(f.onStart).toHaveBeenCalledOnce());
    await delay(1100);
    expect(responded).toBe(false);
    final.resolve({ accepted: true, commandId: "settled-owner-command", code: "already_healthy", message: "Ready." });
    expect(await response).toMatchObject({ requestId: body.requestId, commandId: "settled-owner-command", code: "already_healthy" });
  });

  it.each([
    [{ accepted: false, code: "native_requires_legacy_launch" }, true],
    [{ accepted: false, code: "native_requires_legacy_launch", commandId: "already-dispatched" }, false],
    [{ accepted: false, code: "failed" }, false],
  ] as const)("marks no dispatch only for the explicit owner's fallback: %j", async (result, notDispatched) => {
    const f = await fixture(vi.fn(async () => result));
    const response = await exchange(f, request(f.metadata));
    expect(response).toMatchObject(result);
    expect(response?.notDispatched === true).toBe(notDispatched);
  });

  it("does not expose thrown or rejected exception contents", async () => {
    const f = await fixture(vi.fn(() => { throw new Error("private exception"); }));
    expect(await exchange(f, request(f.metadata))).toMatchObject({ accepted: false, code: "native_start_failed" });
    f.onStart.mockImplementation(async () => { throw new Error(f.metadata.token); });
    const response = await exchange(f, request(f.metadata));
    expect(response).toMatchObject({ accepted: false, code: "native_start_failed" });
    expect(JSON.stringify(response)).not.toContain(f.metadata.token);
  });

  it("bounds owner messages and keeps secrets out of the response", async () => {
    const f = await fixture();
    f.onStart.mockResolvedValue({ accepted: false, code: "failed", message: `${f.metadata.token}${"文".repeat(10000)}` });
    const response = await exchange(f, request(f.metadata));
    expect(response?.accepted).toBe(false);
    expect(String(response?.message).length).toBeLessThanOrEqual(1024);
    expect(JSON.stringify(response)).not.toContain(f.metadata.token);
  });

  it("does not cancel or repeat a dispatched operation when its client disconnects", async () => {
    const final = deferred<NativeStartResult>();
    const f = await fixture(vi.fn(() => final.promise));
    const socket = await connect(f.endpoint);
    socket.write(`${JSON.stringify(request(f.metadata))}\n`);
    await vi.waitFor(() => expect(f.onStart).toHaveBeenCalledOnce());
    socket.destroy();
    final.resolve({ accepted: true, commandId: "continued" });
    await delay(20);
    expect(f.onStart).toHaveBeenCalledOnce();
  });

  it("caps connections at eight without introducing an operation queue", async () => {
    const final = deferred<NativeStartResult>();
    const f = await fixture(vi.fn(() => final.promise));
    for (let index = 0; index < 8; index += 1) {
      const socket = await connect(f.endpoint);
      socket.write(`${JSON.stringify(request(f.metadata))}\n`);
    }
    await vi.waitFor(() => expect(f.onStart).toHaveBeenCalledTimes(8));
    const ninth = await connect(f.endpoint);
    const response = readResponse(ninth);
    ninth.write(`${JSON.stringify(request(f.metadata))}\n`);
    expect(await response).toBeNull();
    expect(f.onStart).toHaveBeenCalledTimes(8);
    final.resolve({ accepted: true });
  });

  it.each(["pid", "token", "both"])("shuts down pending operations promptly and preserves metadata with a different %s", async (changed) => {
    const final = deferred<NativeStartResult>();
    const f = await fixture(vi.fn(() => final.promise));
    const active = await connect(f.endpoint);
    const activeResponse = readResponse(active);
    active.write(`${JSON.stringify(request(f.metadata))}\n`);
    await vi.waitFor(() => expect(f.onStart).toHaveBeenCalledOnce());
    const incomplete = await connect(f.endpoint);
    incomplete.write("{");
    const replacement = { ...f.metadata,
      pid: changed === "token" ? identity.pid : identity.pid + 1,
      token: changed === "pid" ? f.metadata.token : "f".repeat(64),
    };
    await writeFile(f.metadataPath, JSON.stringify(replacement));
    await Promise.race([f.transport.close(), delay(500).then(() => { throw new Error("shutdown waited for callback"); })]);
    expect(await activeResponse).toBeNull();
    expect(JSON.parse(await readFile(f.metadataPath, "utf8"))).toEqual(replacement);
    final.reject(new Error("late private rejection"));
    await delay(20);
    expect(f.onStart).toHaveBeenCalledOnce();
  });

  it("revokes synchronously before exit and cannot delete a replacement published during close", async () => {
    const f = await fixture();
    const closing = f.transport.close();
    expect(existsSync(f.metadataPath)).toBe(false);
    const replacement = await startNativeLauncherStartTransport({
      workspaceRoot: f.root, runtimeDir: f.runtimeDir, identity,
      onStart: vi.fn(async () => ({ accepted: false })),
    });
    transports.push(replacement);
    const published = JSON.parse(await readFile(f.metadataPath, "utf8"));
    expect(published.token).not.toBe(f.metadata.token);
    await closing;
    expect(JSON.parse(await readFile(f.metadataPath, "utf8"))).toEqual(published);
  });

  it("closes its listener and removes temporary files when atomic metadata publication fails", async () => {
    const root = await mkdtemp(join(tmpdir(), "vib-native-"));
    roots.push(root);
    const metadataPath = join(root, "native-start-transport.json");
    await mkdir(metadataPath);
    const socketPath = process.platform === "win32" ? undefined : join(root, "failed.sock");
    await expect(startNativeLauncherStartTransport({ workspaceRoot: root, runtimeDir: root, identity,
      onStart: vi.fn(async () => ({ accepted: true })), socketPath })).rejects.toThrow("Could not publish native start transport.");
    expect(await readdir(root)).toEqual(["native-start-transport.json"]);
    if (socketPath) await expect(connect(socketPath)).rejects.toBeDefined();
  });

  it.skipIf(process.platform === "win32")("does not disturb an existing listener when bind fails", async () => {
    const root = await mkdtemp(join(tmpdir(), "vib-native-"));
    roots.push(root);
    const socketPath = join(root, "occupied.sock");
    const existing = createServer((socket) => socket.end());
    await new Promise<void>((done) => existing.listen(socketPath, done));
    try {
      await expect(startNativeLauncherStartTransport({ workspaceRoot: root, runtimeDir: root, identity,
        onStart: vi.fn(async () => ({ accepted: true })), socketPath })).rejects.toThrow();
      const socket = await connect(socketPath);
      socket.destroy();
    } finally {
      await new Promise<void>((done) => existing.close(() => done()));
    }
  });
});
