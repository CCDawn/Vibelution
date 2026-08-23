import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { canonicalChallengeCupWorkspaceRoute } from "../researchWorkspaceModel";

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
const canvasSource = readFileSync(resolve(import.meta.dirname, "ResearchWorkflowCanvasPane.tsx"), "utf8");
const workspaceStylesSource = readFileSync(resolve(import.meta.dirname, "ResearchProcessWorkspace.styles.ts"), "utf8");
const canvasStylesSource = readFileSync(resolve(import.meta.dirname, "ResearchWorkflowCanvasPane.styles.ts"), "utf8");
const locationSource = readFileSync(resolve(import.meta.dirname, "researchProcessLocation.ts"), "utf8");
const shellSource = readFileSync(resolve(import.meta.dirname, "../useTeamsWorkbenchShellPhase.tsx"), "utf8");

describe("researchWorkspaceRouteContract", () => {
  it("registers workflow view and mounts ResearchProcessWorkspace for challenge cup", () => {
    expect(modelSource).toContain('"workflow"');
    expect(modelSource).toContain("科研流程");
    expect(primarySource).toContain("ResearchProcessWorkspace");
    expect(primarySource).toContain('researchWorkspaceView === "workflow"');
    expect(primarySource).toContain("challengeCupResearchTeamSelected");
  });

  it("physically removes the retired research routes", () => {
    expect(routerSource).not.toContain("ResearchFlowCanvasRedirect");
    expect(routerSource).not.toContain('path: "research/flow-canvas"');
    expect(routerSource).not.toContain('path: "research"');
    expect(routerSource).not.toMatch(/import\("\.\.\/routes\/ResearchFlowCanvasRoute"\)/);
  });

  it("workspace uses single canvas navigation semantics", () => {
    expect(canvasSource).toContain("VWorkflowCanvas");
    expect(locationSource).toContain("researchView");
    expect(locationSource).toContain("workflow");
    expect(workspaceSource).not.toContain("ChallengeCupStageRail");
  });

  it("canonicalizes challenge legacy and overview URLs while preserving process focus", () => {
    const route = canonicalChallengeCupWorkspaceRoute(
      "research-team",
      new URLSearchParams(
        "team=research-team&team_id=legacy&researchView=overview&workflowId=legacy&challengeQuestion=SCI-096&challengeRun=stage1-sci-096-v3&nodeId=hypothesis_design&panel=question",
      ),
    );
    const params = new URLSearchParams(route.split("?")[1]);

    expect(params.get("teamId")).toBe("research-team");
    expect(params.get("researchView")).toBe("workflow");
    expect(params.get("workflowId")).toBe("challenge-cup-research");
    expect(params.get("questionId")).toBe("SCI-096");
    expect(params.get("runId")).toBe("stage1-sci-096-v3");
    expect(params.get("node")).toBe("hypothesis_design");
    expect(params.get("panel")).toBe("question");
    expect(params.has("team")).toBe(false);
    expect(params.has("team_id")).toBe(false);
    expect(params.has("challengeQuestion")).toBe(false);
    expect(params.has("challengeRun")).toBe(false);
  });

  it("canonicalizes the challenge URL after the selected team resolves", () => {
    expect(shellSource).toContain("canonicalChallengeCupWorkspaceRoute");
    expect(shellSource).toContain("navigate(canonicalHref, { replace: true })");
  });

  it("workspace uses VCanvasWorkbenchPage fill recipe like TeamsCanvasComposer", () => {
    expect(workspaceSource).toContain("VCanvasWorkbenchPage");
    expect(workspaceSource).toContain("shouldShowResearchProcessInspector");
    expect(workspaceSource).toContain("WORKBENCH_LAYOUT_IDS.researchFlow");
    expect(workspaceSource).toContain("hideHeader");
    expect(workspaceSource).toContain("research-process-workspace-host");
    expect(workspaceStylesSource).toContain("h-full min-h-0 w-full min-w-0 flex-1");
    expect(canvasSource).toContain('height="100%"');
    expect(canvasStylesSource).toContain("relative h-full min-h-0 w-full");
    expect(canvasStylesSource).not.toContain("!absolute !inset-0");
    expect(workspaceSource).not.toContain("height={440}");
    expect(workspaceSource).not.toContain("height={420}");
  });

  it("selection is URL node only and does not claim runtime write", () => {
    expect(workspaceSource).toContain("runtimeCurrentNodeIds");
    expect(workspaceSource).not.toContain("setRuntimeCurrent");
  });
});
