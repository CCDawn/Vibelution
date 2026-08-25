import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  canonicalChallengeCupWorkspaceRoute,
  canonicalChallengeCupWorkspaceRouteForEffectiveTeam,
  isChallengeCupWorkspaceCanonicalizationEligible,
  teamWorkspaceRoute,
} from "../researchWorkspaceModel";

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
    expect(shellSource).toContain("canonicalChallengeCupWorkspaceRouteForEffectiveTeam");
    expect(shellSource).toContain("navigate(canonicalHref, { replace: true })");
  });

  it("preserves focus only when the URL explicitly names the effective team", () => {
    const focus = "questionId=SCI-096&runId=run-a&node=hypothesis_design&panel=question";
    const sameTeam = canonicalChallengeCupWorkspaceRouteForEffectiveTeam(
      "research-team-a",
      new URLSearchParams(`team=research-team-a&researchView=overview&${focus}`),
    );
    const otherTeam = canonicalChallengeCupWorkspaceRouteForEffectiveTeam(
      "research-team-b",
      new URLSearchParams(`teamId=research-team-a&researchView=workflow&${focus}`),
    );
    const missingTeam = canonicalChallengeCupWorkspaceRouteForEffectiveTeam(
      "research-team-b",
      new URLSearchParams(`researchView=overview&${focus}`),
    );

    expect(sameTeam).toBe(canonicalChallengeCupWorkspaceRoute(
      "research-team-a",
      new URLSearchParams(`team=research-team-a&researchView=overview&${focus}`),
    ));
    expect(otherTeam).toBe(teamWorkspaceRoute("research-team-b"));
    expect(missingTeam).toBe(teamWorkspaceRoute("research-team-b"));
  });

  it.each([
    ["experiment", "node", "hypothesis_design"],
    ["iteration", "node", "controlled_run"],
    ["knowledge_collection", "node", "source_finding"],
    ["source_collection", "node", "source_finding"],
    ["canvas", "panel", "agents"],
  ])("maps retired %s links onto the single workflow workspace", (view, key, value) => {
    const route = canonicalChallengeCupWorkspaceRouteForEffectiveTeam(
      "research-team-a",
      new URLSearchParams(`teamId=research-team-a&researchView=${view}`),
    );
    const params = new URLSearchParams(route.split("?")[1]);

    expect(params.get("researchView")).toBe("workflow");
    expect(params.get(key)).toBe(value);
  });

  it.each(["coordination", "ingestion", "graph", "candidates", "discussion"])(
    "retires %s without reviving an independent surface",
    (view) => {
      const route = canonicalChallengeCupWorkspaceRouteForEffectiveTeam(
        "research-team-a",
        new URLSearchParams(`teamId=research-team-a&researchView=${view}`),
      );
      expect(new URLSearchParams(route.split("?")[1]).get("researchView")).toBe("workflow");
    },
  );

  it("does not carry a retired view mapping or focus across teams", () => {
    const route = canonicalChallengeCupWorkspaceRouteForEffectiveTeam(
      "research-team-b",
      new URLSearchParams(
        "teamId=research-team-a&researchView=experiment&questionId=SCI-096&runId=run-a&node=source_finding&panel=question",
      ),
    );

    expect(route).toBe(teamWorkspaceRoute("research-team-b"));
  });

  it("treats canonical and retired challenge views as canonicalization inputs", () => {
    expect(isChallengeCupWorkspaceCanonicalizationEligible("overview")).toBe(true);
    expect(isChallengeCupWorkspaceCanonicalizationEligible("workflow")).toBe(true);
    expect(isChallengeCupWorkspaceCanonicalizationEligible("discussion")).toBe(true);
    expect(isChallengeCupWorkspaceCanonicalizationEligible("coordination")).toBe(true);
    expect(isChallengeCupWorkspaceCanonicalizationEligible("not-a-view")).toBe(false);
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
