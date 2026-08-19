/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TeamWorkflowCandidate } from "../../../../api/types";
import { TeamSourceCollectionCandidateWorkspacePanel } from "./TeamSourceCollectionCandidateWorkspacePanel";
import type { TeamSourceCollectionCandidateWorkspacePanelProps } from "./TeamSourceCollectionCandidateWorkspacePanel";

function candidate(overrides: Record<string, unknown> = {}): TeamWorkflowCandidate {
  return {
    candidateId: "cand-1",
    title: "论文 Alpha",
    summary: "关于记忆提取的实验研究",
    qualityStatus: "pending",
    currentState: "collected",
    ...overrides,
  } as unknown as TeamWorkflowCandidate;
}

function baseProps(overrides: Partial<TeamSourceCollectionCandidateWorkspacePanelProps> = {}): TeamSourceCollectionCandidateWorkspacePanelProps {
  return {
    lang: "zh",
    sourceCollectionFilteredRunCandidates: [],
    sourceCollectionPageItems: (_stageId, items) => ({ items, start: items.length ? 1 : 0, end: items.length }),
    sourceCollectionCandidateProjection: null,
    sourceCollectionSourceFilter: "all",
    sourceCollectionDisplayedCandidateCount: 0,
    sourceCollectionCountText: (_loading, count) => `${count}`,
    sourceCollectionPrimaryDataLoading: false,
    sourceCollectionDataSyncText: "同步中",
    sourceCollectionRunCandidateCount: 0,
    sourceCollectionFocusedPanelId: "",
    selectedSourceCollectionStageId: "extraction",
    sourceCollectionExpandedPanelId: "",
    setSourceCollectionExpandedPanelId: vi.fn(),
    sourceCollectionExtractionDefaultPanelId: "source-collection-candidates-panel",
    sourceCollectionCandidateStepState: "active",
    sourceCollectionDisplayedCandidateFilterCounts: { all: 0 },
    renderSourceCollectionFilterBar: () => null,
    sourceCollectionDisplayedCandidateCountText: "0",
    sourceCollectionProjectedAssessedCountText: "0",
    sourceCollectionProjectedApprovedCountText: "0",
    sourceCollectionRunPendingScreeningCountText: "0",
    sourceCollectionEvidenceReadyCandidateCount: 0,
    sourceCollectionMissingEvidenceAnchorCount: 0,
    sourceCollectionProjectedCollectedCount: 0,
    renderSourceCollectionPagination: () => null,
    selectedSourceCollectionCandidateId: "",
    selectSourceCollectionCandidate: vi.fn(),
    ...overrides,
  };
}

async function renderPanel(props: TeamSourceCollectionCandidateWorkspacePanelProps) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<TeamSourceCollectionCandidateWorkspacePanel {...props} />);
  });
  return { container, root };
}

describe("TeamSourceCollectionCandidateWorkspacePanel", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("shows the syncing skeleton while primary data is loading", async () => {
    const rendered = await renderPanel(baseProps({
      sourceCollectionPrimaryDataLoading: true,
      sourceCollectionDataSyncText: "正在同步…",
    }));
    root = rendered.root;

    expect(rendered.container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(rendered.container.textContent).toContain("正在同步…");
  });

  it("guides the operator to continue extraction when records exist but no candidates", async () => {
    const rendered = await renderPanel(baseProps({
      sourceCollectionProjectedCollectedCount: 3,
    }));
    root = rendered.root;

    expect(rendered.container.textContent).toContain("已收到 3 条原始资料");
    expect(rendered.container.textContent).toContain("继续补全提炼");
  });

  it("explains when agents produced candidates that are still syncing", async () => {
    const rendered = await renderPanel(baseProps({
      sourceCollectionDisplayedCandidateCount: 5,
      sourceCollectionRunCandidateCount: 0,
    }));
    root = rendered.root;

    expect(rendered.container.textContent).toContain("列表正在同步");
  });

  it("selects a candidate from its card and marks the selected row", async () => {
    const selectSourceCollectionCandidate = vi.fn();
    const first = candidate({ candidateId: "cand-1", title: "论文 Alpha" });
    const second = candidate({ candidateId: "cand-2", title: "论文 Beta" });
    const rendered = await renderPanel(baseProps({
      sourceCollectionFilteredRunCandidates: [first, second],
      sourceCollectionDisplayedCandidateCount: 2,
      sourceCollectionRunCandidateCount: 2,
      selectedSourceCollectionCandidateId: "cand-2",
      selectSourceCollectionCandidate,
    }));
    root = rendered.root;

    const titleButton = Array.from(rendered.container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("论文 Alpha"));
    expect(titleButton).toBeTruthy();
    await act(async () => {
      titleButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(selectSourceCollectionCandidate).toHaveBeenCalledTimes(1);
    expect(selectSourceCollectionCandidate).toHaveBeenCalledWith(first);
  });
});
