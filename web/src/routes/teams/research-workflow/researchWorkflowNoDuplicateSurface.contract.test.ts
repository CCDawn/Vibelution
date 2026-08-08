import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const workspaceSource = readFileSync(
  resolve(import.meta.dirname, "ResearchProcessWorkspace.tsx"),
  "utf8",
);

describe("researchWorkflowNoDuplicateSurface", () => {
  it("workspace uses VWorkflowCanvas and does not mount stage rail", () => {
    expect(workspaceSource).toContain("VWorkflowCanvas");
    expect(workspaceSource).toContain("ResearchProcessNodeInspector");
    expect(workspaceSource).toContain("useResearchWorkflowRun");
    expect(workspaceSource).not.toContain("ChallengeCupStageRail");
    expect(workspaceSource).not.toContain("ResearchStageNav");
    expect(workspaceSource).not.toContain("TeamKnowledgeCollectionCompletionFlowPanel");
    expect(workspaceSource).not.toContain("ChallengeCupOperationsWorkspace");
  });

  it("selection updates URL node without claiming runtime authority in comments/code", () => {
    expect(workspaceSource).toContain("Selection is UI-only");
    expect(workspaceSource).toContain("runtimeCurrentNodeIds");
    expect(workspaceSource).toContain("onSelectNode");
    expect(workspaceSource).not.toContain("canonical");
    expect(workspaceSource).not.toContain("不维护第二份");
  });

  it("has no fake-command fallback error (inspector renders only wired commands)", () => {
    expect(workspaceSource).not.toContain("尚未接入业务服务");
    expect(workspaceSource).toContain("WIRED_COMMANDS");
  });
});
