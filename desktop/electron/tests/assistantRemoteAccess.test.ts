import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, isAbsolute } from "node:path";
import { EventEmitter } from "node:events";
import { Readable } from "node:stream";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AssistantHostBinding, AssistantHostRequest } from "../src/assistant/assistantHost.js";
import { openAssistantRemoteAccess } from "../src/assistant/assistantRemoteAccess.js";

const { createServer } = vi.hoisted(() => ({ createServer: vi.fn() }));
vi.mock("node:https", () => ({ createServer }));
vi.mock("node:crypto", async importOriginal => ({
  ...await importOriginal<typeof import("node:crypto")>(),
  X509Certificate: class { checkIP(ip: string) { return ip === "127.0.0.1"; } },
}));

const roots: string[] = [];
const token = "a".repeat(64);
const expected = { agentId: "assistant-one", sessionId: "session-one" };
const bindingQuery = `agentId=${expected.agentId}&sessionId=${expected.sessionId}`;
const profile = { assistant: { agentId: expected.agentId, directSessionId: expected.sessionId, displayName: "小助理",
  privateMetadata: "hidden" }, assistantAvatarRevision: "b".repeat(64) };
const timestamp = "2026-11-14T12:00:00Z";

afterEach(() => {
  for (const root of roots.splice(0)) {
    const path = relative(tmpdir(), root);
    if (!path.startsWith("assistant-remote-access-") || isAbsolute(path)) throw Error("test temp path escaped");
    rmSync(root, { recursive: true, force: true });
  }
  createServer.mockReset();
});

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "assistant-remote-access-"));
  roots.push(root);
  const directory = join(root, "assistant");
  mkdirSync(directory);
  const put = (extension: string, value: string) =>
    writeFileSync(join(directory, `remote-access.${extension}`), value, { mode: 0o600 });
  const server = Object.assign(new EventEmitter(), {
    listen: vi.fn((_port: number, _host: string, ready: () => void) => ready()),
    unref: vi.fn(), setTimeout: vi.fn(), close: vi.fn(), closeAllConnections: vi.fn(),
  });
  createServer.mockReturnValue(server);
  const native = vi.fn<(request: AssistantHostRequest, binding?: AssistantHostBinding, signal?: AbortSignal) => Promise<unknown>>();
  native.mockResolvedValue(profile);
  return {
    root, server, native, put,
    async open() {
      put("json", JSON.stringify({ port: 14841, token }));
      put("crt", "synthetic cert");
      put("key", "synthetic key");
      return openAssistantRemoteAccess(root, () => ({ request: native }), vi.fn());
    },
    async call(path: string, { method = "GET", body, host = "127.0.0.1:14841", authorization = `Bearer ${token}`,
      origin, address = "127.0.0.1", headers = {} }: {
      method?: string; body?: string; host?: string; authorization?: string; origin?: string; address?: string;
      headers?: Record<string, string>;
    } = {}) {
      const input = Object.assign(Readable.from(body === undefined ? [] : [Buffer.from(body)]), {
        url: path, method, socket: { remoteAddress: address }, headers: { host, authorization, origin,
          ...(body === undefined ? {} : { "content-type": "application/json" }), ...headers },
      });
      return new Promise<{ status: number; headers: Record<string, string>; body: Buffer; json(): unknown }>(resolve => {
        let receivedStatus: number, receivedHeaders: Record<string, string>;
        const output = Object.assign(new EventEmitter(), {
          writeHead(status: number, responseHeaders: Record<string, string>) {
            receivedStatus = status; receivedHeaders = responseHeaders;
          },
          end(bytes: Buffer) {
            resolve({ status: receivedStatus, headers: receivedHeaders, body: bytes,
              json: () => JSON.parse(bytes.toString("utf8")) });
          },
        });
        createServer.mock.calls[0][1](input, output);
      });
    },
  };
}

describe("Launcher assistant remote capability", () => {
  it("is off without configuration and rejects invalid provisioned ports", async () => {
    const { root, put } = fixture();
    const open = () => openAssistantRemoteAccess(root, () => null, vi.fn());
    expect(await open()).toBeNull();
    put("json", JSON.stringify({ port: 80, token }));
    await expect(open()).rejects.toThrow("ASSISTANT_REMOTE_CONFIG_INVALID");
    expect(createServer).not.toHaveBeenCalled();
  });

  it("binds TLS strictly to loopback and denies wrong peers, authorities, web origins and credentials before native access", async () => {
    const { open, call, native, server } = fixture();
    const handle = await open();
    expect(createServer).toHaveBeenCalledWith(expect.objectContaining({ minVersion: "TLSv1.2" }), expect.any(Function));
    expect(server.listen).toHaveBeenCalledWith(14841, "127.0.0.1", expect.any(Function));
    for (const input of [
      { authorization: "" }, { authorization: `Bearer ${"b".repeat(64)}` }, { host: "localhost:14841" },
      { origin: "null" }, { origin: "https://untrusted.invalid" }, { address: "192.0.2.1" }, { headers: { "sec-fetch-site": "same-origin" } },
    ]) expect((await call("/v1/assistant", input)).status).toBe(403);
    expect(native).not.toHaveBeenCalled();
    expect((await call("/v1/assistant")).json()).toEqual({
      ...expected, name: "小助理", status: "ready", avatarRevision: "b".repeat(64),
    });
    handle?.close();
    handle?.close();
    expect(server.close).toHaveBeenCalledTimes(1);
  });

  it("projects the native text window, filters process data, and paginates by the real message index", async () => {
    const { open, call, native } = fixture();
    await open();
    const row = (index: number, role: string, data: object) => ({ id: `${expected.sessionId}-message-${index}`, timestamp, role, ...data });
    const final = { type: "agent_message", phase: "final_answer", status: "completed", text: "最终回复" };
    native.mockResolvedValueOnce({
      id: expected.sessionId, agentId: expected.agentId, messageWindow: { nextBeforeMessageIndex: 2 },
      messages: [
        row(2, "user", { content: "较早问题" }), row(4, "user", { content: "最新问题", metadata: { hidden: true } }),
        row(5, "assistant", { turnItems: [
          { ...final, type: "reasoning", text: "private reasoning" },
          { ...final, phase: "commentary", text: "private commentary" },
          { ...final, status: "running", text: "partial" }, final,
        ] }),
      ],
    });
    const response = await call(`/v1/assistant/messages?${bindingQuery}&limit=2&beforeMessageIndex=6`);
    expect(response.json()).toEqual({
      ...expected, nextBeforeMessageIndex: 4,
      messages: [
        { id: "session-one-message-4", role: "user", text: "最新问题", timestamp, messageIndex: 4 },
        { id: "session-one-message-5", role: "assistant", text: "最终回复", timestamp, messageIndex: 5 },
      ],
    });
    expect(native).toHaveBeenCalledWith({ operation: "detail", beforeMessageIndex: 6 }, expected, expect.any(AbortSignal));
    for (const query of ["&limit=0", "&limit=51", "&beforeMessageIndex=01", "&beforeMessageIndex=2147483648", "&agentId=other", "&path=other"]) {
      expect((await call(`/v1/assistant/messages?${bindingQuery}${query}`)).status).toBe(400);
    }
    expect(native).toHaveBeenCalledTimes(1);
  });

  it("returns validated avatar bytes and emits 404 for a native missing image", async () => {
    const { open, call, native } = fixture();
    await open();
    const image = Buffer.from("synthetic png bytes");
    native.mockResolvedValueOnce({
      schemaVersion: 1, agentId: expected.agentId, image: { contentType: "image/png",
        dataBase64: image.toString("base64"), sha256: createHash("sha256").update(image).digest("hex") },
    });
    const path = `/v1/assistant/avatar?${bindingQuery}`;
    const response = await call(path);
    expect(response.body).toEqual(image);
    expect(response.headers["Content-Type"]).toBe("image/png");
    expect(response.headers["Cache-Control"]).toBe("no-store");
    native.mockResolvedValueOnce({ schemaVersion: 1, agentId: expected.agentId, image: null });
    expect((await call(path)).status).toBe(404);
  });

  it("binds terminal Assistant turns to exact requested submissions, including promoted queue items", async () => {
    const { open, call, native } = fixture();
    await open();
    const row = (index: number, role: string, data: object) =>
      ({ id: `${expected.sessionId}-message-${index}`, timestamp, role, ...data });
    const detail = {
      id: expected.sessionId, agentId: expected.agentId, messageWindow: { nextBeforeMessageIndex: null },
      status: "idle", lastTurnTerminalTurnId: "latest-turn", lastTurnStatus: "failed_provider",
      messages: [
        row(1, "user", { content: "accepted queued message", turnId: "promoted-turn",
          metadata: { clientSubmissionId: "queue-request", private: "never expose" } }),
        row(2, "assistant", { turnId: "promoted-turn", turnState: "completed", turnEndedAt: timestamp }),
        row(3, "user", { content: "request with an earlier stale reply", turnId: "pending-turn",
          metadata: { clientSubmissionId: "pending-request" } }),
        row(4, "assistant", { turnId: "wrong-turn", turnState: "completed", turnEndedAt: timestamp }),
        row(5, "assistant", { turnId: "pending-turn", turnState: "completed" }),
        row(6, "user", { content: "failed request", turnId: "latest-turn", metadata: { clientSubmissionId: "latest-request" } }),
      ],
    };
    native.mockResolvedValueOnce(detail);
    const response = await call(`/v1/assistant/messages?${bindingQuery}&completionId=queue-request&completionId=pending-request&completionId=latest-request`);
    expect(response.headers["X-Vibelution-Assistant-Completion"]).toBe("v1");
    expect(response.json().completions).toEqual([
      { id: "queue-request", turnId: "promoted-turn", state: "completed" },
      { id: "latest-request", turnId: "latest-turn", state: "failed" },
    ]);
    expect(response.body.toString("utf8")).not.toContain("never expose");
    expect(native).toHaveBeenCalledWith({ operation: "detail" }, expected, expect.any(AbortSignal));
    expect((await call(`/v1/assistant/messages?${bindingQuery}&completionId=queue-request&beforeMessageIndex=6`)).status).toBe(400);
    expect(native).toHaveBeenCalledTimes(1);
  });

  it("validates text-only writes, binds each native call, and preserves request IDs across ambiguous replies and retries", async () => {
    const { open, call, native } = fixture();
    await open();
    const send = (body: object) => call("/v1/assistant/messages", { method: "POST", body: JSON.stringify(body) });
    const payload = { ...expected, text: "从手机发送", requestId: "request-id" };
    for (const invalid of [{ ...payload, text: " " }, { ...payload, requestId: "id\n" }, { ...payload, operation: "config" },
      { ...payload, attachmentIds: [] }, { ...payload, text: "x".repeat(64_001) }]) {
      expect((await send(invalid)).status).toBe(400);
    }
    expect((await call("/v1/assistant/config")).status).toBe(404);
    expect(native).not.toHaveBeenCalled();
    native.mockRejectedValueOnce(new Error("ASSISTANT_IDENTITY_INVALID"));
    expect((await send({ ...payload, sessionId: "stale" })).json()).toEqual({ error: "assistant_identity_changed" });
    native.mockRejectedValueOnce(new Error("ASSISTANT_REQUEST_TIMEOUT"));
    expect((await send(payload)).json()).toEqual({ error: "assistant_submission_unconfirmed" });
    const receipt = { accepted: true, sessionId: expected.sessionId, clientSubmissionId: payload.requestId };
    native.mockResolvedValueOnce({ ...receipt, status: "queued", turnId: "", queuedTurnId: "native-queued" });
    expect((await send(payload)).json()).toEqual({
      accepted: true, status: "queued", requestId: payload.requestId, turnId: "", queuedTurnId: "native-queued",
    });
    native.mockResolvedValueOnce({ ...receipt, status: "completed", turnId: "native-turn" });
    expect((await send(payload)).json()).toEqual({
      accepted: true, status: "started", requestId: payload.requestId, turnId: "native-turn",
    });
    for (const invocation of native.mock.calls.slice(1)) {
      expect(invocation).toEqual([
        { operation: "send", message: payload.text, requestId: payload.requestId }, expected, expect.any(AbortSignal),
      ]);
    }
  });
});
