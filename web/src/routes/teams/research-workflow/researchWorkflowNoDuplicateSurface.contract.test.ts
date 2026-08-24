import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const workspaceSource = readFileSync(
  resolve(import.meta.dirname, "ResearchProcessWorkspace.tsx"),
  "utf8",
);
const toolbarSource = readFileSync(resolve(import.meta.dirname, "ResearchWorkflowToolbar.tsx"), "utf8");
const canvasSource = readFileSync(resolve(import.meta.dirname, "ResearchWorkflowCanvasPane.tsx"), "utf8");
const inspectorSource = readFileSync(resolve(import.meta.dirname, "ResearchProcessInspectorPane.tsx"), "utf8");
const commandSource = readFileSync(resolve(import.meta.dirname, "useResearchWorkflowCommands.ts"), "utf8");

const navigationSource = readFileSync(
  resolve(import.meta.dirname, "../createTeamsResearchNavigation.ts"),
  "utf8",
);
const shellSource = readFileSync(
  resolve(import.meta.dirname, "../useTeamsWorkbenchShellPhase.tsx"),
  "utf8",
);
const primarySource = readFileSync(
  resolve(import.meta.dirname, "../teamResearchPrimarySurfaceRenderers.tsx"),
  "utf8",
);


describe("researchWorkflowNoDuplicateSurface", () => {
  it("workspace uses VWorkflowCanvas and does not mount stage rail", () => {
    expect(canvasSource).toContain("VWorkflowCanvas");
    expect(canvasSource).toContain('layoutMode="serpentine"');
    expect(canvasSource).toContain("showMiniMap");
    expect(canvasSource).toContain("showLegend={false}");
    expect(inspectorSource).toContain("ResearchProcessNodeInspector");
    expect(workspaceSource).toContain("useResearchWorkflowRun");
    expect(workspaceSource).not.toContain("ResearchProcessRail");
    expect(workspaceSource).not.toContain('sidebar: { id: "rail"');
    expect(workspaceSource).not.toContain("railClassName=");
    expect(workspaceSource).toContain('aside: { id: "inspector"');
    expect(workspaceSource).not.toContain("ChallengeCupStageRail");
    expect(workspaceSource).not.toContain("ResearchStageNav");
    expect(workspaceSource).not.toContain("TeamKnowledgeCollectionCompletionFlowPanel");
    expect(workspaceSource).not.toContain("ChallengeCupOperationsWorkspace");
  });

  it("autofocuses the current HITL task from the process workspace", () => {
    expect(workspaceSource).toContain("useResearchProcessAutofocus");
    expect(workspaceSource).toContain("atCurrentTask");
  });

  it("keeps challenge-cup primary column on ResearchProcessWorkspace", () => {
    expect(primarySource).toContain("ResearchProcessWorkspace");
    expect(primarySource).toContain("challengeCupResearchTeamSelected && researchWorkspaceView === \"overview\"");
    expect(primarySource).toContain("renderResearchProcessWorkflowSurface");
    expect(primarySource).toContain("toolbarLeading");
    expect(workspaceSource).toContain("leading={toolbarLeading}");
    expect(workspaceSource).toContain("toolbarClassName={styles.toolbar}");
  });

  it("keeps workflow mutations and current-task navigation out of the toolbar", () => {
    expect(toolbarSource).not.toContain("选择题目开始研究");
    expect(toolbarSource).not.toContain("Choose a question to start research");
    expect(toolbarSource).not.toContain("新建运行");
    expect(toolbarSource).not.toContain("New run");
    expect(toolbarSource).not.toContain('variant="primary"');
    expect(toolbarSource).not.toContain('onOpenPanel("launch")');
    expect(toolbarSource).toContain('variant="secondary"');
    expect(toolbarSource).not.toContain('"定位当前任务"');
    expect(workspaceSource).toContain("currentTaskNodeId={semanticCurrentTaskNodeId}");
    expect(canvasSource).toContain("resolveCanvasCurrentNodeIds");
  });

  it("research teams never land on org canvas or challenge launcher", () => {
    expect(navigationSource).toContain("isResearchWorkflowTeam(team)");
    expect(navigationSource).toContain("setTeamShellMode(\"board\")");
    expect(shellSource).toContain("teamShellMode === \"canvas\" && !researchWorkflowTeamSelected");
    expect(shellSource).toContain("challengeCupResearchTeamSelected || isProcessWorkflowView");
  });

  it("selection updates URL node without claiming runtime authority in comments/code", () => {
    expect(workspaceSource).toContain("runtimeCurrentNodeIds");
    expect(workspaceSource).toContain("selectNode");
  });

  it("has no fake-command fallback error (commands are backend-declared)", () => {
    expect(commandSource).not.toContain("WIRED_COMMANDS");
    expect(commandSource).toContain("submitFormalOffer");
    expect(commandSource).toContain("submitOffer");
    expect(commandSource).not.toContain("executeNodeCommand");
    expect(commandSource).not.toContain("runInspectorCommand");
  });
});
