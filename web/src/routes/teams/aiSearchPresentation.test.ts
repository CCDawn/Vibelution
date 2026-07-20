import { describe, expect, it } from "vitest";

import type { AiSearchRun } from "../../api/types";
import {
  AI_SEARCH_RUN_PREVIEW_LIMIT,
  aiSearchRunCardModeLabel,
  aiSearchRunCardUsesFallback,
  aiSearchRunCounts,
  aiSearchRunNextActionText,
  aiSearchRunPrimaryResultText,
  aiSearchRunStatusLabel,
  aiSearchSourceRoleLabel,
  aiSearchSourceTierLabel,
} from "./aiSearchPresentation";

function run(partial: Partial<AiSearchRun> & Pick<AiSearchRun, "runId" | "status">): AiSearchRun {
  return {
    runId: partial.runId,
    status: partial.status,
    topic: partial.topic || "topic",
    cardCount: partial.cardCount ?? 0,
    succeededCount: partial.succeededCount ?? 0,
    failedCount: partial.failedCount ?? 0,
    degradedCount: partial.degradedCount ?? 0,
    referenceCount: partial.referenceCount ?? 0,
    queryCount: partial.queryCount ?? 0,
    cards: partial.cards || [],
    storage: partial.storage || { runPath: "workspace/ai-search/run-1" },
  } as AiSearchRun;
}

describe("aiSearchPresentation", () => {
  it("exports preview limit and source labels", () => {
    expect(AI_SEARCH_RUN_PREVIEW_LIMIT).toBe(6);
    expect(aiSearchSourceRoleLabel("primary", "zh")).toContain("一手");
    expect(aiSearchSourceTierLabel("tier1", "en")).toContain("official");
    expect(aiSearchRunStatusLabel("partial", "zh")).toContain("部分");
  });

  it("summarizes run counts and review-oriented copy", () => {
    const sample = run({
      runId: "r1",
      status: "completed",
      succeededCount: 2,
      failedCount: 1,
      referenceCount: 4,
      cards: [
        { status: "ok" } as AiSearchRun["cards"][number],
        { status: "failed" } as AiSearchRun["cards"][number],
        { status: "ok", searchMode: "source_page_fallback" } as AiSearchRun["cards"][number],
      ],
    });
    const counts = aiSearchRunCounts(sample);
    expect(counts.succeededCount).toBe(2);
    expect(aiSearchRunCardUsesFallback(sample.cards[2])).toBe(true);
    expect(aiSearchRunCardModeLabel(sample.cards[2], "zh")).toContain("源页");
    expect(aiSearchRunPrimaryResultText(sample, counts, "zh")).toContain("可用结果");
    expect(aiSearchRunNextActionText(sample, counts, "en").toLowerCase()).toMatch(/review|extraction|expand/);
  });
});
