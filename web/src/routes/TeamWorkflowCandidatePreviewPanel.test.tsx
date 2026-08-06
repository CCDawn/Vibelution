import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { TeamWorkflowCandidatePreviewPanel } from "./TeamWorkflowCandidatePreviewPanel";

describe("TeamWorkflowCandidatePreviewPanel", () => {
  it("keeps the candidate preview compact and moves supplemental copy to tooltips", () => {
    const markup = renderToStaticMarkup(
      <TeamWorkflowCandidatePreviewPanel
        lang="zh"
        items={[{
          id: "candidate-1",
          title: "Isolation Forest 基线",
          statusLabel: "候选",
          statusTitle: "等待资料提炼复核",
          tone: "pending",
        }]}
        canOpenLibrary
        reviewDisabled={false}
        reviewTitle="进入资料提炼复核"
        listNeedsScrollHint
        emptyMessage="暂无候选"
        onOpenLibrary={vi.fn()}
        onOpenReview={vi.fn()}
      />,
    );

    expect(markup).toContain("候选仓库");
    expect(markup).toContain("候选库");
    expect(markup).toContain("提炼复核");
    expect(markup).not.toContain("data-vui=\"metric-chip\"");
    expect(markup).toContain("workflowCandidateListScrollCue");
    expect(markup).not.toContain("当前显示");
    expect(markup).not.toContain("向下滚动查看更多候选");
  });
});
