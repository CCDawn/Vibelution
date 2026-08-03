import { describe, expect, it } from "vitest";

import { buildResearchBoardColumns } from "./researchBoardModel";

describe("buildResearchBoardColumns", () => {
  it("builds three preview-aligned columns with fallback cards", () => {
    const columns = buildResearchBoardColumns({
      lang: "zh",
      phases: [],
      sourceRunCount: 0,
      sourceCandidateCount: 0,
    });
    expect(columns).toHaveLength(3);
    expect(columns.map((item) => item.id)).toEqual([
      "knowledge_collection",
      "experiment",
      "iteration",
    ]);
    expect(columns.every((column) => column.cards.length >= 1)).toBe(true);
  });

  it("surfaces source progress and frozen design cards", () => {
    const columns = buildResearchBoardColumns({
      lang: "zh",
      phases: [],
      sourceRunCount: 2,
      sourceCandidateCount: 17,
      experimentDesignFrozen: true,
      frozenDesignLabel: "Design v4",
      bestCandidateId: "formal-v4",
      latestDiagnostic: "smoke_needs_review",
    });
    expect(columns[0].cards[0].title).toContain("资料批次");
    expect(columns[1].cards.some((card) => card.title.includes("Design v4"))).toBe(true);
    expect(columns[2].cards.some((card) => card.id === "it-best")).toBe(true);
    expect(columns[2].cards.some((card) => card.id === "it-diag")).toBe(true);
  });
});
