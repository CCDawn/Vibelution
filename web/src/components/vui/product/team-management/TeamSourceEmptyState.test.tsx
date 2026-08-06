import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TeamSourceEmptyState } from "./TeamSourceEmptyState";

describe("TeamSourceEmptyState", () => {
  it("renders a centered blank slate without empty support copy", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceEmptyState title="暂无资料" description="" />,
    );

    expect(markup).toContain('data-vui-product="team-source-empty-state"');
    expect(markup).toContain('data-slot="source-empty-visual"');
    expect(markup).toContain("lucide-search-x");
    expect(markup).toContain("暂无资料");
    expect(markup).not.toContain('data-slot="source-empty-description"');
    expect(markup).not.toContain("accent-cool");
  });

  it("keeps facts and actions as distinct blank-slate regions", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceEmptyState
        title="暂无资料"
        description="调整筛选条件"
        facts={[{ key: "query", label: "关键词", value: "园区能耗" }]}
        actions={<button type="button">清除筛选</button>}
      />,
    );

    expect(markup).toContain('data-slot="source-empty-description"');
    expect(markup).toContain('data-slot="source-empty-facts"');
    expect(markup).toContain("<dt");
    expect(markup).toContain("<dd");
    expect(markup).toContain("清除筛选");
  });
});
