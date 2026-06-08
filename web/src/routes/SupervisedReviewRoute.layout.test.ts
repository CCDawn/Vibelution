import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";

const routeSource = readFileSync(new URL("./SupervisedReviewRoute.tsx", import.meta.url), "utf-8");
const stylesSource = readFileSync(new URL("./SupervisedReviewRoute.module.css", import.meta.url), "utf-8");
const worktreePanelSource = readFileSync(new URL("./SupervisedWorktreeReviewPanel.tsx", import.meta.url), "utf-8");
const worktreePanelStyles = readFileSync(new URL("./SupervisedWorktreeReviewPanel.module.css", import.meta.url), "utf-8");

describe("SupervisedReviewRoute layout contract", () => {
  it("keeps the review workspace in split-pane layout at common desktop widths", () => {
    expect(stylesSource).toContain("@media (min-width: 981px) and (max-width: 1600px)");
    expect(stylesSource).toContain("grid-template-columns: var(--review-queue-width, 380px) 12px minmax(0, 1fr)");
    expect(stylesSource).toContain("@media (max-width: 980px)");
    expect(stylesSource).not.toContain("@media (max-width: 1280px)");
  });

  it("keeps review empty states compact enough for the first viewport", () => {
    expect(stylesSource).toContain("min-height: 118px");
    expect(stylesSource).toContain("padding: 8px 12px 12px");
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
    expect(worktreePanelSource).toContain("WORKTREE_ACTION_ITEMS");
    expect(worktreePanelSource).toContain('action: "analyze_merge"');
    expect(worktreePanelSource).toContain('action: "preserve"');
    expect(worktreePanelSource).toContain('action: "discard"');
    expect(worktreePanelSource).toContain('action: "merge"');
    expect(worktreePanelSource).toContain("setSelectedWorktreeRunId");
    expect(worktreePanelSource).toContain("runs.slice(0, 4).map");
    expect(worktreePanelSource).toContain("selfWorktreeMergeRequiresReview");
    expect(worktreePanelStyles).toContain(".worktreeReviewSurface");
    expect(worktreePanelStyles).toContain(".worktreeReviewGate .controlActions");
    expect(worktreePanelStyles).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
  });
});
