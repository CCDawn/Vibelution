import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const root = import.meta.dirname;

describe("research workflow workspace responsibility contract", () => {
  it("keeps every workspace responsibility in its owning file", () => {
    const requiredFiles = [
      "useResearchWorkflowWorkspace.ts",
      "useResearchWorkflowCatalog.ts",
      "researchExperimentSwitchModel.ts",
      "useResearchWorkflowCommands.ts",
      "useHypothesisFirstChain.ts",
      "hypothesisFirstCanvasRegion.ts",
      "HypothesisFirstNodeInspector.tsx",
      "ResearchWorkflowToolbar.tsx",
      "ResearchWorkflowCanvasPane.tsx",
      "ResearchRunTimeline.tsx",
      "ResearchTeamPanel.tsx",
      "ResearchProcessInspectorPane.tsx",
      "DefinitionNodeAgentSection.tsx",
      "NodeAgentSection.tsx",
      "NodeSessionSection.tsx",
      "NodeHandoffSection.tsx",
      "NodeCommandSection.tsx",
    ];

    for (const file of requiredFiles) {
      expect(existsSync(resolve(root, file)), `${file} must exist`).toBe(true);
    }
  });

  it("keeps ResearchProcessWorkspace as composition only", () => {
    const source = readFileSync(resolve(root, "ResearchProcessWorkspace.tsx"), "utf8");
    expect(source).not.toContain("useState(");
    expect(source).not.toContain("useEffect(");
    expect(source).not.toContain("fetchEffectiveAgentBindings");
    expect(source).not.toContain("listResearchWorkflowRuns");
    expect(source).not.toContain("fetchResearchWorkflowLaunchOptions");
    expect(source).not.toContain("executeNodeCommand");
    expect(source).toContain("useResearchWorkflowWorkspace");
    expect(source).toContain("ResearchProcessInspectorPane");
  });

  it("keeps live operations in the fixed inspector and opens the read-only archive in the wide canvas", () => {
    const source = readFileSync(resolve(root, "ResearchProcessWorkspace.tsx"), "utf8");
    expect(source).toContain('const archiveOpen = location.panel === "question"');
    expect(source).toContain("canvas={archiveOpen ? (");
    expect(source).toContain('data-vui="research-question-archive-canvas"');
    expect(source).toContain("inspector={archiveOpen ? null : (");
    expect(source).not.toContain("inspector={inspectorPane ? (");
    expect(source).toContain("<ResearchCurrentTaskInspector");
    expect(source).toContain("{inspectorPane}");
  });

  it("submits the workspace model offer unchanged from the sole formal primary action", () => {
    const source = readFileSync(resolve(root, "ResearchProcessWorkspace.tsx"), "utf8");
    expect(source).toContain("const formalPrimaryAction = workspaceModel.primaryAction");
    expect(source).toContain("commands.submitOffer(formalPrimaryAction.offer)");
    expect(source).toContain("if (commandBusy) return");
    expect(source).toContain("isDisabled={commandBusy}");
    expect(source).toContain("primaryActionOwnedByWorkspace={workspaceModel.source === \"formal_runtime\"}");
    expect(source).not.toContain("idempotencyKey: formalPrimaryAction");
    expect(source).not.toContain("expectedRunVersion: formalPrimaryAction");
  });

  it("opts into the approved tablet and compact drawer contract", () => {
    const source = readFileSync(resolve(root, "ResearchProcessWorkspace.tsx"), "utf8");
    const workspaceStyles = readFileSync(resolve(root, "ResearchProcessWorkspace.styles.ts"), "utf8");
    const toolbarStyles = readFileSync(resolve(root, "ResearchWorkflowToolbar.styles.ts"), "utf8");
    expect(source).toContain("responsive={{");
    expect(source).toContain('rail: { label: "研究阶段" }');
    // The URL-synced responsive inspector (459dbfb9a) intentionally expanded
    // the drawer block beyond a one-line literal; keep guarding the approved
    // label plus the URL-owned open wiring instead of the stale marker.
    expect(source).toContain("inspector: {");
    expect(source).toContain('label: "当前任务"');
    expect(source).toContain("open: location.inspectorOpen");
    expect(source).toContain("layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}");
    expect(source).toContain("toolbarClassName={styles.toolbar}");
    expect(workspaceStyles).toContain('toolbar: "!flex-nowrap overflow-hidden"');
    expect(workspaceStyles).toContain("max-w-full");
    expect(toolbarStyles).toContain("flex-col");
    expect(toolbarStyles).toContain("xl:flex-row");
    expect(toolbarStyles.match(/overflow-x-auto/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
  });

  it("mounts inspector panel leaves through the research workflow lazy pack", () => {
    const source = readFileSync(resolve(root, "ResearchProcessInspectorPane.tsx"), "utf8");
    expect(source).toContain('from "../teamLazyPanels"');
    expect(source).not.toContain('from "./ResearchRunLaunchPanel"');
    expect(source).not.toContain('from "./ChallengeMvpProgressPanel"');
    expect(source).not.toContain('from "./ResearchProcessNodeInspector"');
    expect(source).not.toContain('from "./ResearchAgentBindingPanel"');
    expect(source).not.toContain('from "../challenge-cup/ChallengeQuestionDetailPanel"');
  });
});
