import { describe, expect, it } from "vitest";
import {
  isWorkbenchErrorPageUrl,
  isWorkbenchStatusPageUrl,
  isWorkbenchWaitingPageUrl,
  renderWorkbenchErrorPage,
  renderWorkbenchWaitingPage,
  workbenchErrorPageDataUrl,
  workbenchWaitingPageDataUrl
} from "../src/windows/workbenchErrorPage.js";

function decodeDataUrl(url: string): string {
  const comma = url.indexOf(",");
  return decodeURIComponent(url.slice(comma + 1));
}

describe("workbench error page", () => {
  it("renders a bilingual status with the origin, guidance, and original cause", () => {
    const html = renderWorkbenchErrorPage({
      origin: "http://127.0.0.1:8000",
      detail: "Workbench navigation failed for http://127.0.0.1:8000: net::ERR_CONNECTION_REFUSED"
    });

    expect(html).toContain("工作台暂时无法连接");
    expect(html).toContain("打开窗口");
    expect(html).toContain("The Workbench backend is not ready");
    expect(html).toContain("Open Window");
    expect(html).toContain("127.0.0.1:8000");
    expect(html).toContain("ERR_CONNECTION_REFUSED");
  });

  it("escapes hostile detail text before it reaches the document", () => {
    const html = renderWorkbenchErrorPage({
      origin: "http://127.0.0.1:8000",
      detail: '<script>alert("xss")</script>'
    });

    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("round-trips through the data URL and is recognized as an error page", () => {
    const url = workbenchErrorPageDataUrl({
      origin: "http://127.0.0.1:8000",
      detail: "net::ERR_CONNECTION_REFUSED"
    });

    expect(url.startsWith("data:text/html")).toBe(true);
    expect(isWorkbenchErrorPageUrl(url)).toBe(true);
    expect(isWorkbenchErrorPageUrl("http://127.0.0.1:8000/")).toBe(false);
    expect(isWorkbenchErrorPageUrl("data:text/html;charset=utf-8,%3Cp%3Ehello%3C%2Fp%3E")).toBe(false);
  });
});

describe("workbench waiting page", () => {
  it("renders a bilingual waiting status with the origin and the auto-reload promise", () => {
    const html = renderWorkbenchWaitingPage({ origin: "http://127.0.0.1:8000" });

    expect(html).toContain("正在等待工作台后端启动");
    expect(html).toContain("自动重新加载");
    expect(html).toContain("Waiting for the Workbench backend");
    expect(html).toContain("reloads this window automatically");
    expect(html).toContain("127.0.0.1:8000");
    // It is the interim state: no terminal "cannot connect" wording and no
    // "retry by hand" instruction that would contradict the auto recovery.
    expect(html).not.toContain("工作台暂时无法连接");
    expect(html).not.toContain("错误详情");
  });

  it("carries a live elapsed-seconds counter driven by a self-contained inline script", () => {
    const html = renderWorkbenchWaitingPage({ origin: "http://127.0.0.1:8000" });

    expect(html).toContain("已等待");
    expect(html).toContain("Waited");
    expect(html.match(/data-wait-seconds/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain("<script>");
    expect(html).toContain("setInterval(tick,1000)");
    expect(html).toContain("Date.now()");
    // Nothing external: the data: document must stay self-sufficient.
    expect(html).not.toMatch(/<script[^>]+src=/);
    expect(html).not.toMatch(/<link[^>]+href=/);
  });

  it("escapes the origin so no caller-supplied text can reach the script or markup", () => {
    const html = renderWorkbenchWaitingPage({ origin: '</code><script>alert("x")</script>' });

    expect(html).not.toContain('<script>alert("x")</script>');
    expect(html).toContain("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;");
    expect(html.match(/<script>/g)?.length).toBe(1);
  });

  it("round-trips through the data URL and is told apart from the error page by its marker", () => {
    const waitingUrl = workbenchWaitingPageDataUrl({ origin: "http://127.0.0.1:8000" });
    const errorUrl = workbenchErrorPageDataUrl({ origin: "http://127.0.0.1:8000", detail: "down" });

    expect(waitingUrl.startsWith("data:text/html")).toBe(true);
    expect(decodeDataUrl(waitingUrl)).toContain("正在等待工作台后端启动");

    expect(isWorkbenchWaitingPageUrl(waitingUrl)).toBe(true);
    expect(isWorkbenchErrorPageUrl(waitingUrl)).toBe(false);
    expect(isWorkbenchWaitingPageUrl(errorUrl)).toBe(false);
    expect(isWorkbenchErrorPageUrl(errorUrl)).toBe(true);

    expect(isWorkbenchStatusPageUrl(waitingUrl)).toBe(true);
    expect(isWorkbenchStatusPageUrl(errorUrl)).toBe(true);
    expect(isWorkbenchStatusPageUrl("http://127.0.0.1:8000/")).toBe(false);
    expect(isWorkbenchStatusPageUrl("data:text/html;charset=utf-8,%3Cp%3Ehello%3C%2Fp%3E")).toBe(false);
    expect(isWorkbenchWaitingPageUrl("")).toBe(false);
  });
});
