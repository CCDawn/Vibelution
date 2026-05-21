import { afterEach, describe, expect, it, vi } from "vitest";

import { getControlToken, resetControlTokenForTests } from "../api/client";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "./browserTelemetry";

describe("browser telemetry", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetControlTokenForTests();
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

  it("summarizes page content without copying main text into telemetry fields", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
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
      pathname: "/chat",
      activeNavHref: "/chat",
      activeNavText: "对话",
      heading: "当前会话",
      mainTextLength: expect.any(Number),
    });
    expect(snapshot).not.toHaveProperty("mainTextPreview");
    expect(JSON.stringify(snapshot)).not.toContain("用户对话正文");
  });
});
