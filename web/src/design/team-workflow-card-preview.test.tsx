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
    expect(markup).toContain("现在 · 横排挤卡 · 244×102");
    expect(markup).toContain("建议 · 竖排模块卡 · 实心色块");
    expect(markup).toContain('data-testid="current-find"');
    expect(markup).toContain('data-testid="proposed-find"');
    expect(markup).toContain("资料搜集 · 白望舒");
    expect(markup).toContain("类型只靠实心色块，状态只靠图标角标");
    expect(markup).toContain("twc-proposed-mark");
  });
});
