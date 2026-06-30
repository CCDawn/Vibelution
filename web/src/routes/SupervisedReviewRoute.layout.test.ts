import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";

const routeSource = readFileSync(new URL("./SupervisedReviewRoute.tsx", import.meta.url), "utf-8");
const worktreePanelSource = readFileSync(new URL("./SupervisedWorktreeReviewPanel.tsx", import.meta.url), "utf-8");

describe("SupervisedReviewRoute layout contract", () => {
  it("routes supervised review controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).toContain("<VNativeSelect");
    expect(routeSource).toContain("<VNativeTextarea");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
    expect(worktreePanelSource).toContain('from "../components/vui"');
    expect(worktreePanelSource).toContain("<VButton");
    expect(worktreePanelSource).not.toMatch(/<button\b/);
  });

  it("keeps the review workspace in split-pane layout at common desktop widths", () => {
    expect(routeSource).toContain("grid-cols-[var(--review-queue-width,380px)_12px_minmax(0,1fr)]");
    expect(routeSource).toContain("max-[980px]:grid-cols-1");
    expect(routeSource).toContain("max-[980px]:overflow-visible");
    expect(routeSource).not.toContain("max-[1280px]:grid-cols-1");
  });

  it("keeps review empty states compact enough for the first viewport", () => {
    expect(routeSource).toContain("min-h-[82px]");
    expect(routeSource).toContain("px-[11px] py-[9px]");
    expect(routeSource).not.toContain("min-h-[118px]");
  });

  it("hosts candidate worktree review inside the sample review workspace", () => {
    expect(routeSource).toContain("SupervisedWorktreeReviewPanel");
    expect(routeSource).toContain("queryKeys.evolutionWorkspaceSnapshot()");
    expect(routeSource).toContain('"/api/evolution/workspace-snapshot"');
    expect(routeSource).toContain("worktreeActionMutation");
    expect(routeSource).toContain('action: "approve_review"');
    expect(routeSource).toContain('reviewerNote: t("selfWorktreeReviewNote")');
    expect(routeSource).toContain('action === "discard" || action === "merge"');
    expect(routeSource).toContain("discardWorktreeConfirm");
    expect(routeSource).toContain("mergeWorktreeConfirm");
  });

  it("loads chat review queue summaries and selected candidate details separately", () => {
    expect(routeSource).toContain('fetchJson<EvolutionChatReviewQueue>("/api/evolution/chat-review")');
    expect(routeSource).toContain("queryKeys.evolutionChatReviewCandidate");
    expect(routeSource).toContain("fetchJson<EvolutionChatReviewCandidate>");
    expect(routeSource).toContain('`/api/evolution/chat-review/${encodeURIComponent(selectedCandidate?.candidateId ?? "")}`');
    expect(routeSource).not.toContain("includeDetails=true");
  });

  it("keeps worktree review actions explicit in the shared panel", () => {
    const genericActionsIndex = worktreePanelSource.indexOf("worktreeActionGateClass");
    const actionMapIndex = worktreePanelSource.indexOf("highlightedWorktreeActions.map");
    const selfOriginGateIndex = worktreePanelSource.indexOf("highlightedIsSelfOrigin && highlightedWorktreeRun ? (");

    expect(worktreePanelSource).toContain("WORKTREE_ACTION_ITEMS");
    expect(worktreePanelSource).toContain('action: "analyze_merge"');
    expect(worktreePanelSource).toContain('action: "preserve"');
    expect(worktreePanelSource).toContain('action: "discard"');
    expect(worktreePanelSource).toContain('action: "merge"');
    expect(genericActionsIndex).toBeGreaterThan(-1);
    expect(actionMapIndex).toBeGreaterThan(genericActionsIndex);
    expect(selfOriginGateIndex).toBeGreaterThan(actionMapIndex);
    expect(worktreePanelSource).toContain("setSelectedWorktreeRunId");
    expect(worktreePanelSource).toContain("runs.slice(0, 4).map");
    expect(worktreePanelSource).toContain("selfWorktreeMergeRequiresReview");
    expect(worktreePanelSource).toContain("worktreeReviewSurfaceClass");
    expect(worktreePanelSource).toContain("worktreeReviewGateClass");
    expect(worktreePanelSource).toContain("controlActionsClass");
    expect(worktreePanelSource).toContain("gateActionGridClass");
    expect(worktreePanelSource).toContain("grid-cols-2");
  });
});
