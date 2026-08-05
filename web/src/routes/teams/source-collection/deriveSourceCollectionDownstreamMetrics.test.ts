import { describe, expect, it } from "vitest";

import { deriveSourceCollectionDownstreamMetrics } from "./deriveSourceCollectionDownstreamMetrics";

describe("deriveSourceCollectionDownstreamMetrics", () => {
  it("falls back to summary counts and computes ingest gates", () => {
    const metrics = deriveSourceCollectionDownstreamMetrics({
      teamWorkflowSourceQualityStatus: null,
      sourceCollectionSummaryCounts: {
        approvedSourceCandidateCount: 2,
        graphNodeCount: 5,
        stewardPackCount: 1,
        formalKnowledgeSyncCount: 3,
      },
      teamWorkflowCandidateGraph: { summary: { nodeCount: 8, edgeCount: 4 } },
      teamWorkflowKnowledgeIngestionStatus: {
        summary: {
          stewardPackCandidateCount: 2,
          pendingKnowledgeReviewCandidateCount: 1,
          formalKnowledgeItemCount: 4,
        },
        knowledgeBases: [{ knowledgeBaseId: "kb-1" }],
      },
      graphProjection: null,
      memoryProjection: null,
      runApprovedCount: 1,
      displayedCandidateCount: 6,
    });
    expect(metrics.sourceCollectionApprovedCount).toBe(2);
    expect(metrics.candidateGraphNodeCount).toBe(8);
    expect(metrics.candidateGraphEdgeCount).toBe(4);
    expect(metrics.sourceCollectionDefaultKnowledgeBaseId).toBe("kb-1");
    expect(metrics.sourceCollectionPrecheckCandidateCount).toBe(2);
    expect(metrics.sourceCollectionIngestCandidateCount).toBe(6);
    expect(metrics.sourceCollectionCanBuildGraph).toBe(true);
  });

  it("disables graph when no approved or displayed candidates", () => {
    const metrics = deriveSourceCollectionDownstreamMetrics({
      teamWorkflowSourceQualityStatus: null,
      sourceCollectionSummaryCounts: {},
      teamWorkflowCandidateGraph: null,
      teamWorkflowKnowledgeIngestionStatus: null,
      graphProjection: null,
      memoryProjection: null,
      runApprovedCount: 0,
      displayedCandidateCount: 0,
    });
    expect(metrics.sourceCollectionCanBuildGraph).toBe(false);
    expect(metrics.sourceCollectionIngestCandidateCount).toBe(0);
  });
});
