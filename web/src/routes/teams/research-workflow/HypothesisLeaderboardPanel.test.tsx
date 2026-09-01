/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import {
  HypothesisLeaderboardPanel,
  buildHypothesisLeaderboardModel,
  selectLeaderboardRound,
} from "./HypothesisLeaderboardPanel";

const fetchRoundsMock = vi.hoisted(() => vi.fn());

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisRounds: (...args: unknown[]) => fetchRoundsMock(...args),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function dimensionReview(dimension: string, rating: string, rationale = "") {
  return {
    dimension,
    rating,
    rationale: rationale || `${dimension} 评述`,
    evidence_refs: [`ev-${dimension}`],
    reviewer: "agent-reviewer",
  };
}

function makeRichRound() {
  return {
    roundId: "hr-002",
    question: "SCI-096",
    status: "reviewed",
    createdAt: "2026-08-02T00:00:00.000Z",
    closedAt: "2026-08-02T06:00:00.000Z",
    lineage: [],
    meetingRefs: [],
    candidates: [
      {
        candidateId: "c-alpha",
        claim: "Alpha 假设：梯度稀疏训练在竞赛数据上更稳。",
        rationale: "基于两轮证据汇总。",
        differenceFromAlternatives: "引入显式稀疏约束。",
        lineageRefs: [],
        scores: {
          novelty: 4,
          competitionFit: 5,
          falsifiability: 4,
          evidenceSupport: 3,
          feasibility: 4,
          replicability: 3,
          scopeAlignment: 4,
        },
        dimensionReviews: [
          dimensionReview("novelty", "strong", "有新意"),
          dimensionReview("falsifiability", "adequate", "可设计判决实验"),
        ],
        reviewedBy: "agent-reviewer",
        status: "reviewed",
      },
      {
        candidateId: "c-beta",
        claim: "Beta 假设：数据增广即可解释全部提升。",
        rationale: "",
        differenceFromAlternatives: "",
        lineageRefs: [],
        scores: { novelty: 2, competitionFit: 3, falsifiability: 3, evidenceSupport: 2, feasibility: 5 },
        reviewedBy: "agent-reviewer",
        status: "reviewed",
      },
      {
        candidateId: "c-gamma",
        claim: "Gamma 假设：评估噪声主导差异。",
        rationale: "",
        differenceFromAlternatives: "",
        lineageRefs: [],
        scores: { novelty: 3, competitionFit: 2, falsifiability: 5, evidenceSupport: 4, feasibility: 3 },
        reviewedBy: "agent-reviewer",
        status: "reviewed",
      },
    ],
    pairwiseComparisons: [
      {
        comparisonId: "pc-1",
        leftCandidateId: "c-alpha",
        rightCandidateId: "c-beta",
        reviewerAgentId: "agent-pair-1",
        outcome: "left_wins",
        justification: "证据支撑更强。",
      },
      {
        comparisonId: "pc-2",
        leftCandidateId: "c-alpha",
        rightCandidateId: "c-gamma",
        reviewerAgentId: "agent-pair-2",
        outcome: "tie",
        justification: "各有胜场。",
      },
    ],
    pareto: {
      paretoFrontCandidateIds: ["c-alpha", "c-gamma"],
      dominatedCandidateIds: ["c-beta"],
      analystAgentId: "agent-analyst",
      notes: "c-beta 在所有维度被 c-alpha 支配。",
    },
    metaReview: {
      metaReviewId: "mr-002",
      reviewerAgentId: "agent-meta",
      recommendationCandidateId: "c-alpha",
      rationale: "证据链最完整。",
      riskNotes: "样本量有限。",
      accepted: true,
    },
  };
}

function makeSparseRound() {
  return {
    roundId: "hr-001",
    question: "SCI-096",
    status: "closed",
    createdAt: "2026-08-01T00:00:00.000Z",
    candidates: [
      {
        candidateId: "c-delta",
        claim: "Delta 假设：更早一轮的候选。",
        rationale: "",
        differenceFromAlternatives: "",
        lineageRefs: [],
        scores: { novelty: 3 },
        reviewedBy: "agent-reviewer",
        status: "closed",
      },
    ],
    pairwiseComparisons: [],
    pareto: { paretoFrontCandidateIds: [], dominatedCandidateIds: [], analystAgentId: "", notes: "" },
    metaReview: null,
  };
}

function makePayload() {
  return {
    schemaVersion: 1,
    teamId: "research-team",
    roundCount: 2,
    corruptQuarantinedLineCount: 0,
    rounds: [makeSparseRound(), makeRichRound()],
  };
}

// ---------------------------------------------------------------------------
// Render harness
// ---------------------------------------------------------------------------

async function renderPanel(
  language: "zh" | "en",
  props: Partial<{ teamId: string; questionId: string }> = {},
) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <HypothesisLeaderboardPanel
          teamId={props.teamId ?? "research-team"}
          questionId={props.questionId ?? "SCI-096"}
        />
      </QueryClientProvider>,
    );
  });
  // Let the query settle across separate act ticks (loading stays pending).
  for (let tick = 0; tick < 8; tick += 1) {
    await act(async () => {
      await new Promise((resolveTick) => setTimeout(resolveTick, 25));
    });
  }
  return { container, root, queryClient };
}

async function clickToggle(container: HTMLElement, testId: string) {
  const button = container.querySelector<HTMLButtonElement>(`[data-testid="${testId}"]`);
  expect(button).not.toBeNull();
  await act(async () => {
    button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await new Promise((resolveTick) => setTimeout(resolveTick, 10));
  });
}

async function unmount(rendered: Awaited<ReturnType<typeof renderPanel>>) {
  await act(async () => {
    rendered.root.unmount();
  });
  rendered.container.remove();
}

describe("HypothesisLeaderboardPanel model", () => {
  it("builds chronological rounds with display indexes and parses the tally", () => {
    const model = buildHypothesisLeaderboardModel(makePayload(), "sci-096");
    expect(model.rounds.map((round) => round.roundId)).toEqual(["hr-001", "hr-002"]);
    expect(model.rounds.map((round) => round.displayIndex)).toEqual([1, 2]);
    expect(model.scopeFallback).toBe(false);
    expect(model.quarantinedCount).toBe(0);

    const round = model.rounds[1];
    const alpha = round.candidates.find((candidate) => candidate.candidateId === "c-alpha");
    const beta = round.candidates.find((candidate) => candidate.candidateId === "c-beta");
    const gamma = round.candidates.find((candidate) => candidate.candidateId === "c-gamma");
    expect(alpha?.wins).toBe(1);
    expect(alpha?.losses).toBe(0);
    expect(alpha?.ties).toBe(1);
    expect(beta?.wins).toBe(0);
    expect(beta?.losses).toBe(1);
    expect(gamma?.ties).toBe(1);
    // Presentation order: recommendation → pareto front → wins → id.
    expect(round.candidates.map((candidate) => candidate.candidateId)).toEqual([
      "c-alpha",
      "c-gamma",
      "c-beta",
    ]);
    expect(alpha?.isRecommended).toBe(true);
    expect(alpha?.isParetoFront).toBe(true);
    expect(beta?.isDominated).toBe(true);
    expect(alpha?.comparisons[0]).toMatchObject({
      opponentCandidateId: "c-beta",
      outcome: "win",
    });
    // 5 score axes stay separate from the 2 diagnostics.
    expect(alpha?.scores).toHaveLength(5);
    expect(alpha?.diagnostics.map((entry) => entry.dimension)).toEqual([
      "replicability",
      "scopeAlignment",
    ]);
    expect(alpha?.dimensionReviews).toHaveLength(2);
  });

  it("drops malformed rounds, candidates, comparisons and review rows fail-closed", () => {
    const payload = {
      schemaVersion: 1,
      teamId: "research-team",
      roundCount: 2,
      rounds: [
        null,
        42,
        { roundId: "", candidates: [{ candidateId: "c-x", claim: "x" }] },
        {
          roundId: "hr-ok",
          status: "open",
          createdAt: "2026-08-03T00:00:00.000Z",
          candidates: [
            { candidateId: "c-ok", claim: "ok", scores: { novelty: "high" } },
            { claim: "missing id" },
            "junk",
          ],
          pairwiseComparisons: [
            { comparisonId: "pc-bad", leftCandidateId: "c-ok", outcome: "left_wins" },
            { comparisonId: "pc-bad2", leftCandidateId: "c-ok", rightCandidateId: "c-ok", outcome: "maybe" },
            { comparisonId: "pc-ok", leftCandidateId: "c-ok", rightCandidateId: "c-ok", outcome: "tie" },
          ],
          dimensionReviews: "not-on-round",
        },
      ],
    };
    const model = buildHypothesisLeaderboardModel(payload as never, "");
    expect(model.rounds).toHaveLength(1);
    const round = model.rounds[0];
    expect(round.candidates.map((candidate) => candidate.candidateId)).toEqual(["c-ok"]);
    // Self-comparison still tallies once (tie), malformed comparisons dropped.
    const candidate = round.candidates[0];
    expect(candidate.wins).toBe(0);
    expect(candidate.losses).toBe(0);
    expect(candidate.ties).toBe(1);
    expect(candidate.scores).toEqual([]);
    expect(candidate.dimensionReviews).toEqual([]);
  });

  it("filters by question scope and falls back only when the wire carries no scope", () => {
    const scoped = buildHypothesisLeaderboardModel(makePayload(), "SCI-096");
    expect(scoped.rounds).toHaveLength(2);

    const unmatched = buildHypothesisLeaderboardModel(makePayload(), "SCI-999");
    expect(unmatched.rounds).toHaveLength(0);
    expect(unmatched.scopeFallback).toBe(false);

    const unscopedPayload = makePayload();
    for (const round of unscopedPayload.rounds) {
      (round as Record<string, unknown>).question = "";
    }
    const fallback = buildHypothesisLeaderboardModel(unscopedPayload, "SCI-096");
    expect(fallback.rounds).toHaveLength(2);
    expect(fallback.scopeFallback).toBe(true);
  });

  it("parses the quarantined ledger marker", () => {
    const payload = { ...makePayload(), corruptQuarantinedLineCount: 3 };
    expect(buildHypothesisLeaderboardModel(payload, "SCI-096").quarantinedCount).toBe(3);
  });

  it("selects the newest round by default and falls back for unknown ids", () => {
    const model = buildHypothesisLeaderboardModel(makePayload(), "SCI-096");
    expect(selectLeaderboardRound(model.rounds, "")?.roundId).toBe("hr-002");
    expect(selectLeaderboardRound(model.rounds, "hr-001")?.roundId).toBe("hr-001");
    expect(selectLeaderboardRound(model.rounds, "hr-missing")?.roundId).toBe("hr-002");
    expect(selectLeaderboardRound([], "")).toBeNull();
  });
});

describe("HypothesisLeaderboardPanel rendering", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    fetchRoundsMock.mockReset();
  });

  it("shows the loading state before the query settles", async () => {
    fetchRoundsMock.mockReturnValue(new Promise(() => undefined));
    const rendered = await renderPanel("zh");
    expect(rendered.container.textContent).toContain("正在读取假说评审轮次");
    await unmount(rendered);
  });

  it("shows the error state with a retry action when the endpoint fails", async () => {
    fetchRoundsMock.mockRejectedValue(new Error("backend unavailable"));
    const rendered = await renderPanel("zh");
    expect(rendered.container.textContent).toContain("假说评审轮次暂不可用");
    expect(rendered.container.textContent).toContain("重试");
    await unmount(rendered);
  });

  it("shows the empty state when no round records exist", async () => {
    fetchRoundsMock.mockResolvedValue({
      schemaVersion: 1,
      teamId: "research-team",
      roundCount: 0,
      rounds: [],
    });
    const rendered = await renderPanel("zh");
    expect(rendered.container.textContent).toContain("暂无假说评审轮次");
    await unmount(rendered);
  });

  it("renders the newest round with badges, scores, tally and metareview", async () => {
    fetchRoundsMock.mockResolvedValue(makePayload());
    const rendered = await renderPanel("zh");
    const text = rendered.container.textContent;
    // Newest round is the default view; the closed older round exists only in
    // the switcher options (Radix renders them on open), so the selected
    // label carries the round index.
    expect(text).toContain("第 2 轮 · 已评审");
    expect(text).toContain("已评审");

    expect(text).toContain("MetaReview 推荐");
    expect(text).toContain("Pareto 前沿");
    expect(text).toContain("证据链最完整。");
    expect(text).toContain("风险：样本量有限。");
    expect(text).toContain("c-beta 在所有维度被 c-alpha 支配。");

    const card = rendered.container.querySelector('[data-candidate-id="c-alpha"]');
    expect(card?.getAttribute("data-recommended")).toBe("true");
    expect(card?.textContent).toContain("1 胜 0 负 1 平");
    expect(card?.querySelector('[data-testid="leaderboard-score-grid"]')?.textContent)
      .toContain("竞赛契合");

    // Ranking is presentational: recommended → pareto → record.
    const ids = [...rendered.container.querySelectorAll('[data-testid="leaderboard-candidate-card"]')]
      .map((node) => node.getAttribute("data-candidate-id"));
    expect(ids).toEqual(["c-alpha", "c-gamma", "c-beta"]);
    await unmount(rendered);
  });

  it("expands the pairwise details and the seven-dimension review card", async () => {
    fetchRoundsMock.mockResolvedValue(makePayload());
    const rendered = await renderPanel("zh");

    await clickToggle(rendered.container, "leaderboard-toggle-reviews-c-alpha");
    const reviews = rendered.container.querySelector('[data-testid="leaderboard-reviews-c-alpha"]');
    expect(reviews?.textContent).toContain("新颖性");
    expect(reviews?.textContent).toContain("强");
    expect(reviews?.textContent).toContain("可证伪性");
    expect(reviews?.textContent).toContain("充分");
    expect(reviews?.textContent).toContain("agent-reviewer");
    expect(reviews?.textContent).toContain("ev-novelty");

    await clickToggle(rendered.container, "leaderboard-toggle-pairs-c-alpha");
    const pairs = rendered.container.querySelector('[data-testid="leaderboard-pairs-c-alpha"]');
    expect(pairs?.textContent).toContain("对阵 c-beta");
    expect(pairs?.textContent).toContain("胜");
    expect(pairs?.textContent).toContain("证据支撑更强。");
    await unmount(rendered);
  });

  it("shows the empty note when a candidate carries no dimension reviews", async () => {
    fetchRoundsMock.mockResolvedValue(makePayload());
    const rendered = await renderPanel("zh");
    await clickToggle(rendered.container, "leaderboard-toggle-reviews-c-beta");
    expect(
      rendered.container.querySelector('[data-testid="leaderboard-reviews-c-beta"]')?.textContent,
    ).toContain("本轮未产出七维评审正文");
    await unmount(rendered);
  });

  it("keeps the panel usable when the wire contains malformed entries", async () => {
    fetchRoundsMock.mockResolvedValue({
      schemaVersion: 1,
      teamId: "research-team",
      roundCount: 1,
      rounds: [null, 7, makeRichRound()],
    });
    const rendered = await renderPanel("zh");
    expect(rendered.container.textContent).toContain("c-alpha");
    expect(rendered.container.querySelectorAll('[data-testid="leaderboard-candidate-card"]'))
      .toHaveLength(3);
    await unmount(rendered);
  });

  it("annotates the scope fallback instead of showing an empty board", async () => {
    const payload = makePayload();
    for (const round of payload.rounds) {
      (round as Record<string, unknown>).question = "";
    }
    fetchRoundsMock.mockResolvedValue(payload);
    const rendered = await renderPanel("zh", { questionId: "SCI-096" });
    expect(
      rendered.container.querySelector('[data-testid="leaderboard-scope-fallback"]')?.textContent,
    ).toContain("轮次未携带题目范围");
    expect(rendered.container.textContent).toContain("c-alpha");
    await unmount(rendered);
  });

  it("surfaces the quarantined ledger marker when present", async () => {
    const payload = { ...makePayload(), corruptQuarantinedLineCount: 2 };
    fetchRoundsMock.mockResolvedValue(payload);
    const rendered = await renderPanel("zh");
    expect(
      rendered.container.querySelector('[data-testid="leaderboard-quarantined"]')?.textContent,
    ).toContain("2 条损坏记录已隔离");
    await unmount(rendered);
  });

  it("follows the shell language for chrome and shared labels", async () => {
    fetchRoundsMock.mockResolvedValue(makePayload());
    const rendered = await renderPanel("en");
    const text = rendered.container.textContent;
    expect(text).toContain("Hypothesis leaderboard · read only · SCI-096");
    expect(text).toContain("MetaReview pick");
    expect(text).toContain("1W 0L 1T");
    expect(text).toContain("Round 2 · Reviewed");

    await clickToggle(rendered.container, "leaderboard-toggle-reviews-c-alpha");
    const reviews = rendered.container.querySelector('[data-testid="leaderboard-reviews-c-alpha"]');
    expect(reviews?.textContent).toContain("Novelty");
    expect(reviews?.textContent).toContain("Strong");
    await unmount(rendered);
  });
});

// ---------------------------------------------------------------------------
// Registration contract: the panel is reachable from the workflow chrome.
// ---------------------------------------------------------------------------

describe("HypothesisLeaderboardPanel registration contract", () => {
  const readSource = (relativePath: string) =>
    readFileSync(resolve(import.meta.dirname, relativePath), "utf8");

  it("registers the leaderboard panel id across the four workflow surfaces", () => {
    expect(readSource("./researchProcessPanelSelection.ts")).toContain('"leaderboard"');
    expect(readSource("./researchProcessLocation.ts")).toContain('"leaderboard"');
    expect(readSource("./ResearchWorkflowToolbar.tsx")).toContain('onOpenPanel("leaderboard")');
    const inspector = readSource("./ResearchProcessInspectorPane.tsx");
    expect(inspector).toContain('scope.panel === "leaderboard"');
    // Inspector leaves mount through the lazy pack, never a direct import.
    expect(inspector).toContain('from "../teamLazyPanels"');
    expect(inspector).not.toContain('from "./HypothesisLeaderboardPanel"');
  });

  it("exports the panel through the research workflow lazy pack", () => {
    expect(readSource("../teamResearchWorkflowPanels.ts")).toContain("HypothesisLeaderboardPanel");
    expect(readSource("../teamLazyPanels.tsx")).toContain("HypothesisLeaderboardPanel");
  });
});
