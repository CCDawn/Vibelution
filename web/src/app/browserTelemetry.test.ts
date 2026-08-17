import { afterEach, describe, expect, it, vi } from "vitest";

import { getControlToken, resetControlTokenForTests } from "../api/client";
import {
  collectBrowserMemorySnapshot,
  collectBrowserPageSnapshot,
  peekBrowserTelemetryDeliveryBufferForTests,
  postBrowserTelemetry,
  resetBrowserTelemetryDeliveryBufferForTests,
} from "./browserTelemetry";
import { resetPageInstanceIdForTests } from "./pageInstance";

describe("browser telemetry", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetControlTokenForTests();
    resetPageInstanceIdForTests();
    resetBrowserTelemetryDeliveryBufferForTests();
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

  it("summarizes page content without copying main text into telemetry fields", () => {
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
    vi.stubGlobal("document", {
      title: "Vibelution 工作台",
      readyState: "complete",
      visibilityState: "visible",
      querySelector: (selector: string) => {
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
      mainTextLength: expect.any(Number),
    });
    expect(snapshot).not.toHaveProperty("mainTextPreview");
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
