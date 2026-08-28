import { describe, expect, it } from "vitest";

import type { KnowledgeInvocationBadge } from "../../../api/types/research-workflow/core";
import {
  buildKnowledgeCollectionInspectorModel,
} from "./knowledgeCollectionInspectorModel";

function badge(overrides: Partial<KnowledgeInvocationBadge> = {}): KnowledgeInvocationBadge {
  return {
    nodeId: "problem_understanding",
    totalCount: 1,
    runningCount: 0,
    awaitingHandoffCount: 0,
    absorbedCount: 0,
    ...overrides,
  };
}

describe("buildKnowledgeCollectionInspectorModel", () => {
  it("starts at not_started without a badge and explains the request preview", () => {
    const model = buildKnowledgeCollectionInspectorModel({ badge: null });
    expect(model.phase).toBe("not_started");
    expect(model.progress).toBeNull();
    expect(model.detail).toContain("尚未发起");
  });

  it("treats a badge without invocations as not_started", () => {
    const model = buildKnowledgeCollectionInspectorModel({
      badge: badge({ totalCount: 0, latest: null }),
    });
    expect(model.phase).toBe("not_started");
  });

  it("derives collecting state with chain progress from the current node", () => {
    const model = buildKnowledgeCollectionInspectorModel({
      badge: badge({
        runningCount: 1,
        latest: {
          invocationId: "inv-1",
          parentNodeId: "problem_understanding",
          status: "running",
          handoffState: null,
          currentKnowledgeNodeId: "source_extraction",
          knowledgeChildRunId: "child-1",
          updatedAtMs: 5,
        },
      }),
    });
    expect(model.phase).toBe("collecting");
    expect(model.headline).toContain("知识搜集中");
    expect(model.lineage.childRunId).toBe("child-1");
    expect(model.lineage.sourceNodeId).toBe("problem_understanding");
    expect(model.progress).toEqual({
      completedNodes: 1,
      totalNodes: 5,
      currentNodeId: "source_extraction",
    });
  });

  it("derives awaiting_handoff with the handoff gate as current node", () => {
    const model = buildKnowledgeCollectionInspectorModel({
      badge: badge({
        awaitingHandoffCount: 1,
        latest: {
          invocationId: "inv-2",
          parentNodeId: "source_finding",
          status: "awaiting_handoff",
          handoffState: "awaiting_human",
          currentKnowledgeNodeId: "knowledge_handoff",
          knowledgePackageRef: "kb://pkg-1",
          packageContentHash: "a".repeat(64),
          updatedAtMs: 6,
        },
      }),
    });
    expect(model.phase).toBe("awaiting_handoff");
    expect(model.progress?.completedNodes).toBe(4);
    expect(model.progress?.currentNodeId).toBe("knowledge_handoff");
    expect(model.packageRef).toBe("kb://pkg-1");
    expect(model.packageHash).toBe("a".repeat(64));
  });

  it("derives handed_off as fully completed progress", () => {
    const model = buildKnowledgeCollectionInspectorModel({
      badge: badge({
        absorbedCount: 1,
        latest: {
          invocationId: "inv-3",
          parentNodeId: "source_finding",
          status: "completed",
          handoffState: "completed",
          currentKnowledgeNodeId: "knowledge_handoff",
          updatedAtMs: 7,
        },
      }),
    });
    expect(model.phase).toBe("handed_off");
    expect(model.progress).toEqual({ completedNodes: 5, totalNodes: 5, currentNodeId: null });
  });

  it("derives failed state for recovery", () => {
    const model = buildKnowledgeCollectionInspectorModel({
      badge: badge({
        failedCount: 1,
        latest: {
          invocationId: "inv-4",
          parentNodeId: "evidence_relations",
          status: "failed",
          handoffState: null,
          currentKnowledgeNodeId: "knowledge_ingestion",
          errorSummary: "source search failed",
          updatedAtMs: 8,
        },
      }),
    });
    expect(model.phase).toBe("failed");
    expect(model.lineage.invocationId).toBe("inv-4");
    expect(model.detail).toContain("失败");
  });

  it("reports the request count in the headline", () => {
    const model = buildKnowledgeCollectionInspectorModel({
      badge: badge({ totalCount: 3, latest: null }),
    });
    // A count without a latest invocation still reads as not_started...
    expect(model.phase).toBe("not_started");
    const active = buildKnowledgeCollectionInspectorModel({
      badge: badge({
        totalCount: 3,
        runningCount: 1,
        latest: {
          invocationId: "inv-5",
          parentNodeId: "problem_understanding",
          status: "running",
          handoffState: null,
          currentKnowledgeNodeId: "source_finding",
          updatedAtMs: 9,
        },
      }),
    });
    expect(active.headline).toContain("3 次");
  });
});
