import { describe, expect, it } from "vitest";

import { preflightSourceCollectionStageAdvance } from "./stageAdvancePreflight";

describe("preflightSourceCollectionStageAdvance", () => {
  it("blocks ingestion when the graph has nodes but no edges", () => {
    const result = preflightSourceCollectionStageAdvance({
      stageId: "ingestion",
      hasRun: true,
      rawRecordCount: 19,
      approvedCandidateCount: 19,
      displayedCandidateCount: 19,
      graphNodeCount: 19,
      graphEdgeCount: 0,
      graphMissingLinkCount: 36,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.redirectStageId).toBe("relations");
      expect(result.reasonZh).toContain("推进失败");
      expect(result.reasonZh).toContain("0 条边");
    }
  });

  it("blocks ingestion when missing links are still high", () => {
    const result = preflightSourceCollectionStageAdvance({
      stageId: "ingestion",
      hasRun: true,
      rawRecordCount: 19,
      approvedCandidateCount: 19,
      displayedCandidateCount: 19,
      graphNodeCount: 19,
      graphEdgeCount: 3,
      graphMissingLinkCount: 36,
      knowledgeActionItemCodes: ["candidate_graph_missing_links"],
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.redirectStageId).toBe("relations");
    }
  });

  it("allows ingestion when graph is healthy enough", () => {
    const result = preflightSourceCollectionStageAdvance({
      stageId: "ingestion",
      hasRun: true,
      rawRecordCount: 19,
      approvedCandidateCount: 19,
      displayedCandidateCount: 19,
      graphNodeCount: 19,
      graphEdgeCount: 18,
      graphMissingLinkCount: 2,
      relationsState: "done",
    });
    expect(result.ok).toBe(true);
  });

  it("blocks extraction when there are no raw records", () => {
    const result = preflightSourceCollectionStageAdvance({
      stageId: "extraction",
      hasRun: true,
      rawRecordCount: 0,
      approvedCandidateCount: 0,
      displayedCandidateCount: 0,
      graphNodeCount: 0,
      graphEdgeCount: 0,
      graphMissingLinkCount: 0,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.redirectStageId).toBe("finding");
    }
  });
});
