import { afterEach, describe, expect, it, vi } from "vitest";

import { getControlToken, resetControlTokenForTests, seedControlTokenForTests } from "../api/client";
import {
  collectBrowserMemorySnapshot,
  collectBrowserPageSnapshot,
  peekBrowserTelemetryDeliveryBufferForTests,
  postBrowserTelemetry,
  resetBrowserTelemetryDeliveryBufferForTests,
  shouldCaptureConsoleTelemetry,
} from "./browserTelemetry";
import { resetPageInstanceIdForTests } from "./pageInstance";

function deferredResponse() {
  let resolve!: (response: { ok: boolean; status: number }) => void;
  const promise = new Promise<{ ok: boolean; status: number }>((done) => { resolve = done; });
  return { promise, resolve };
}

function postTestEvent(eventCode: string, level: "info" | "warning" | "error" = "info") {
  postBrowserTelemetry({ phase: "test", eventCode, message: eventCode, level });
}

function postExitTestEvent(eventCode: string) {
  postBrowserTelemetry({ phase: "page", eventCode, message: eventCode }, { preferBeacon: true });
}

describe("browser telemetry", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetControlTokenForTests();
    resetPageInstanceIdForTests();
    resetBrowserTelemetryDeliveryBufferForTests();
  });

  it("keeps only one telemetry request in flight during a burst", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const responses = Array.from({ length: 5 }, deferredResponse);
    let inFlight = 0;
    let maximumInFlight = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      maximumInFlight = Math.max(maximumInFlight, ++inFlight);
      return responses[fetchMock.mock.calls.length - 1].promise.finally(() => { inFlight -= 1; });
    });
    vi.stubGlobal("fetch", fetchMock);

    for (let index = 0; index < responses.length; index += 1) {
      postTestEvent(`burst.${index}`);
    }
    for (let index = 0; index < responses.length; index += 1) {
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(index + 1));
      expect(inFlight).toBe(1);
      responses[index].resolve({ ok: true, status: 202 });
    }
    await vi.waitFor(() => expect(inFlight).toBe(0));
    expect(maximumInFlight).toBe(1);
  });

  it("immediately sends two exit events alongside a normal request and queues further exit events", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const now = vi.fn().mockReturnValue(12);
    vi.stubGlobal("performance", { now });
    const responses = Array.from({ length: 5 }, deferredResponse);
    let inFlight = 0;
    let maximumInFlight = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      maximumInFlight = Math.max(maximumInFlight, ++inFlight);
      return responses[fetchMock.mock.calls.length - 1].promise.finally(() => { inFlight -= 1; });
    });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("normal");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    postExitTestEvent("refresh_requested");
    postExitTestEvent("pagehide");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    postExitTestEvent("queued-exit");
    now.mockReturnValue(900);
    for (let index = 0; index < 20; index += 1) { await Promise.resolve(); }
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(inFlight).toBe(3);
    responses[0].resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(inFlight).toBe(3);
    expect(fetchMock.mock.calls.map((call) => JSON.parse(String(call[1].body)).eventCode)).toEqual([
      "normal", "refresh_requested", "pagehide", "queued-exit",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[3][1].body)).fields.clientMonotonicMs).toBe(12);
    expect(fetchMock.mock.calls.every((call) => call[1].keepalive === true)).toBe(true);
    responses[1].resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(inFlight).toBe(2));
    postExitTestEvent("next-pagehide");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    expect(inFlight).toBe(3);
    for (const response of responses.slice(1)) { response.resolve({ ok: true, status: 202 }); }
    await vi.waitFor(() => expect(inFlight).toBe(0));
    expect(maximumInFlight).toBe(3);
  });

  it("does not replay failures through the immediate exit channel", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const normal = deferredResponse();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockImplementationOnce(() => normal.promise)
      .mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("failed");
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1));
    postTestEvent("normal");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    postExitTestEvent("pagehide");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    for (let index = 0; index < 20; index += 1) { await Promise.resolve(); }
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1);
    normal.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0));
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it.each(["network", "HTTP", "403"])("handles immediate exit %s failure without recursive delivery", async (failure) => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const normal = deferredResponse();
    const fetchMock = vi.fn().mockImplementationOnce(() => normal.promise);
    if (failure === "network") {
      fetchMock.mockRejectedValueOnce(new Error("network down"));
    } else {
      fetchMock.mockResolvedValueOnce({ ok: false, status: failure === "403" ? 403 : 500 });
    }
    fetchMock.mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("normal");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    postExitTestEvent("pagehide");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    for (let index = 0; index < 20; index += 1) { await Promise.resolve(); }
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(failure === "403" ? 0 : 1);
    expect(warn).toHaveBeenCalledTimes(failure === "403" ? 0 : 1);
    if (failure === "403") {
      fetchMock.mockResolvedValueOnce({
        ok: true, json: async () => ({ header: "X-Control", controlToken: "fresh" }),
      });
      expect((await getControlToken()).token).toBe("fresh");
    }
    normal.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0));
    for (let index = 0; index < 20; index += 1) { await Promise.resolve(); }
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not remove the next failure when immediate failures evict an in-flight retry", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const replay = deferredResponse();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: true, status: 202 })
      .mockImplementationOnce(() => replay.promise)
      .mockResolvedValue({ ok: false, status: 500 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("old-failure");
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1));
    postTestEvent("success");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    for (let index = 0; index < 20; index += 1) {
      postExitTestEvent(`exit.${index}`);
      await vi.waitFor(() => expect(warn).toHaveBeenCalledTimes(index + 2));
    }
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(20);
    expect(peekBrowserTelemetryDeliveryBufferForTests()[0]).toContain("exit.0");
    replay.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(24));
    expect(JSON.parse(String(fetchMock.mock.calls[23][1].body)).eventCode).toBe("exit.0");
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(20);
  });

  it("prioritizes pending errors and warnings while retaining FIFO within each level", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const first = deferredResponse();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("in-flight");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    postTestEvent("info.1");
    postTestEvent("warning", "warning");
    postTestEvent("error.1", "error");
    postTestEvent("info.2");
    postTestEvent("error.2", "error");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    first.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));

    expect(fetchMock.mock.calls.map((call) => JSON.parse(String(call[1].body)).eventCode)).toEqual([
      "in-flight", "error.1", "error.2", "warning", "info.1", "info.2",
    ]);
  });

  it("bounds pending deliveries at 100 and evicts the oldest info before warnings or errors", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const first = deferredResponse();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("in-flight");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    postTestEvent("warning", "warning");
    for (let index = 0; index < 99; index += 1) {
      postTestEvent(`info.${index}`);
    }
    postTestEvent("error", "error");
    first.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(101));
    const posted = fetchMock.mock.calls.map((call) => JSON.parse(String(call[1].body)).eventCode);
    expect(posted.slice(0, 4)).toEqual(["in-flight", "error", "warning", "info.1"]);
    expect(posted).not.toContain("info.0");
    expect(posted.at(-1)).toBe("info.98");
  });

  it("discards an incoming info event when the pending queue contains only errors", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const first = deferredResponse();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("in-flight");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    for (let index = 0; index < 100; index += 1) {
      postTestEvent(`error.${index}`, "error");
    }
    postTestEvent("discarded-info");
    first.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(101));
    const posted = fetchMock.mock.calls.map((call) => JSON.parse(String(call[1].body)).eventCode);
    expect(posted[1]).toBe("error.0");
    expect(posted.at(-1)).toBe("error.99");
    expect(posted).not.toContain("discarded-info");
  });

  it("preserves occurrence fields across queue delay and failure replay", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const now = vi.fn().mockReturnValue(12);
    vi.stubGlobal("performance", { now });
    const occurredAt = vi.spyOn(Date.prototype, "toISOString").mockReturnValue("2026-10-21T01:00:00.000Z");
    const first = deferredResponse();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("in-flight");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    postTestEvent("delayed");
    now.mockReturnValue(900);
    occurredAt.mockReturnValue("2026-10-21T02:00:00.000Z");
    first.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1));
    postTestEvent("recovered");
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0));

    const originalBody = String(fetchMock.mock.calls[1][1].body);
    expect(JSON.parse(originalBody).fields).toMatchObject({
      clientOccurredAt: "2026-10-21T01:00:00.000Z", clientMonotonicMs: 12,
    });
    expect(String(fetchMock.mock.calls[3][1].body)).toBe(originalBody);
  });

  it("shares the in-flight slot with FIFO failure replays before draining pending events", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const replay = deferredResponse();
    let inFlight = 0;
    let maximumInFlight = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      const call = fetchMock.mock.calls.length;
      maximumInFlight = Math.max(maximumInFlight, ++inFlight);
      const response = call <= 2
        ? Promise.resolve({ ok: false, status: 500 })
        : call === 4 ? replay.promise : Promise.resolve({ ok: true, status: 202 });
      return response.finally(() => { inFlight -= 1; });
    });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("failed.1");
    postTestEvent("failed.2");
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(2));
    postTestEvent("success");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    postTestEvent("pending");
    for (let index = 0; index < 20; index += 1) { await Promise.resolve(); }
    expect(fetchMock).toHaveBeenCalledTimes(4);
    replay.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
    await vi.waitFor(() => expect(inFlight).toBe(0));
    expect(maximumInFlight).toBe(1);
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0);
    expect(fetchMock.mock.calls.map((call) => JSON.parse(String(call[1].body)).eventCode)).toEqual([
      "failed.1", "failed.2", "success", "failed.1", "failed.2", "pending",
    ]);
  });

  it("sends a newly queued error immediately after the current retry completes", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const replay = deferredResponse();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: true, status: 202 })
      .mockImplementationOnce(() => replay.promise)
      .mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("failed.1");
    postTestEvent("failed.2");
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(2));
    postTestEvent("success");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    postTestEvent("queued-info");
    postTestEvent("new-error", "error");
    expect(fetchMock).toHaveBeenCalledTimes(4);
    replay.resolve({ ok: true, status: 202 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(7));

    expect(fetchMock.mock.calls.map((call) => JSON.parse(String(call[1].body)).eventCode)).toEqual([
      "failed.1", "failed.2", "success", "failed.1", "new-error", "failed.2", "queued-info",
    ]);
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0);
  });

  it("refreshes the control token before sending a queued event after a 403", async () => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests("expired");
    const first = deferredResponse();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({
        ok: true, json: async () => ({ header: "X-Control", controlToken: "fresh" }),
      })
      .mockResolvedValueOnce({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("forbidden");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    postTestEvent("queued");
    first.resolve({ ok: false, status: 403 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toBe("/api/control-token");
    expect(fetchMock.mock.calls[2][1].headers["X-Control"]).toBe("fresh");
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0);
  });

  it.each(["network", "HTTP", "403"])("stops a failed %s replay until another successful new event", async (failure) => {
    vi.stubGlobal("window", {});
    seedControlTokenForTests();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: true, status: 202 });
    if (failure === "network") {
      fetchMock.mockRejectedValueOnce(new Error("still down"));
    } else {
      fetchMock.mockResolvedValueOnce({ ok: false, status: failure === "403" ? 403 : 502 });
    }
    fetchMock.mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);
    postTestEvent("failed");
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1));
    postTestEvent("success");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    // Settle continuations so an accidental self-retry cannot hide behind the assertion.
    for (let index = 0; index < 20; index += 1) { await Promise.resolve(); }
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1);
    expect(warn).toHaveBeenCalledTimes(failure === "403" ? 1 : 2);
    if (failure === "403") {
      fetchMock.mockResolvedValueOnce({
        ok: true, json: async () => ({ header: "X-Control", controlToken: "fresh" }),
      });
      expect((await getControlToken()).token).toBe("fresh");
    }
    postTestEvent("next-success");
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0));
    const posted = fetchMock.mock.calls.filter((call) => call[1]?.body)
      .map((call) => JSON.parse(String(call[1].body)).eventCode);
    expect(posted).toEqual(["failed", "success", "failed", "next-success", "failed"]);
  });

  it("clears cached control token after telemetry receives 403", async () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:8000" } });
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
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "fresh-token",
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    postBrowserTelemetry({
      phase: "page",
      eventCode: "browser.page.snapshot",
      message: "snapshot",
    });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const control = await getControlToken();

    expect(control.token).toBe("fresh-token");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("stamps telemetry with trusted browser occurrence fields", async () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:8000" } });
    vi.stubGlobal("performance", { now: () => 4321.5 });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "telemetry-token",
        }),
      })
      .mockResolvedValueOnce({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);

    postBrowserTelemetry({
      phase: "chat_submit",
      eventCode: "browser.chat_submit.request_started",
      message: "submit started",
      fields: {
        sessionId: "session-demo",
        clientOccurredAt: "spoofed",
        clientMonotonicMs: -1,
      },
    });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const request = fetchMock.mock.calls[1]?.[1] as RequestInit;
    const payload = JSON.parse(String(request.body));
    expect(payload.fields).toMatchObject({
      sessionId: "session-demo",
      clientOccurredAt: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
      clientMonotonicMs: 4321.5,
    });
    expect(payload.fields.clientOccurredAt).not.toBe("spoofed");
  });

  it("summarizes page content without reading main text into telemetry fields", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
        hostname: "127.0.0.1",
        port: "8000",
        pathname: "/chat",
        search: "",
        hash: "",
      },
    });
    const queriedSelectors: string[] = [];
    vi.stubGlobal("document", {
      title: "Vibelution 工作台",
      readyState: "complete",
      visibilityState: "visible",
      querySelector: (selector: string) => {
        queriedSelectors.push(selector);
        if (selector === "[data-browser-role], [data-shell]") {
          return {
            dataset: {
              shell: "workbench",
              browserRole: "workbench",
            },
          };
        }
        if (selector === "header nav a[aria-current='page']") {
          return {
            getAttribute: (name: string) => (name === "href" ? "/chat" : ""),
            textContent: "对话",
          };
        }
        if (selector === "h1") {
          return { textContent: "当前会话" };
        }
        if (selector === "main") {
          return { textContent: "用户对话正文不应该进入浏览器遥测字段。" };
        }
        return null;
      },
    });

    const snapshot = collectBrowserPageSnapshot();

    expect(snapshot).toMatchObject({
      pageInstanceId: expect.stringMatching(/^page-/),
      pathname: "/chat",
      telemetrySurface: "managed_workbench",
      browserRole: "workbench",
      port: "8000",
      activeNavHref: "/chat",
      activeNavText: "对话",
      heading: "当前会话",
    });
    expect(snapshot).not.toHaveProperty("mainTextLength");
    expect(snapshot).not.toHaveProperty("mainTextPreview");
    expect(queriedSelectors).not.toContain("main");
    expect(JSON.stringify(snapshot)).not.toContain("用户对话正文");
  });

  it("marks Vite dev pages so backend diagnostics can ignore mixed-origin samples", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:5173/chat",
        origin: "http://127.0.0.1:5173",
        hostname: "127.0.0.1",
        port: "5173",
        pathname: "/chat",
        search: "",
        hash: "",
      },
    });
    vi.stubGlobal("document", {
      title: "Vibelution 工作台",
      readyState: "complete",
      visibilityState: "visible",
      querySelector: () => null,
    });

    expect(collectBrowserPageSnapshot()).toMatchObject({
      href: "http://127.0.0.1:5173/chat",
      telemetrySurface: "vite_dev",
      port: "5173",
    });
  });

  it("marks Launcher control pages with a separate browser role", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/launcher",
        origin: "http://127.0.0.1:8000",
        hostname: "127.0.0.1",
        port: "8000",
        pathname: "/launcher",
        search: "",
        hash: "",
      },
    });
    vi.stubGlobal("document", {
      title: "Launcher",
      readyState: "complete",
      visibilityState: "visible",
      querySelector: (selector: string) => {
        if (selector === "[data-browser-role], [data-shell]") {
          return {
            dataset: {
              shell: "launcher",
              browserRole: "launcher_control_surface",
            },
          };
        }
        return null;
      },
    });

    expect(collectBrowserPageSnapshot()).toMatchObject({
      href: "http://127.0.0.1:8000/launcher",
      telemetrySurface: "managed_launcher",
      browserRole: "launcher_control_surface",
      pathname: "/launcher",
    });
  });

  it("summarizes JS heap memory as bounded numeric telemetry fields", () => {
    vi.stubGlobal("performance", {
      memory: {
        usedJSHeapSize: 15 * 1024 * 1024,
        totalJSHeapSize: 24 * 1024 * 1024,
        jsHeapSizeLimit: 128 * 1024 * 1024,
      },
    });

    expect(collectBrowserMemorySnapshot()).toMatchObject({
      available: true,
      usedJSHeapMB: 15,
      totalJSHeapMB: 24,
      jsHeapLimitMB: 128,
      usedJSHeapBytes: 15 * 1024 * 1024,
    });
  });

  it("marks browser memory unavailable when the runtime does not expose heap metrics", () => {
    vi.stubGlobal("performance", {});

    expect(collectBrowserMemorySnapshot()).toEqual({
      available: false,
    });
  });

  it("warns when telemetry delivery fails without posting another event", async () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:8000" } });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "telemetry-token",
        }),
      })
      .mockRejectedValueOnce(new Error("network down"));
    vi.stubGlobal("fetch", fetchMock);

    postBrowserTelemetry({
      phase: "error",
      eventCode: "browser.route.error",
      message: "workbench route render failed",
    });
    await vi.waitFor(() => expect(warn).toHaveBeenCalled());

    expect(warn).toHaveBeenCalledWith(
      "browser telemetry delivery failed",
      expect.stringContaining("network down"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1);
    expect(peekBrowserTelemetryDeliveryBufferForTests()[0]).toContain("browser.route.error");
  });

  it("excludes telemetry delivery failures from console telemetry capture", () => {
    expect(shouldCaptureConsoleTelemetry([
      "browser telemetry delivery failed",
      "HTTP 502",
    ])).toBe(false);
    expect(shouldCaptureConsoleTelemetry([
      "ordinary application warning",
    ])).toBe(true);
  });

  it("buffers HTTP delivery failures without posting another telemetry event", async () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:8000" } });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "telemetry-token",
        }),
      })
      .mockResolvedValueOnce({ ok: false, status: 500 });
    vi.stubGlobal("fetch", fetchMock);

    postBrowserTelemetry({
      phase: "error",
      eventCode: "browser.preview.error",
      message: "preview render failed",
    });
    await vi.waitFor(() => expect(warn).toHaveBeenCalled());

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1);
    expect(peekBrowserTelemetryDeliveryBufferForTests()[0]).toContain("browser.preview.error");
  });

  it("does not buffer 403 telemetry responses", async () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:8000" } });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "expired-token",
        }),
      })
      .mockResolvedValueOnce({ ok: false, status: 403 });
    vi.stubGlobal("fetch", fetchMock);

    postBrowserTelemetry({
      phase: "page",
      eventCode: "browser.page.snapshot",
      message: "snapshot",
    });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(warn).not.toHaveBeenCalled();
    expect(peekBrowserTelemetryDeliveryBufferForTests()).toEqual([]);
  });

  it("flushes buffered deliveries after the next successful post", async () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:8000" } });
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "telemetry-token",
        }),
      })
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ ok: true, status: 202 })
      .mockResolvedValueOnce({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);

    postBrowserTelemetry({
      phase: "error",
      eventCode: "browser.route.error",
      message: "workbench route render failed",
    });
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(1));

    postBrowserTelemetry({
      phase: "page",
      eventCode: "browser.page.snapshot",
      message: "snapshot",
    });
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(0));

    const postedBodies = fetchMock.mock.calls
      .slice(1)
      .map((call) => String((call[1] as RequestInit | undefined)?.body ?? ""));
    expect(postedBodies.some((body) => body.includes("browser.route.error"))).toBe(true);
    expect(postedBodies.some((body) => body.includes("browser.page.snapshot"))).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("drops the oldest buffered delivery when the ring is full", async () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:8000" } });
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "telemetry-token",
        }),
      });
    for (let index = 0; index < 21; index += 1) {
      fetchMock.mockRejectedValueOnce(new Error("network down"));
    }
    vi.stubGlobal("fetch", fetchMock);

    for (let index = 0; index < 21; index += 1) {
      postBrowserTelemetry({
        phase: "error",
        eventCode: `browser.overflow.${index}`,
        message: "overflow",
      });
    }
    await vi.waitFor(() => expect(peekBrowserTelemetryDeliveryBufferForTests()).toHaveLength(20));

    const buffered = peekBrowserTelemetryDeliveryBufferForTests();
    expect(buffered[0]).toContain("browser.overflow.1");
    expect(buffered[19]).toContain("browser.overflow.20");
    expect(buffered.some((body) => body.includes("browser.overflow.0"))).toBe(false);
  });
});
