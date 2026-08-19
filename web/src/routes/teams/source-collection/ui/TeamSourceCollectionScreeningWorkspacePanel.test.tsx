/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Team, TeamWorkflowCandidate } from "../../../../api/types";
import { TeamSourceCollectionScreeningWorkspacePanel } from "./TeamSourceCollectionScreeningWorkspacePanel";
import type { TeamSourceCollectionScreeningWorkspacePanelProps } from "./TeamSourceCollectionScreeningWorkspacePanel";

type Props = TeamSourceCollectionScreeningWorkspacePanelProps;

function candidate(overrides: Record<string, unknown> = {}): TeamWorkflowCandidate {
  return {
    candidateId: "cand-1",
    title: "论文 Alpha",
    summary: "关于记忆提取的实验研究",
    candidateType: "paper",
    qualityStatus: "pending",
    currentState: "collected",
    ...overrides,
  } as unknown as TeamWorkflowCandidate;
}

function makeMutation() {
  return { mutate: vi.fn(), isPending: false, variables: undefined } as unknown as Props["assessSourceQualityMutation"];
}

function baseProps(overrides: Partial<Props> = {}): Props {
  return {
    lang: "zh",
    sourceCollectionFilteredRunCandidates: [],
    sourceCollectionPageItems: (_stageId, items) => ({ items, start: items.length ? 1 : 0, end: items.length }),
    sourceCollectionSourceFilter: "all",
    sourceCollectionDisplayedCandidateCount: 0,
    sourceCollectionCountText: (_loading, count) => `${count}`,
    sourceCollectionPrimaryDataLoading: false,
    sourceCollectionDataSyncText: "同步中",
    sourceCollectionFocusedPanelId: "",
    selectedSourceCollectionStageId: "extraction",
    sourceCollectionExpandedPanelId: "",
    setSourceCollectionExpandedPanelId: vi.fn(),
    sourceCollectionExtractionDefaultPanelId: "source-collection-screening-panel",
    sourceCollectionScreeningStepState: "active",
    sourceCollectionDisplayedCandidateFilterCounts: { all: 0 },
    renderSourceCollectionFilterBar: () => null,
    sourceCollectionDisplayedCandidateCountText: "0",
    sourceCollectionProjectedAssessedCountText: "0",
    sourceCollectionProjectedApprovedCountText: "0",
    sourceCollectionRunPendingScreeningCountText: "0",
    sourceCollectionEvidenceReadyCandidateCount: 0,
    sourceCollectionMissingEvidenceAnchorCount: 0,
    runSourceCollectionScreeningAction: vi.fn(),
    sourceCollectionScreeningDisabled: false,
    selectedTeamSourceQualityPending: false,
    sourceCollectionActionDisabledTitle: () => undefined,
    sourceCollectionScreeningActionReadiness: { disabled: false } as unknown as Props["sourceCollectionScreeningActionReadiness"],
    sourceCollectionScreeningButtonText: "开始质量审查",
    openSourceCollectionScreeningPanel: vi.fn(),
    renderSourceCollectionPagination: () => null,
    teamWorkflowSourceQualityStatus: null,
    teamWorkflowSourceQualityStatusQuery: {},
    workflowIngestionTone: () => "",
    selectedTeamSourceQualityError: null,
    selectedSourceCollectionCandidateId: "",
    selectSourceCollectionCandidate: vi.fn(),
    selectedTeam: { teamId: "team-1" } as unknown as Team,
    selectedTeamAssessSourceQualityPending: false,
    assessSourceQualityMutation: makeMutation(),
    selectedTeamPlanPaperNoteChunksPending: false,
    planPaperNoteChunksMutation: makeMutation(),
    sourceCandidateHasCompletedExtraction: () => false,
    candidatePaperNoteChunkPlanSummary: () => null,
    ...overrides,
  };
}

async function renderPanel(props: Props) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<TeamSourceCollectionScreeningWorkspacePanel {...props} />);
  });
  return { container, root };
}

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(text));
}

describe("TeamSourceCollectionScreeningWorkspacePanel", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("shows the loading empty state while primary data syncs", async () => {
    const rendered = await renderPanel(baseProps({ sourceCollectionPrimaryDataLoading: true }));
    root = rendered.root;

    expect(rendered.container.textContent).toContain("正在加载质量审查候选");
  });

  it("guides the operator to search and import first when the run has no candidates", async () => {
    const rendered = await renderPanel(baseProps());
    root = rendered.root;

    expect(rendered.container.textContent).toContain("本轮还没有候选资料。先完成搜索资料并导入候选。");
  });

  it("approves a candidate through the quality mutation", async () => {
    const assessSourceQualityMutation = makeMutation();
    const rendered = await renderPanel(baseProps({
      sourceCollectionFilteredRunCandidates: [candidate()],
      sourceCollectionDisplayedCandidateCount: 1,
      assessSourceQualityMutation,
    }));
    root = rendered.root;

    const approve = buttonByText(rendered.container, "通过复核");
    expect(approve).toBeTruthy();
    expect(approve!.disabled).toBe(false);
    await act(async () => {
      approve!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(assessSourceQualityMutation.mutate).toHaveBeenCalledTimes(1);
    expect(assessSourceQualityMutation.mutate).toHaveBeenCalledWith({
      teamId: "team-1",
      candidateId: "cand-1",
      decision: "approved",
    });
  });

  it("blocks review actions for superseded preprint versions", async () => {
    const assessSourceQualityMutation = makeMutation();
    const superseded = candidate({
      sourceVersionFamily: {
        sourceKind: "research_square_preprint",
        versionLabel: "v1",
        currentVersionLabel: "v2",
        state: "superseded",
        familySize: 2,
      },
    });
    const rendered = await renderPanel(baseProps({
      sourceCollectionFilteredRunCandidates: [superseded],
      sourceCollectionDisplayedCandidateCount: 1,
      assessSourceQualityMutation,
    }));
    root = rendered.root;

    expect(rendered.container.textContent).toContain("历史版本 v1");
    const approve = buttonByText(rendered.container, "通过复核");
    expect(approve).toBeTruthy();
    expect(approve!.disabled).toBe(true);
    await act(async () => {
      approve!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(assessSourceQualityMutation.mutate).not.toHaveBeenCalled();
  });
});
