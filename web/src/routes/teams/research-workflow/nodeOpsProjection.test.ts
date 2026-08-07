import { describe, expect, it } from "vitest";

import { projectNodeOps } from "./nodeOpsProjection";

describe("nodeOpsProjection", () => {
  it("blocks hypothesis without accepted knowledge package", () => {
    const proj = projectNodeOps({
      nodeId: "hypothesis_design",
      run: {
        runId: "r1",
        workflowId: "challenge-cup-research",
        workflowVersionId: "wv",
        status: "running",
        langGraph: { knowledgePackageAccepted: false, completedNodeIds: [] },
      },
    });
    expect(proj?.blockedReason).toMatch(/Knowledge Package/);
  });

  it("blocks controlled_run without protocol and smoke", () => {
    const proj = projectNodeOps({
      nodeId: "controlled_run",
      run: {
        runId: "r1",
        workflowId: "challenge-cup-research",
        workflowVersionId: "wv",
        status: "running",
        langGraph: {
          knowledgePackageAccepted: true,
          frozenProtocolAccepted: false,
          smokeAccepted: false,
        },
      },
    });
    expect(proj?.blockedReason).toMatch(/Frozen Protocol/);
  });

  it("marks runtime current node", () => {
    const proj = projectNodeOps({
      nodeId: "knowledge_handoff",
      runtimeCurrentNodeIds: ["knowledge_handoff"],
      run: {
        runId: "r1",
        workflowId: "challenge-cup-research",
        workflowVersionId: "wv",
        status: "waiting_human",
      },
    });
    expect(proj?.facts.some((f) => f.value === "运行当前")).toBe(true);
  });
});
