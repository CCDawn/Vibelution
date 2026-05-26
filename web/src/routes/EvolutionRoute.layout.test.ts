import { describe, expect, it } from "vitest";

import routeSource from "./EvolutionRoute.tsx?raw";

describe("EvolutionRoute library user flow contract", () => {
  it("shows self-evolution candidates as local pending details instead of proposal details", () => {
    expect(routeSource).toContain("selectedProposalIsSelfCandidate");
    expect(routeSource).toContain("!selectedProposalIsSelfCandidate");
    expect(routeSource).toContain("renderSelfEvolutionCandidateDetail(selectedProposalSummary)");
    expect(routeSource).toContain("function isSelfEvolutionCandidateItem");
    expect(routeSource).toContain('item?.ingestMode === "self_evolution_candidate"');
  });

  it("labels self-evolution candidate origins without opening them as supervised runs", () => {
    expect(routeSource).toContain("function proposalDisplaySourceRun");
    expect(routeSource).toContain("item.sourceSelfRunId || item.sourceRun");
    expect(routeSource).toContain("function canOpenProposalSourceRun");
    expect(routeSource).toContain("!isSelfEvolutionCandidateItem(item)");
    expect(routeSource).toContain("selectedProposalDisplaySourceRun || latestRun?.id");
    expect(routeSource).toContain("selectedProposalSummary && selectedProposalCanOpenSourceRun");
    expect(routeSource).toContain("item.riskLevel ? riskLabel(item.riskLevel) : \"--\"");
  });

  it("does not let blocked library items enter batch delete selection", () => {
    const disabledSelectionCount = routeSource.match(/disabled={!item\.canDelete}/g)?.length ?? 0;
    expect(disabledSelectionCount).toBeGreaterThanOrEqual(2);
    expect(routeSource).toContain("visibleLibraryEntries.filter((item) => item.canDelete).map((item) => item.sourceRun)");
    expect(routeSource).toContain("function toggleProposalSelection(item: EvolutionLibraryEntry)");
    expect(routeSource).toContain("if (!item.canDelete)");
    expect(routeSource).toContain("onChange={() => toggleProposalSelection(item)}");
  });

  it("adds collapse handles to the supervised split panes", () => {
    expect(routeSource).toContain("PaneCollapseHandle");
    expect(routeSource).toContain("liveLaunchCollapsed");
    expect(routeSource).toContain("liveRunCollapsed");
    expect(routeSource).toContain("runsQueueCollapsed");
    expect(routeSource).toContain("libraryListCollapsed");
  });

  it("routes risky self-evolution writes into the supervised worktree endpoint", () => {
    expect(routeSource).toContain("startSelfWorktreeRunMutation");
    expect(routeSource).toContain('"/api/evolution/self/worktree-runs"');
    expect(routeSource).toContain('mode: "manual"');
    expect(routeSource).toContain("onStartWorktreeRun={() => startSelfWorktreeRunMutation.mutate()}");
    expect(routeSource).toContain("startWorktreeError={startSelfWorktreeRunMutation.error?.message ?? \"\"}");
  });

  it("surfaces self-origin worktree review gates without auto-merging", () => {
    expect(routeSource).toContain("worktreeRunsQuery");
    expect(routeSource).toContain('"/api/evolution/worktree-runs"');
    expect(routeSource).toContain("isSelfEvolutionWorktreeRun");
    expect(routeSource).toContain("worktreeReviewGate");
    expect(routeSource).toContain("highlightedReviewPending");
    expect(routeSource).toContain("worktreeActionMutation");
    expect(routeSource).toContain('action: "approve_review"');
    expect(routeSource).toContain('reviewerNote: t("selfWorktreeReviewNote")');
    expect(routeSource).toContain("approveSelfWorktreeReview");
    expect(routeSource).toContain("selfWorktreeReviewHint");
  });

  it("keeps worktree follow-up actions explicit and separate from review approval", () => {
    expect(routeSource).toContain("WORKTREE_ACTION_ITEMS");
    expect(routeSource).toContain('action: "analyze_merge"');
    expect(routeSource).toContain('action: "preserve"');
    expect(routeSource).toContain('action: "discard"');
    expect(routeSource).toContain('action: "merge"');
    expect(routeSource).toContain("highlightedWorktreeActions.map");
    expect(routeSource).toContain("triggerWorktreeAction(highlightedWorktreeRun, item.action)");
    expect(routeSource).toContain("selfWorktreeMergeRequiresReview");
  });

  it("lets users select a recent worktree run for review actions", () => {
    expect(routeSource).toContain("selectedWorktreeRunId");
    expect(routeSource).toContain("setSelectedWorktreeRunId(activeRunId)");
    expect(routeSource).toContain("setSelectedWorktreeRunId(worktreeRuns[0]?.runId ?? null)");
    expect(routeSource).toContain("selectedWorktreeRun");
    expect(routeSource).toContain("worktreeRunPicker");
    expect(routeSource).toContain("worktreeRuns.slice(0, 6).map");
    expect(routeSource).toContain("aria-pressed={selected}");
    expect(routeSource).toContain("onClick={() => setSelectedWorktreeRunId(run.runId)}");
  });
});
