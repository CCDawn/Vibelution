import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VErrorSummary, summarizeErrorText } from "./VErrorSummary";

describe("VErrorSummary", () => {
  it("summarizes long error text into one line plus full details", () => {
    const long = "A".repeat(120);
    const result = summarizeErrorText(long, 40);
    expect(result.summary.endsWith("…")).toBe(true);
    expect(result.summary.length).toBeLessThanOrEqual(41);
    expect(result.details).toBe(long);
  });

  it("keeps short errors as summary-only", () => {
    expect(summarizeErrorText("upstream 502")).toEqual({
      summary: "upstream 502",
      details: null,
    });
  });

  it("renders a compact alert without a details disclosure when no details exist", () => {
    const markup = renderToStaticMarkup(
      <VErrorSummary tone="error" label="请求错误" summary="模型调用失败" />,
    );
    expect(markup).toContain('data-vui="error-summary"');
    expect(markup).toContain('data-tone="error"');
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("请求错误");
    expect(markup).toContain("模型调用失败");
    expect(markup).not.toContain("<details");
    expect(markup).toContain("[overflow-wrap:anywhere]");
  });

  it("renders expandable details for long diagnostics", () => {
    const markup = renderToStaticMarkup(
      <VErrorSummary
        tone="error"
        label="Runtime"
        summary="provider timeout…"
        details={"full stack\nline 2"}
        openLabel="详情"
        closeLabel="收起"
      />,
    );
    expect(markup).toContain("<details");
    expect(markup).toContain('data-slot="error-summary-details"');
    expect(markup).toContain("full stack");
    expect(markup).toContain("详情");
    expect(markup).toContain("provider timeout…");
  });
});
