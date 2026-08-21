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

  it("renders question archives in the wide canvas region instead of the narrow inspector", () => {
    const source = readFileSync(resolve(root, "ResearchProcessWorkspace.tsx"), "utf8");
    expect(source).toContain('const archiveOpen = location.panel === "question"');
    expect(source).toContain('data-vui="research-question-archive-workspace"');
    expect(source).toContain("canvas={archiveOpen && inspectorPane");
    expect(source).toContain("inspector={!archiveOpen && inspectorPane");
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
