import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const routerSource = readFileSync(resolve(import.meta.dirname, "../../../app/router.tsx"), "utf8");
const modelSource = readFileSync(
  resolve(import.meta.dirname, "../researchWorkspaceModel.ts"),
  "utf8",
);
const primarySource = readFileSync(
  resolve(import.meta.dirname, "../teamResearchPrimarySurfaceRenderers.tsx"),
  "utf8",
);
const workspaceSource = readFileSync(
  resolve(import.meta.dirname, "ResearchProcessWorkspace.tsx"),
  "utf8",
);

describe("researchWorkspaceRouteContract", () => {
  it("registers workflow view and mounts ResearchProcessWorkspace for challenge cup", () => {
    expect(modelSource).toContain('"workflow"');
    expect(modelSource).toContain("科研流程");
    expect(primarySource).toContain("ResearchProcessWorkspace");
    expect(primarySource).toContain('researchWorkspaceView === "workflow"');
    expect(primarySource).toContain("challengeCupResearchTeamSelected");
  });

  it("flow-canvas is redirect only — no lazy ResearchFlowCanvasRoute page", () => {
    expect(routerSource).toContain("ResearchFlowCanvasRedirect");
    expect(routerSource).toContain('path: "research/flow-canvas"');
    expect(routerSource).not.toMatch(/import\("\.\.\/routes\/ResearchFlowCanvasRoute"\)/);
  });

  it("workspace uses single canvas navigation semantics", () => {
    expect(workspaceSource).toContain("VWorkflowCanvas");
    expect(workspaceSource).toContain("researchView");
    expect(workspaceSource).toContain("workflow");
    expect(workspaceSource).not.toContain("ChallengeCupStageRail");
  });

  it("workspace uses VCanvasWorkbenchPage fill recipe like TeamsCanvasComposer", () => {
    expect(workspaceSource).toContain("VCanvasWorkbenchPage");
    expect(workspaceSource).toContain("WORKBENCH_LAYOUT_IDS.researchFlow");
    expect(workspaceSource).toContain("hideHeader");
    expect(workspaceSource).toContain("research-process-workspace-host");
    expect(workspaceSource).toContain("h-full min-h-0 w-full min-w-0 flex-1");
    expect(workspaceSource).toContain('height="100%"');
    expect(workspaceSource).toContain("!absolute !inset-0");
    expect(workspaceSource).not.toContain("height={440}");
    expect(workspaceSource).not.toContain("height={420}");
  });

  it("selection is URL node only and does not claim runtime write", () => {
    expect(workspaceSource).toContain("Selection is UI-only");
    expect(workspaceSource).toContain("runtimeCurrentNodeIds");
    expect(workspaceSource).not.toContain("setRuntimeCurrent");
  });
});
