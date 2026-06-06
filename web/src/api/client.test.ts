import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchJson, getControlToken, resetControlTokenForTests, setFetchJsonFailureReporter } from "./client";

describe("fetchJson control token", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetControlTokenForTests();
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

  it("does not request a control token for read-only requests", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ status: string }>("/api/health");

    expect(payload.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
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
    const fetchMock = vi.fn().mockResolvedValueOnce({
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

  it("preserves structured JSON error details for callers", async () => {
    const reports: unknown[] = [];
    setFetchJsonFailureReporter((report) => reports.push(report));
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
        json: async () => ({
          detail: {
            code: "active_work_restart_blocked",
            activeWorkRuns: [{ kind: "chat_turn", runId: "turn-live" }],
          },
        }),
        text: async () => "",
      });
    vi.stubGlobal("fetch", fetchMock);

    const expectedMessage = JSON.stringify({
      detail: {
        code: "active_work_restart_blocked",
        activeWorkRuns: [{ kind: "chat_turn", runId: "turn-live" }],
      },
    });
    await expect(fetchJson("/api/runtime/restart", { method: "POST" })).rejects.toThrow(expectedMessage);

    expect(reports).toEqual([
      {
        endpoint: "/api/runtime/restart",
        method: "POST",
        status: 409,
        message: expectedMessage,
        failureKind: "http",
      },
    ]);
  });

  it("clears cached control token after a guarded write returns 403", async () => {
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
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/api/runtime/shutdown", { method: "POST" })).rejects.toThrow(
      "Missing or invalid web control token",
    );
    const control = await getControlToken();

    expect(control.token).toBe("fresh-token");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("reports same-origin API network failures", async () => {
    const reports: unknown[] = [];
    setFetchJsonFailureReporter((report) => reports.push(report));
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error("connection lost"));
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
});
