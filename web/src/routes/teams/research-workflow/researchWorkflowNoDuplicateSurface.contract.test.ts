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
    expect(workspaceSource).not.toContain("ChallengeCupStageRail");
    expect(workspaceSource).not.toContain("ResearchStageNav");
    expect(workspaceSource).not.toContain("TeamKnowledgeCollectionCompletionFlowPanel");
  });

  it("selection updates URL node without claiming runtime authority in comments/code", () => {
    expect(workspaceSource).toContain("Selection is UI-only");
    expect(workspaceSource).toContain("runtimeCurrentNodeIds");
    expect(workspaceSource).toContain("onSelectNode");
  });
});
