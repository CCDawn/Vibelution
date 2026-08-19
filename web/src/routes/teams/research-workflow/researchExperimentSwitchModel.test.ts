import { describe, expect, it } from "vitest";

import type { ResearchWorkflowLaunchOption } from "../../../api/researchWorkflow";
import {
  buildExperimentChromeIdentity,
  buildExperimentSwitchOptions,
  formatHypothesisSummary,
  resolveExperimentSwitch,
} from "./researchExperimentSwitchModel";

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

describe("researchExperimentSwitchModel", () => {
  it("lists only questions that already have a checkpoint and restores that run+node", () => {
    const options = buildExperimentSwitchOptions({
      questions: [
        question({ questionId: "SCI-001", title: "Idle question", checkpoint: null }),
        question(),
        question({
          questionId: "SCI-003",
          title: "Is the Riemann hypothesis true?",
          checkpoint: {
            runId: "run-3",
            status: "running",
            currentNodeId: "protocol_design",
            currentNodeLabel: "协议设计",
            completedCount: 6,
            totalSteps: 16,
            resumable: true,
          },
        }),
      ],
    });

    expect(options.map((item) => item.questionId)).toEqual(["SCI-096", "SCI-003"]);
    expect(options[0].label).toBe("SCI-096 · 尚未选择假说");
    expect(options[0].label).not.toContain("知识包交接");
    expect(options[0].label).not.toContain("4/16");
    expect(options[0].label).not.toContain("等待确认");
    expect(options[0].label).not.toContain("run-96");
    expect(options[0].description).toContain("coding principles");

    expect(resolveExperimentSwitch(options, "sci-003")).toEqual({
      questionId: "SCI-003",
      runId: "run-3",
      node: "protocol_design",
      panel: "node",
    });
  });

  it("keeps the current run visible even if launch-options omitted it", () => {
    const options = buildExperimentSwitchOptions({
      questions: [question({ checkpoint: null })],
      current: {
        questionId: "SCI-091",
        title: "A current experiment",
        runId: "run-current",
        currentNodeId: "source_finding",
        selectedCandidateIds: ["hyp-a"],
      },
    });

    expect(options).toHaveLength(1);
    expect(options[0]).toMatchObject({
      questionId: "SCI-091",
      runId: "run-current",
      currentNodeId: "source_finding",
    });
    expect(options[0].label).toBe("SCI-091 · 假说 hyp-a");
    expect(options[0].label).not.toContain("资料寻找");
  });

  it("surfaces question identity and hypothesis count for chrome, not a run id", () => {
    expect(formatHypothesisSummary(null, "")).toBe("");
    expect(formatHypothesisSummary([], "SCI-096")).toBe("尚未选择假说");
    expect(formatHypothesisSummary(["hyp-a", "hyp-b"], "SCI-096")).toBe("假说 hyp-a、hyp-b");
    expect(formatHypothesisSummary(["a", "b", "c"], "SCI-096")).toBe("已选 3 个假说");

    const chrome = buildExperimentChromeIdentity({
      questionId: "sci-096",
      title: "What are the coding principles embedded in neuronal spike trains?",
      selectedCandidateIds: ["hyp-a"],
    });
    expect(chrome).toMatchObject({
      questionId: "SCI-096",
      hypothesisSummary: "假说 hyp-a",
    });
    expect(chrome?.title).not.toContain("run-");
  });
});
