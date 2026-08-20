/** @vitest-environment happy-dom */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { ResearchWorkflowToolbarPreviewApp } from "./research-workflow-toolbar-preview";

describe("research workflow toolbar preview", () => {
  it("puts hypothesis and number in the switcher with a separate status column", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <ResearchWorkflowToolbarPreviewApp />
      </VuiProvider>,
    );
    expect(markup).toContain("现在 · flex-wrap 半行");
    expect(markup).toContain("建议 · 单行三区 · 宽屏");
    expect(markup).toContain('data-testid="current-toolbar"');
    expect(markup).toContain('data-testid="proposed-toolbar"');
    expect(markup).toContain("新建运行");
    expect(markup).toContain("下一步：资料寻找");
    const proposedStart = markup.indexOf('data-testid="proposed-toolbar"');
    const proposedToolbar = markup.slice(proposedStart, proposedStart + 8000);
    expect(proposedToolbar).toContain("SCI-002 · 假说待生成");
    expect(proposedToolbar).toContain('data-testid="proposed-status"');
    expect(proposedToolbar).toContain("准备中");
    expect(proposedToolbar).not.toContain("rwt-proposed-identity");
    expect(proposedToolbar).not.toContain("挑战杯ai科研团队");
    expect(proposedToolbar).not.toContain("下一步：资料寻找");
    expect(proposedToolbar).not.toContain("资料寻找 · 0/16");
    expect(markup).toContain('data-testid="proposed-hypothesis"');
    expect(markup).toContain("rwt-proposed");
    expect(markup).toContain("短假说 vs 长假说");
    expect(markup).toContain('data-testid="proposed-cta-short"');
    expect(markup).toContain('data-testid="proposed-cta-long"');
    expect(markup).toContain("720px 窄屏");
  });
});
