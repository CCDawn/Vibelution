import { describe, expect, it } from "vitest";
import type { ResearchWorkflowLaunchOption } from "../../../api/researchWorkflow";
import { buildExperimentChromeIdentity, buildExperimentSwitchOptions, resolveExperimentSwitch } from "./researchExperimentSwitchModel";

function question(overrides: Partial<ResearchWorkflowLaunchOption> = {}): ResearchWorkflowLaunchOption {
  return {
    questionId: "SCI-096",
    title: "What are the coding principles embedded in neuronal spike trains?",
    scope: "neuroscience",
    domain: "neuroscience",
    catalogId: "science-125-questions-2021",
    reviewRunId: "",
    artifactSha256: "",
    source: "catalog",
    launchable: true,
    checkpoint: {
      runId: "run-96",
      status: "waiting_human",
      currentNodeId: "knowledge_handoff",
      currentNodeLabel: "知识包交接",
      completedCount: 4,
      totalSteps: 16,
      resumable: true,
    },
    ...overrides,
  };
}

describe("research question navigation", () => {
  it("lists all catalog questions, including those without a formal run", () => {
    const options = buildExperimentSwitchOptions({ questions: Array.from({length: 125}, (_, i) => question({questionId: `SCI-${String(i + 1).padStart(3, "0")}`, checkpoint: i % 2 ? question().checkpoint : null})) });
    expect(options).toHaveLength(125);
    expect(options[0].questionId).toBe("SCI-001");
    expect(options[0].description).toContain("尚无正式运行记录");
    expect(options[1].description).toContain("知识包交接");
  });
  it("uses identity, never candidate absence or review state, as the picker label", () => {
    const options = buildExperimentSwitchOptions({ questions: [question({title: "研究题名"})] });
    expect(options[0].label).toBe("SCI-096 · 研究题名");
    expect(buildExperimentChromeIdentity({questionId: "sci-096", title: "研究题名"})).toEqual({questionId: "SCI-096", title: "研究题名"});
    expect(buildExperimentChromeIdentity({questionId: ""})).toBeNull();
  });
  it("navigates fresh questions to the existing launch panel without executing a run", () => {
    const options = buildExperimentSwitchOptions({questions: [question({checkpoint: null})]});
    expect(resolveExperimentSwitch(options, "sci-096")).toEqual({questionId: "SCI-096", runId: "", node: null, panel: "launch"});
    expect(resolveExperimentSwitch(options, "SCI-999")).toBeNull();
  });
  it("restores the exact run and selected node for an existing question", () => {
    const options = buildExperimentSwitchOptions({questions: [question()]});
    expect(resolveExperimentSwitch(options, "sci-096")).toEqual({questionId: "SCI-096", runId: "run-96", node: "knowledge_handoff", panel: "node"});
    expect(resolveExperimentSwitch(options, "SCI-096", "hf_generation")?.node).toBe("hf_generation");
  });
  it("keeps cancelled checkpoints navigable with their actual status", () => {
    const options = buildExperimentSwitchOptions({questions: [question({checkpoint: {...question().checkpoint!, status: "cancelled"}})]});
    expect(options[0].description).toContain("已取消");
    expect(resolveExperimentSwitch(options, "SCI-096")?.runId).toBe("run-96");
  });
  it("keeps the current question first without hiding other catalog questions", () => {
    const options = buildExperimentSwitchOptions({questions: [question(), question({questionId: "SCI-001", checkpoint: null})], current: {questionId: "SCI-003", title: "当前题目", runId: "run-current", currentNodeId: "source_finding"}});
    expect(options.map(item => item.questionId)).toEqual(["SCI-003", "SCI-096", "SCI-001"]);
    expect(options[0].label).toBe("SCI-003 · 当前题目");
    expect(resolveExperimentSwitch(options, "SCI-003")?.runId).toBe("run-current");
  });
});
