import { describe, expect, it } from "vitest";

import type { TeamCanvasNode, TeamWorkflowCandidate } from "../../api/types";
import {
  canvasNodeStatusLabel,
  latestWorkflowCandidate,
  parseSourceCollectionStageModuleId,
  researchStageStartFeedbackText,
  sourceCandidateHasCompletedExtraction,
  teamNodeFunctionLabel,
} from "./teamRouteShellModel";

describe("teamRouteShellModel", () => {
  it("normalizes source-collection stage module aliases", () => {
    expect(parseSourceCollectionStageModuleId("search")).toBe("finding");
    expect(parseSourceCollectionStageModuleId("extract")).toBe("extraction");
    expect(parseSourceCollectionStageModuleId("graph")).toBe("relations");
    expect(parseSourceCollectionStageModuleId("memory")).toBe("ingestion");
    expect(parseSourceCollectionStageModuleId("finding")).toBe("finding");
    expect(parseSourceCollectionStageModuleId("unknown")).toBeNull();
  });

  it("labels canvas nodes and sorts latest workflow candidates", () => {
    const node = { role: "research_ceo", purpose: "lead", agentId: "a1", status: "bound" } as TeamCanvasNode;
    expect(teamNodeFunctionLabel(node, undefined, "zh")).toBe("科研负责人");
    expect(canvasNodeStatusLabel(node, "zh")).toBe("已绑定");
    expect(canvasNodeStatusLabel(null, "en")).toBe("not selected");

    const candidates = [
      { candidateId: "old", updatedAt: "2026-01-01T00:00:00Z", createdAt: "2026-01-01T00:00:00Z" },
      { candidateId: "new", updatedAt: "2026-07-01T00:00:00Z", createdAt: "2026-06-01T00:00:00Z" },
    ] as TeamWorkflowCandidate[];
    expect(latestWorkflowCandidate(candidates)?.candidateId).toBe("new");
  });

  it("detects completed source extraction and formats stage start feedback", () => {
    const extracted = {
      candidateType: "source_manifest",
      metadata: { sourceExtraction: { status: "extracted", pageAnchors: [{ page: 1 }] } },
    } as TeamWorkflowCandidate;
    expect(sourceCandidateHasCompletedExtraction(extracted)).toBe(true);

    const payload = {
      created: true,
      continued: false,
      stageRound: { stageType: "finding", roundNumber: 2 },
    } as Parameters<typeof researchStageStartFeedbackText>[0];
    expect(researchStageStartFeedbackText(payload, "zh", "资料寻找")).toContain("第 2 轮");
  });
});
