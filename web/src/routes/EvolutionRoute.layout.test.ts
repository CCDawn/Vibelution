import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routeSource from "./EvolutionRoute.tsx?raw";

const stylesSource = readFileSync(new URL("./EvolutionRoute.module.css", import.meta.url), "utf-8");

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
    expect(routeSource).toContain("worktreeRuns.slice(0, 4).map");
    expect(routeSource).toContain("aria-pressed={selected}");
    expect(routeSource).toContain("onClick={() => setSelectedWorktreeRunId(run.runId)}");
  });

  it("merges supervised datasets and bundles into one source picker", () => {
    expect(routeSource).toContain("primaryDatasets");
    expect(routeSource).toContain("item.selectable !== false && item.effective");
    expect(routeSource).toContain("hiddenDatasetCount");
    expect(routeSource).toContain("supervisedSourceOptions");
    expect(routeSource).toContain('value: `dataset:${item.name}`');
    expect(routeSource).toContain('value: `bundle:${item.name}`');
    expect(routeSource).toContain("数据集会先物化，评测包可直接运行。");
    expect(routeSource).toContain("sourceInventoryBar");
    expect(routeSource).toContain("primaryDatasets.map((item)");
  });

  it("separates inconclusive terminal status and harness-only datasets from success wording", () => {
    expect(routeSource).toContain('normalizedDecision === "INCONCLUSIVE"');
    expect(routeSource).toContain("statusIcon(monitoredRun.status, monitoredRun.decision)");
    expect(routeSource).toContain("monitoredStatusLabel");
    expect(routeSource).toContain('status === "agent_harness_ready"');
    expect(routeSource).toContain('status === "custom_harness_ready"');
    expect(routeSource).toContain("自定义评测");
    expect(routeSource).toContain("非官方 Terminal-Bench 成绩");
  });

  it("labels supervised retry as rerunning failed items", () => {
    expect(routeSource).toContain("retryRunMutation");
    expect(routeSource).toContain("`/api/evolution/runs/${runId}/retry`");
  });

  it("keeps the supervised launch panel compact", () => {
    expect(routeSource).toContain("sourceMetaSide");
    expect(routeSource).toContain("数据集会先物化，评测包可直接运行。");
    expect(routeSource).toContain("worktreeRuns.slice(0, 4).map");
  });

  it("keeps the supervised live console as a dense desktop split before narrow layouts", () => {
    const desktopBreakpoint = stylesSource.slice(
      stylesSource.indexOf("@media (max-width: 1360px)"),
      stylesSource.indexOf("@media (max-width: 1200px)"),
    );
    expect(stylesSource).toContain("@media (max-width: 1360px)");
    expect(desktopBreakpoint).toContain('"launch resize-launch io resize-run run"');
    expect(desktopBreakpoint).not.toContain('"io io"\n      "launch run"');
  });

  it("lets the supervised case transcript fill the lower vertical space", () => {
    expect(routeSource).toContain("styles.transcriptSection");
    expect(stylesSource).toContain(".transcriptSection");
    expect(stylesSource).toContain("flex: 1 1 0");
    expect(stylesSource).toContain(".transcriptSection .ioTranscript");
    expect(stylesSource).not.toContain("max-height: 340px");
  });

  it("keeps the proposal library summary in three columns at common desktop widths", () => {
    expect(stylesSource).toContain(".librarySummaryBar");
    expect(stylesSource).toContain("minmax(300px, 1fr) minmax(260px, 0.8fr) minmax(300px, 0.9fr)");
  });

  it("does not put long live supervised text into native title tooltips", () => {
    expect(routeSource).not.toContain("title={monitoredRun.latestMessage}");
    expect(routeSource).not.toContain("title={monitoredTaskLabel}");
    expect(routeSource).not.toContain("title={entry.content}");
  });
});
