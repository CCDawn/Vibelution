import { describe, expect, it } from "vitest";

import styles from "./SupervisedReviewRoute.styles";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";

const routeSource = readFileSync(new URL("./SupervisedReviewRoute.tsx", import.meta.url), "utf-8");
const worktreePanelSource = readFileSync(new URL("./SupervisedWorktreeReviewPanel.tsx", import.meta.url), "utf-8");
const routeStylesSource = readFileSync(new URL("./SupervisedReviewRoute.styles.ts", import.meta.url), "utf-8");
const worktreePanelStylesSource = readFileSync(new URL("./SupervisedWorktreeReviewPanel.styles.ts", import.meta.url), "utf-8");

function routeStyle(name: string) {
  const match = routeStylesSource.match(new RegExp(`${name}:\\s*"([^"]+)"`));
  expect(match, `${name} style exists`).not.toBeNull();
  return match?.[1] ?? "";
}

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
    const workspaceClass = routeStyle("workspace");
    const queuePanelClass = routeStyle("queuePanel");
    const detailPanelClass = routeStyle("detailPanel");

    expect(routeSource).toContain("className={styles.workspace}");
    expect(workspaceClass).toContain("grid-cols-[var(--review-queue-width,380px)_12px_minmax(0,1fr)]");
    expect(workspaceClass).toContain("min-h-0");
    expect(workspaceClass).toContain("minmax(0,1fr)");
    expect(workspaceClass).toContain("max-[980px]:grid-cols-1");
    expect(workspaceClass).toContain("max-[980px]:overflow-visible");
    expect(workspaceClass).not.toContain("max-[1280px]:grid-cols-1");
    expect(queuePanelClass).toContain("min-h-0");
    expect(detailPanelClass).toContain("min-h-0");
  });

  it("keeps the route surface background-aware instead of stacking opaque route-owned panels", () => {
    const pageClass = routeStyle("page");
    const primaryPanelClasses = [
      routeStyle("summaryCard"),
      routeStyle("lifecyclePanel"),
      routeStyle("queuePanel"),
      routeStyle("detailPanel"),
    ];

    expect(pageClass).toContain("min-w-0");
    expect(styles.workspace).toContain("min-w-0");
    expect(pageClass).not.toContain("bg-[var(--surface-page)]");
    for (const panelClass of primaryPanelClasses) {
      expect(panelClass).not.toMatch(/bg-\[var\(--surface-panel(?:-strong)?\)\]/);
      expect(panelClass).toContain("color-mix");
    }
    expect(styles.queuePanel).toContain("min-w-0");
    expect(styles.detailPanel).toContain("min-w-0");
  });

  it("keeps review data surfaces lightweight instead of a thick card wall", () => {
    const repeatedSurfaces = [
      styles.summaryCard,
      styles.factCard,
      styles.metricCard,
      styles.signalSection,
      styles.detailSection,
      styles.transcriptSection,
      styles.evidenceCard,
      styles.transcriptCard,
    ];

    for (const surface of repeatedSurfaces) {
      expect(surface).toContain("border-[var(--border-hairline)]");
      expect(surface).not.toContain("bg-[var(--surface-panel-strong)]");
    }

    expect(styles.factCard).toContain("min-w-0");
    expect(styles.metricCard).toContain("min-w-0");
    expect(styles.evidenceCard).toContain("bg-[color-mix(in_srgb,var(--surface-card)_");
    expect(styles.transcriptCard).toContain("bg-[color-mix(in_srgb,var(--surface-card)_");
  });

  it("keeps review actions content-sized while preserving danger emphasis", () => {
    const contentSizedActions = [
      styles.filterButton,
      styles.decisionButton,
      styles.primaryAction,
      styles.secondaryAction,
      styles.compactAction,
    ];

    for (const action of contentSizedActions) {
      expect(action).toContain("w-fit");
      expect(action).toContain("max-w-full");
      expect(action).not.toContain(" w-full");
    }

    expect(styles.bulkActions).toContain("flex");
    expect(styles.bulkActions).toContain("flex-wrap");
    expect(styles.bulkActions).not.toContain("grid-cols-3");
    expect(styles.actionRow).toContain("flex-wrap");
    expect(styles.dangerAction).toContain("var(--state-error)");
  });

  it("keeps dense review rows from overflowing at 390px mobile width", () => {
    expect(styles.bulkToolbar).toContain("max-[520px]:grid-cols-1");
    expect(styles.detailHeader).toContain("max-[520px]:flex-col");
    expect(styles.detailHeaderActions).toContain("flex-wrap");
    expect(styles.queueFooter).toContain("flex-wrap");
    expect(styles.queueHeadline).toContain("min-w-0");
    expect(styles.queueHeadline).toContain("break-words");
    expect(styles.signalRow).toContain("min-w-0");
    expect(styles.signalPill).toContain("max-w-full");
    expect(styles.signalPill).toContain("truncate");
    expect(styles.evidenceTop).toContain("grid-cols-[max-content_minmax(0,1fr)]");
    expect(styles.evidenceTop).toContain("max-[520px]:grid-cols-1");
    expect(styles.metaRow).toContain("grid-cols-[max-content_minmax(0,1fr)]");
    expect(styles.metaRow).toContain("max-[520px]:grid-cols-1");
    expect(styles.transcriptMeta).toContain("min-w-0");
  });

  it("keeps review empty states compact enough for the first viewport", () => {
    expect(routeSource).toContain("className={styles.emptyState}");
    expect(routeStylesSource).toContain("min-h-[82px]");
    expect(routeStylesSource).toContain("px-[11px] py-[9px]");
    expect(routeStylesSource).not.toContain("min-h-[118px]");
  });

  it("keeps repeated review controls as named Tailwind slices", () => {
    expect(routeStylesSource).toContain("const reviewControlButton");
    expect(routeStylesSource).toContain("const reviewControlButtonActive");
    expect(routeStylesSource).toContain("const reviewPrimaryActionButton");
    expect(routeStylesSource).toContain("const reviewFormLabel");
    expect(routeStylesSource).toContain("const reviewInputTargets");
    expect(routeStylesSource).toContain("const reviewTextAreaTargets");
    expect(routeStylesSource).toContain("filterButton: reviewControlButton");
    expect(routeStylesSource).toContain("decisionButton: reviewControlButton");
    expect(routeStylesSource).toContain("secondaryAction: reviewControlButton");
    expect(routeStylesSource).toContain("filterButtonActive: reviewControlButtonActive");
    expect(routeStylesSource).toContain("decisionButtonActive: reviewControlButtonActive");
    expect(routeStylesSource).toContain("primaryAction: reviewPrimaryActionButton");
    expect(routeStylesSource).toContain("formField: reviewFormField");
    expect(routeStylesSource).toContain("textAreaField: reviewTextAreaField");
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
    expect(worktreePanelStylesSource).toContain("gateActionGridClass");
    expect(worktreePanelStylesSource).toContain("grid-cols-2");
  });
});
