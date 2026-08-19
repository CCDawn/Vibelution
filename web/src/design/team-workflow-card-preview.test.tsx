/** @vitest-environment happy-dom */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { TeamWorkflowCardPreviewApp } from "./team-workflow-card-preview";

describe("team workflow card preview", () => {
  it("places current and proposed research cards side by side", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <TeamWorkflowCardPreviewApp />
      </VuiProvider>,
    );
    expect(markup).toContain("现在 · 244×102 · 8px 脚注");
    expect(markup).toContain("建议 · 268×84 · 14/12px");
    expect(markup).toContain('data-testid="current-find"');
    expect(markup).toContain('data-testid="proposed-find"');
    expect(markup).toContain("资料搜集 · 白望舒");
    expect(markup).toContain("类型只靠图标，例外才打标签");
  });
});
