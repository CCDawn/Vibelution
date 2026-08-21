import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ResearchCriticalPathPanel } from "./ResearchCriticalPathPanel";

function insights(overrides: Record<string, unknown> = {}) {
  return {
    loading: false,
    error: null,
    handoffs: null,
    ...overrides,
  } as never;
}

describe("ResearchCriticalPathPanel", () => {
  it("keeps loading insights out of the empty path state", () => {
    const html = renderToStaticMarkup(
      <ResearchCriticalPathPanel projection={null} insights={insights({ loading: true })} />,
    );

    expect(html).toContain("正在加载关键路径");
    expect(html).not.toContain("关键路径尚未形成");
  });

  it("surfaces a path loading error instead of claiming no path", () => {
    const html = renderToStaticMarkup(
      <ResearchCriticalPathPanel projection={null} insights={insights({ error: "关键路径读取失败" })} />,
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("关键路径读取失败");
    expect(html).not.toContain("关键路径尚未形成");
  });

  it("uses an honest empty state after loaded data has no path", () => {
    const html = renderToStaticMarkup(
      <ResearchCriticalPathPanel projection={null} insights={insights()} />,
    );

    expect(html).toContain("关键路径尚未形成");
    expect(html).not.toContain("暂无已确认路径");
  });
});
