// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { buildSafeHtmlPreview } from "./safeHtmlPreview";

describe("safe static HTML preview", () => {
  it("removes executable, network and navigation surfaces while keeping the drawing", () => {
    const html = buildSafeHtmlPreview(`<meta http-equiv="refresh" content="0;url=https://bad.test"><base href="https://bad.test"><script>parent.hacked=true</script><style>h1{color:red}</style><h1 onclick="alert(1)">Report</h1><a href="https://bad.test" ping="https://bad.test">Link</a><iframe srcdoc="bad"></iframe><img src="https://bad.test/a" srcset="https://bad.test/b 2x"><form action="https://bad.test"></form><svg><circle r="5"/><a xlink:href="https://bad.test"><text>link</text></a></svg>`);
    const doc = new DOMParser().parseFromString(html, "text/html");
    expect(doc.querySelectorAll("script,base,iframe,form[action],[onclick],[href],[srcset],[ping]")).toHaveLength(0);
    expect(doc.querySelector("svg circle")).not.toBeNull();
    expect(doc.querySelector("h1")?.textContent).toBe("Report");
    expect(doc.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute("content")).toContain("script-src 'none'");
    expect(html).not.toContain("https://bad.test");
  });
  it("keeps inline CSS and embedded raster images but blocks SVG data documents", () => {
    const doc = new DOMParser().parseFromString(buildSafeHtmlPreview('<style>p{color:blue}</style><img src="data:image/png;base64,YQ=="><img src="data:image/svg+xml;base64,YQ==">'), "text/html");
    expect(doc.querySelector("style")?.textContent).toBe("p{color:blue}");
    expect(doc.querySelectorAll("img[src]")).toHaveLength(1);
  });
});
