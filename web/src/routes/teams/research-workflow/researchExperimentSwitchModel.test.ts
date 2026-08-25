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
  it("keeps all 125 catalog questions in the unified selector", () => {
    const questions = Array.from({ length: 125 }, (_, index) => {
      const questionId = `SCI-${String(index + 1).padStart(3, "0")}`;
      return question({
        questionId,
        title: `Question ${index + 1}`,
        checkpoint: index % 2 === 0 ? null : {
          runId: `run-${index + 1}`,
          status: "running",
          currentNodeId: "protocol_design",
          currentNodeLabel: "协议设计",
          completedCount: 6,
          totalSteps: 16,
          resumable: true,
        },
      });
    });

    const options = buildExperimentSwitchOptions({ questions });

    expect(options).toHaveLength(125);
    expect(options[0].questionId).toBe("SCI-001");
    expect(options[0].description).toContain("无 checkpoint");
    expect(options[1].questionId).toBe("SCI-002");
    expect(options[1].description).toContain("运行中");
    expect(options[124].questionId).toBe("SCI-125");
  });

  it("lists every supplied catalog question including checkpoint-less entries", () => {
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

    expect(options.map((item) => item.questionId)).toEqual(["SCI-001", "SCI-096", "SCI-003"]);
    expect(options[1].label).toBe("SCI-096 · 假说待生成");
    expect(options[1].label).not.toContain("知识包交接");
    expect(options[1].label).not.toContain("4/16");
    expect(options[1].label).not.toContain("等待确认");
    expect(options[1].label).not.toContain("run-96");
  });

  it("describes checkpoint availability, status and progress for every option", () => {
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

    const checkpointless = options.find((item) => item.questionId === "SCI-001");
    expect(checkpointless?.description).toContain("Idle question");
    expect(checkpointless?.description).toContain("无 checkpoint");
    expect(checkpointless?.runId).toBeUndefined();
    expect(checkpointless?.currentNodeId).toBeUndefined();

    const checkpointed = options.find((item) => item.questionId === "SCI-096");
    expect(checkpointed?.description).toContain("coding principles");
    expect(checkpointed?.description).toContain("知识包交接");
    expect(checkpointed?.description).toContain("4/16");
    expect(checkpointed?.description).toContain("等待确认");
    expect(checkpointed?.runId).toBe("run-96");

    const running = options.find((item) => item.questionId === "SCI-003");
    expect(running?.description).toContain("协议设计");
    expect(running?.description).toContain("6/16");
    expect(running?.description).toContain("运行中");
  });

  it("keeps cancelled checkpoints visible and restores their run+node", () => {
    const options = buildExperimentSwitchOptions({
      questions: [
        question(),
        question({
          questionId: "SCI-004",
          checkpoint: {
            runId: "run-4",
            status: "cancelled",
            currentNodeId: "source_finding",
            currentNodeLabel: "资料寻找",
            completedCount: 0,
            totalSteps: 16,
            resumable: false,
          },
        }),
      ],
    });

    expect(options.map((item) => item.questionId)).toEqual(["SCI-096", "SCI-004"]);
    const cancelled = options.find((item) => item.questionId === "SCI-004");
    expect(cancelled?.description).toContain("资料寻找");
    expect(cancelled?.description).toContain("已取消");
    expect(resolveExperimentSwitch(options, "SCI-004")).toEqual({
      questionId: "SCI-004",
      runId: "run-4",
      node: "source_finding",
      panel: "node",
    });
  });

  it("resolves a checkpoint entry to a restore patch with the focused node", () => {
    const options = buildExperimentSwitchOptions({
      questions: [question()],
    });

    expect(resolveExperimentSwitch(options, "sci-096")).toEqual({
      questionId: "SCI-096",
      runId: "run-96",
      node: "knowledge_handoff",
      panel: "node",
    });
    expect(resolveExperimentSwitch(options, "sci-096", "hf_generation")).toEqual({
      questionId: "SCI-096",
      runId: "run-96",
      node: "hf_generation",
      panel: "node",
    });
  });

  it("resolves a checkpoint-less question to a no-run launch patch", () => {
    const options = buildExperimentSwitchOptions({
      questions: [
        question(),
        question({ questionId: "SCI-005", title: "Fresh question", checkpoint: null }),
      ],
    });

    expect(resolveExperimentSwitch(options, "sci-005")).toEqual({
      questionId: "SCI-005",
      runId: "",
      node: null,
      panel: "launch",
    });
  });

  it("returns null for unknown question ids", () => {
    const options = buildExperimentSwitchOptions({ questions: [question()] });
    expect(resolveExperimentSwitch(options, "SCI-999")).toBeNull();
  });

  it("sorts the current question first and keeps catalog order stable otherwise", () => {
    const options = buildExperimentSwitchOptions({
      questions: [
        question({ questionId: "SCI-001", title: "Alpha", checkpoint: null }),
        question(),
        question({ questionId: "SCI-002", title: "Beta", checkpoint: null }),
        question({ questionId: "SCI-003", title: "Gamma", checkpoint: null }),
      ],
      current: {
        questionId: "sci-003",
        title: "Gamma",
        runId: "",
        selectedCandidateIds: ["hyp-a"],
      },
    });

    expect(options.map((item) => item.questionId)).toEqual(["SCI-003", "SCI-001", "SCI-096", "SCI-002"]);
    expect(options[0].label).toBe("SCI-003 · 1 条假说待评审");
  });

  it("uses the current chain state for the selected question label", () => {
    const converged = buildExperimentSwitchOptions({
      questions: [question({ questionId: "SCI-004", checkpoint: null })],
      current: {
        questionId: "SCI-004",
        runId: "run-4",
        selectedCandidateIds: ["hyp-a", "hyp-b", "hyp-c", "hyp-d", "hyp-e"],
        chain: { hypothesisConverged: true, meetingCount: 1 },
      },
    });

    expect(converged[0].label).toBe("SCI-004 · 5 条假说已收敛");

    const reviewing = buildExperimentSwitchOptions({
      questions: [question({ questionId: "SCI-004", checkpoint: null })],
      current: {
        questionId: "SCI-004",
        runId: "run-4",
        selectedCandidateIds: ["hyp-a", "hyp-b"],
        chain: { meetingCount: 2 },
      },
    });

    expect(reviewing[0].label).toBe("SCI-004 · 2 条假说评审中 · 第 1 轮");

    const secondRound = buildExperimentSwitchOptions({
      questions: [question({ questionId: "SCI-004", checkpoint: null })],
      current: {
        questionId: "SCI-004",
        runId: "run-4",
        selectedCandidateIds: ["hyp-a", "hyp-b"],
        chain: { meetingCount: 3 },
      },
    });

    expect(secondRound[0].label).toBe("SCI-004 · 2 条假说评审中 · 第 2 轮");
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

    expect(options).toHaveLength(2);
    expect(options[0]).toMatchObject({
      questionId: "SCI-091",
      runId: "run-current",
      currentNodeId: "source_finding",
    });
    expect(options[0].label).toBe("SCI-091 · 1 条假说待评审");
    expect(options[0].label).not.toContain("资料寻找");
  });

  it("surfaces question identity and hypothesis count for chrome, not a run id", () => {
    expect(formatHypothesisSummary(null, "")).toBe("");
    expect(formatHypothesisSummary([], "SCI-096")).toBe("假说待生成");
    expect(formatHypothesisSummary(["hyp-a", "hyp-b"], "SCI-096")).toBe("2 条假说待评审");
    expect(formatHypothesisSummary(["a", "b", "c"], "SCI-096")).toBe("3 条假说待评审");

    const chrome = buildExperimentChromeIdentity({
      questionId: "sci-096",
      title: "What are the coding principles embedded in neuronal spike trains?",
      selectedCandidateIds: ["hyp-a"],
    });
    expect(chrome).toMatchObject({
      questionId: "SCI-096",
      hypothesisSummary: "1 条假说待评审",
    });
    expect(chrome?.title).not.toContain("run-");
  });

  it("never renders raw candidate ids, even for long or duplicate ids", () => {
    const longId = `candidate-${"a".repeat(200)}`;
    expect(formatHypothesisSummary([longId], "SCI-096")).toBe("1 条假说待评审");
    expect(formatHypothesisSummary(["hyp-a", longId], "SCI-096")).toBe("2 条假说待评审");
    expect(formatHypothesisSummary(["hyp-a", "hyp-a"], "SCI-096")).toBe("2 条假说待评审");

    const chrome = buildExperimentChromeIdentity({
      questionId: "sci-096",
      title: "What are the coding principles embedded in neuronal spike trains?",
      selectedCandidateIds: [longId],
    });
    expect(chrome?.hypothesisSummary).toBe("1 条假说待评审");
    expect(chrome?.hypothesisSummary).not.toContain("candidate-");

    const options = buildExperimentSwitchOptions({
      questions: [question()],
      current: {
        questionId: "SCI-096",
        title: "What are the coding principles embedded in neuronal spike trains?",
        runId: "",
        selectedCandidateIds: [longId],
      },
    });
    expect(options[0].label).toBe("SCI-096 · 1 条假说待评审");
    expect(options[0].label).not.toContain("candidate-");
  });
});
