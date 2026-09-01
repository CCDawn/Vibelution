import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchJson,
  fetchWithControl,
  isFetchJsonHttpError,
  isFetchAbortError,
  resetControlTokenForTests,
  setFetchJsonFailureReporter,
} from "./client";
import {
  pushClientOperationContext,
  resetClientOperationContextForTests,
} from "../app/clientOperationContext";

describe("fetchJson control token", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetControlTokenForTests();
    resetClientOperationContextForTests();
    setFetchJsonFailureReporter(null);
  });

  it("adds the web control token header to mutating requests", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ ok: boolean }>("/api/runtime/shutdown", { method: "POST" });

    expect(payload.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    const headers = requestInit.headers as Headers;
    expect(headers.get("X-Vibelution-Control-Token")).toBe("test-token");
    expect(requestInit.credentials).toBe("same-origin");
  });

  it("attaches the control token to read-only API requests too", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "t" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: "ok" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ status: string }>("/api/health");

    expect(payload.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/control-token");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/health");
  });

  it("returns an unread guarded response for streaming adapters", async () => {
    const streamResponse = new Response("event: ready\ndata: {}\n\n", {
      headers: { "Content-Type": "text/event-stream" },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "stream-token" }),
      })
      .mockResolvedValueOnce(streamResponse);
    vi.stubGlobal("fetch", fetchMock);

    const response = await fetchWithControl("/api/research/workflow-runs/run-a/stream");

    expect(response).toBe(streamResponse);
    expect(response.bodyUsed).toBe(false);
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(new Headers(requestInit.headers).get("X-Vibelution-Control-Token")).toBe("stream-token");
  });

  it("does not attach the local control token to external writes", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ ok: boolean }>("https://example.invalid/api/probe", { method: "POST" });

    expect(payload.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = requestInit.headers as Headers;
    expect(headers.get("X-Vibelution-Control-Token")).toBeNull();
  });

  it("attaches a control token from the target local API origin", async () => {
    vi.stubGlobal("window", {
      location: {
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "launcher-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ accepted: true }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ accepted: boolean }>("http://127.0.0.1:8765/api/launcher/restart", {
      method: "POST",
    });

    expect(payload.accepted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8765/api/control-token");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    const headers = requestInit.headers as Headers;
    expect(requestInit.credentials).toBe("include");
    expect(headers.get("X-Vibelution-Control-Token")).toBe("launcher-token");
  });

  it("reports same-origin API http failures", async () => {
    const reports: unknown[] = [];
    setFetchJsonFailureReporter((report) => reports.push(report));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "t" }),
        text: async () => "",
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ detail: "run is active" }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/evolution/runs")).rejects.toThrow("run is active");

    expect(reports).toEqual([
      {
        endpoint: "/api/evolution/runs",
        method: "GET",
        status: 409,
        message: "run is active",
        failureKind: "http",
      },
    ]);
  });

  it("surfaces the problem code verbatim when a structured detail has no readable fields", async () => {
    const reports: unknown[] = [];
    setFetchJsonFailureReporter((report) => reports.push(report));
    const structuredDetail = {
      code: "active_work_restart_blocked",
      activeWorkRuns: [{ kind: "chat_turn", runId: "turn-live" }],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ detail: structuredDetail }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/runtime/restart", { method: "POST" })).rejects.toThrow(
      "active_work_restart_blocked",
    );

    expect(reports).toEqual([
      {
        endpoint: "/api/runtime/restart",
        method: "POST",
        status: 409,
        message: "active_work_restart_blocked",
        failureKind: "http",
      },
    ]);
  });

  it("falls back to compact truncated JSON when the structured detail is unreadable", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 422,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          detail: {
            opaque: "x".repeat(400),
          },
        }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    try {
      await fetchJson("/api/probe", { method: "POST" });
      expect.unreachable("expected the request to fail");
    } catch (error) {
      expect((error as Error).message.startsWith('{"detail":{"opaque":"xxx')).toBe(true);
      expect((error as Error).message.endsWith("…")).toBe(true);
      expect((error as Error).message.length).toBeLessThanOrEqual(241);
    }
  });

  it("reads the server message out of a structured detail instead of showing JSON", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ detail: { code: "catalog_question_unknown", message: "unknown question" } }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    const result = fetchJson("/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/state-v2");
    await expect(result).rejects.toMatchObject({
      status: 404,
      code: "catalog_question_unknown",
    });
    await expect(result).rejects.toThrow("unknown question");
    await expect(result.catch((error: unknown) => {
      expect(isFetchJsonHttpError(error)).toBe(true);
      expect((error as { details?: unknown }).details).toEqual({
        detail: { code: "catalog_question_unknown", message: "unknown question" },
      });
    })).resolves.toBeUndefined();
  });

  it("maps command_forbidden to plain language when the detail carries no message", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 403,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ detail: { code: "command_forbidden", message: "" } }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/teams/team-1/workflow-orchestration/hypothesis-first/commands", {
      method: "POST",
    })).rejects.toThrow("当前身份无权执行此操作");
  });

  it("appends readiness blockers as readable entries after the detail message", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 412,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          detail: {
            code: "node_not_ready",
            message: "节点尚未就绪",
            blockers: [
              "知识包缺少证据主张",
              { code: "run_not_started", message: "正式运行尚未启动" },
            ],
          },
        }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/teams/team-1/workflow-orchestration/hypothesis-first/commands", {
      method: "POST",
    })).rejects.toThrow("节点尚未就绪（阻塞项：知识包缺少证据主张；run_not_started：正式运行尚未启动）");
  });

  it("refreshes a rotated control token and retries the guarded request once", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "expired-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 403,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ detail: "Missing or invalid web control token" }),
        text: async () => "",
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "fresh-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ ok: boolean }>("/api/runtime/shutdown", { method: "POST" });

    expect(payload.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    const retriedRequest = fetchMock.mock.calls[3][1] as RequestInit;
    expect((retriedRequest.headers as Headers).get("X-Vibelution-Control-Token")).toBe("fresh-token");
  });

  it("does not refresh or retry a source-policy 403", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "current-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 403,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ detail: "Untrusted web control origin" }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/runtime/shutdown", { method: "POST" })).rejects.toThrow(
      "Untrusted web control origin",
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stops after one rotated-token retry", async () => {
    const rejected = () => ({
      ok: false,
      status: 403,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ detail: "Missing or invalid web control token" }),
      text: async () => "",
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "expired-token",
        }),
      })
      .mockResolvedValueOnce(rejected())
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "also-expired-token",
        }),
      })
      .mockResolvedValueOnce(rejected());
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/runtime/shutdown", { method: "POST" })).rejects.toThrow(
      "Missing or invalid web control token",
    );

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("reports same-origin API network failures", async () => {
    const reports: unknown[] = [];
    setFetchJsonFailureReporter((report) => reports.push(report));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "t" }),
      })
      .mockRejectedValueOnce(new Error("connection lost"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/runtime/summary")).rejects.toThrow("connection lost");

    expect(reports).toEqual([
      {
        endpoint: "/api/runtime/summary",
        method: "GET",
        status: null,
        message: "connection lost",
        failureKind: "network",
      },
    ]);
  });

  it("does not report aborted requests as API failures", async () => {
    const reports: unknown[] = [];
    setFetchJsonFailureReporter((report) => reports.push(report));
    const abortError = new DOMException("signal is aborted without reason", "AbortError");
    const fetchMock = vi.fn().mockRejectedValueOnce(abortError);
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/sessions/session-live?messageLimit=40", { signal: new AbortController().signal }))
      .rejects.toThrow(abortError);

    expect(reports).toEqual([]);
  });

  it("classifies abort errors by name and message", () => {
    expect(isFetchAbortError(new DOMException("signal is aborted without reason", "AbortError"))).toBe(true);
    expect(isFetchAbortError(new Error("The operation was aborted."))).toBe(true);
    expect(isFetchAbortError(new Error("connection lost"))).toBe(false);
    expect(isFetchAbortError(null)).toBe(false);
  });

  it("does not report external API failures", async () => {
    const reports: unknown[] = [];
    setFetchJsonFailureReporter((report) => reports.push(report));
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      headers: new Headers(),
      text: async () => "external failed",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("https://example.invalid/api/probe")).rejects.toThrow("external failed");

    expect(reports).toEqual([]);
  });

  it("adds the active client operation id header to mutating requests", async () => {
    pushClientOperationContext("session_delete-probe-1");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await fetchJson<{ ok: boolean }>("/api/sessions/session-a", { method: "DELETE" });

    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    const headers = requestInit.headers as Headers;
    expect(headers.get("X-Vibelution-Client-Operation-Id")).toBe("session_delete-probe-1");
  });
});
