import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantHost, type AssistantHostRequest } from "../src/assistant/assistantHost.js";
import type { WorkbenchJobSpawnInput } from "../src/process/workbenchJob.js";

const fixtures: { host: AssistantHost; root: string }[] = [];
afterEach(async () => {
  for (const { host, root } of fixtures.splice(0)) {
    await host.stop();
    const relativeRoot = relative(tmpdir(), root);
    if (!relativeRoot || relativeRoot.startsWith("..") || isAbsolute(relativeRoot)) throw new Error("test temp path escaped");
    rmSync(root, { recursive: true, force: true });
  }
});

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "assistant-conversation-test-"));
  const python = join(root, "pythonw.exe");
  writeFileSync(python, "not launched");
  let active = true;
  const native = {
    spawn: vi.fn((input: WorkbenchJobSpawnInput) => {
      const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
      const generation = input.arguments[input.arguments.indexOf("--instance-id") + 1];
      writeFileSync(join(runtime, "ready.json"), JSON.stringify({ protocolVersion: 1, role: "launcher_assistant",
        instanceId: generation, pid: 900, port: 12345 }));
      return { pid: 100, job: {} };
    }),
    terminate: vi.fn(() => { active = false; return true; }), activeCount: vi.fn(() => active ? 1 : 0),
    drainStatus: vi.fn(() => ({ complete: true, channels: [] })), close: vi.fn(),
  };
  const rows = [{ id: "queued-one", position: 1, content: "next", status: "queued", kind: "user",
    references: [], attachments: [{ artifactId: "native-file" }], nativeExtra: { retained: true } }];
  const fetchImpl = vi.fn(async (...args: Parameters<typeof globalThis.fetch>): Promise<Response> => {
    const url = String(args[0]);
    if (url.endsWith("/health")) return Response.json({ status: "ok", protocolVersion: 1, role: "launcher_assistant" });
    if (url.endsWith("/api/assistant")) return Response.json({ assistant: { agentId: "a", directSessionId: "s" }, followupQueueVersion: 1 });
    if (url.endsWith("/shutdown")) { active = false; return Response.json({ stopping: true }); }
    if (url.endsWith("/send-now")) return Response.json({ queuedTurns: rows, stopRequested: true });
    return Response.json({ queuedTurns: rows });
  });
  const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"),
    sourceRoot: root, pythonPath: python, projects: {}, native, fetch: fetchImpl,
    env: { VIBELUTION_CONFIG_PATH: join(root, "config.toml") } });
  fixtures.push({ host, root });
  return { host, fetchImpl, rows };
}

describe("assistant fixed native queue transport", () => {
  it("forwards edits, withdrawals and fenced send-now without exposing Session selection to Python", async () => {
    const { host, fetchImpl, rows } = fixture();
    await host.start();
    const requests = [
      { operation: "updateQueuedTurn", sessionId: "s", queuedTurnId: "queued-one", content: "edited", position: 2, status: "paused" },
      { operation: "removeQueuedTurn", sessionId: "s", queuedTurnId: "queued-one" },
      { operation: "sendNowQueuedTurn", sessionId: "s", queuedTurnId: "queued-one", expectedTurnId: "observed-turn" },
    ] as const;
    for (const [index, request] of requests.entries()) {
      const expected = { queuedTurns: rows, ...(index === 2 ? { stopRequested: true } : {}) };
      await expect(host.request(request)).resolves.toEqual(expected);
      const [url, options] = fetchImpl.mock.calls.at(-1)!;
      expect(String(url)).toBe(`http://127.0.0.1:12345/api/assistant/queued-turns/${["update", "remove", "send-now"][index]}`);
      expect(options?.method).toBe("POST");
      const { operation: _operation, sessionId: _sessionId, ...body } = request;
      expect(JSON.parse(String(options?.body))).toEqual(body);
      expect(options?.headers).toMatchObject({ Authorization: expect.stringMatching(/^Bearer /) });
    }
    await expect(host.request({ operation: "status" })).resolves.toMatchObject({ followupQueueVersion: 1 });
  });

  it("refuses foreign Sessions, malformed IDs and extra fields before any RPC", async () => {
    const { host, fetchImpl } = fixture();
    await host.start();
    const calls = fetchImpl.mock.calls.length;
    for (const operation of ["updateQueuedTurn", "removeQueuedTurn", "sendNowQueuedTurn"]) {
      const request = { operation, sessionId: "s", queuedTurnId: "queued-one" };
      await expect(host.request({ ...request, sessionId: "foreign" } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_SESSION_FORBIDDEN");
      for (const extra of [{ queuedTurnId: "../other" }, { queuedTurnId: "q".repeat(161) }, { queuedTurnId: "queued-one\n" },
        { sessionId: "s\n" }, { agentId: "a" }, { projectRoot: "private" }, { expectedTurnId: "../other" }]) {
        await expect(host.request({ ...request, ...extra } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
      }
    }
    for (const fields of [{ content: null }, { content: 7 }, { content: "x".repeat(64001) }, { position: true },
      { position: 0 }, { position: 1.5 }, { position: Number.MAX_SAFE_INTEGER + 1 }, { status: "starting" }]) {
      await expect(host.request({ operation: "updateQueuedTurn", sessionId: "s", queuedTurnId: "queued-one", ...fields } as AssistantHostRequest))
        .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    }
    expect(fetchImpl.mock.calls.length).toBe(calls);
  });

  it("keeps the write pending behind migration and records lifecycle arrival", async () => {
    const { host, fetchImpl, rows } = fixture();
    await host.start();
    const lifecycle = host.beginLifecycleAdmission();
    const calls = fetchImpl.mock.calls.length;
    let settled = false;
    const write = host.request({ operation: "removeQueuedTurn", sessionId: "s", queuedTurnId: "queued-one" })
      .then(result => { settled = true; return result; });
    await Promise.resolve(); await Promise.resolve();
    expect(settled).toBe(false);
    expect(fetchImpl.mock.calls.length).toBe(calls);
    expect(() => lifecycle.check()).toThrow("ASSISTANT_LIFECYCLE_BUSY");
    lifecycle.release();
    await expect(write).resolves.toEqual({ queuedTurns: rows });
  });

  it("returns one failed write without replay and rejects malformed responses", async () => {
    const { host, fetchImpl } = fixture();
    await host.start();
    const request = { operation: "sendNowQueuedTurn", sessionId: "s", queuedTurnId: "queued-one", expectedTurnId: "old-turn" } as const;
    let calls = fetchImpl.mock.calls.length;
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: { code: "SESSION_CONFLICT" } }, { status: 409 }));
    await expect(host.request(request)).rejects.toThrow("ASSISTANT_SESSION_CONFLICT");
    expect(fetchImpl.mock.calls.length).toBe(calls + 1);
    for (const response of [{ queuedTurns: [] }, { queuedTurns: [], stopRequested: "yes" },
      { queuedTurns: {}, stopRequested: true }, { queuedTurns: [null], stopRequested: true },
      { queuedTurns: [], stopRequested: true, sessionId: "foreign" }]) {
      calls = fetchImpl.mock.calls.length;
      fetchImpl.mockResolvedValueOnce(Response.json(response));
      await expect(host.request(request)).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
      expect(fetchImpl.mock.calls.length).toBe(calls + 1);
    }
  });
});
