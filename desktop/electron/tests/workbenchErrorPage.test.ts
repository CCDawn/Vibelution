import { describe, expect, it } from "vitest";
import {
  isWorkbenchErrorPageUrl,
  renderWorkbenchErrorPage,
  workbenchErrorPageDataUrl
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
