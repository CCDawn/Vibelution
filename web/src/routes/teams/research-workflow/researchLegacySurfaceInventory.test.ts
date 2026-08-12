import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const webSrc = resolve(import.meta.dirname, "../../..");
const routesRoot = resolve(webSrc, "routes");
const routerSource = readFileSync(resolve(webSrc, "app/router.tsx"), "utf8");
const runHookSource = readFileSync(
  resolve(routesRoot, "teams/research-workflow/useResearchWorkflowRun.ts"),
  "utf8",
);

describe("research workflow legacy cleanup", () => {
  it("does not expose the retired research routes", () => {
    expect(routerSource).not.toContain('path: "research"');
    expect(routerSource).not.toContain('path: "research/flow-canvas"');
    expect(routerSource).not.toContain("ResearchFlowCanvasRedirect");
  });

  it.each([
    "ResearchRoute.tsx",
    "ResearchRoute.styles.ts",
    "ResearchRoute.layout.test.ts",
    "ResearchFlowCanvasRoute.tsx",
    "ResearchFlowCanvasRoute.styles.ts",
    "teams/research-workflow/researchLegacyRouteResolver.ts",
    "teams/research-workflow/TeamsLegacyResearchBoundary.tsx",
    "teams/research-workflow/researchWorkflowPollingController.ts",
    "teams/research-workflow/IterationDecisionPanel.tsx",
    "teams/challenge-cup/ChallengeCupOperationsWorkspace.tsx",
    "teams/challenge-cup/ChallengeCupStageRail.tsx",
  ])("physically removes %s", (relativePath) => {
    expect(existsSync(resolve(routesRoot, relativePath))).toBe(false);
  });

  it("keeps the single workflow workspace and exact session anchors", () => {
    expect(existsSync(resolve(routesRoot, "teams/research-workflow/ResearchProcessWorkspace.tsx"))).toBe(true);
    const anchor = readFileSync(
      resolve(routesRoot, "teams/research-workflow/chatSessionAnchor.ts"),
      "utf8",
    );
    expect(anchor).toContain("focusTask");
    expect(anchor).toContain("focusTurn");
    expect(anchor).toContain('params.set("teamId"');
    expect(anchor).not.toContain('params.set("team"');
  });

  it("ships formal T7 snapshot/event/command hooks", () => {
    expect(existsSync(resolve(routesRoot, "teams/research-workflow/useResearchWorkflowSnapshot.ts"))).toBe(true);
    expect(existsSync(resolve(routesRoot, "teams/research-workflow/useResearchWorkflowEventStream.ts"))).toBe(true);
    expect(existsSync(resolve(routesRoot, "teams/research-workflow/useResearchWorkflowCommand.ts"))).toBe(true);
    expect(existsSync(resolve(routesRoot, "teams/research-workflow/useResearchWorkflowEventReplay.ts"))).toBe(true);
    expect(existsSync(resolve(webSrc, "api/research-workflow/commands.ts"))).toBe(true);
  });

  it("hard-switches run read path away from legacy canvas fetch", () => {
    expect(runHookSource).toContain("useResearchWorkflowSnapshot");
    expect(runHookSource).toContain("useResearchWorkflowEventStream");
    expect(runHookSource).toContain("useResearchWorkflowEventReplay");
    expect(runHookSource).not.toContain("fetchResearchWorkflowCanvas");
    expect(runHookSource).not.toContain("fetchResearchWorkflowRun");
  });

  it("listens to formal SSE event types instead of legacy names", () => {
    const sseTypes = readFileSync(
      resolve(routesRoot, "teams/research-workflow/researchWorkflowSseEventTypes.ts"),
      "utf8",
    );
    expect(sseTypes).toContain("run_created");
    expect(sseTypes).toContain("node_starting");
    expect(sseTypes).not.toContain("run.queued");
    expect(sseTypes).not.toContain("NodeRunTransitioned");
  });

  it("hard-switches inspector reads and commands onto formal NodeDetail/Offer", () => {
    const inspector = readFileSync(
      resolve(routesRoot, "teams/research-workflow/ResearchProcessNodeInspector.tsx"),
      "utf8",
    );
    const nodeDetail = readFileSync(
      resolve(routesRoot, "teams/research-workflow/useNodeDetailState.ts"),
      "utf8",
    );
    const commands = readFileSync(
      resolve(routesRoot, "teams/research-workflow/useResearchWorkflowCommands.ts"),
      "utf8",
    );
    const commandSection = readFileSync(
      resolve(routesRoot, "teams/research-workflow/NodeCommandSection.tsx"),
      "utf8",
    );
    expect(inspector).toContain("detail.commandOffers");
    expect(inspector).toContain("onOffer");
    expect(inspector).not.toContain("onCommand");
    expect(nodeDetail).toContain("api/research-workflow/runs");
    expect(commands).toContain("submitFormalOffer");
    expect(commands).not.toContain("executeNodeCommand");
    expect(commandSection).not.toContain("EvidenceRemediationDialog");
  });
});
