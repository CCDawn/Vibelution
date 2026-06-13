import { describe, expect, it } from "vitest";

import { EvolutionRun } from "../api/types";
import { buildSupervisedRunRecordDisplay } from "./supervisedRunRecordLabel";

const labels = {
  statusLabel: (status: string) => status,
  decisionLabel: (decision: string) => {
    if (decision === "INCONCLUSIVE") {
      return "评测无结论";
    }
    return decision;
  },
};

function run(overrides: Partial<EvolutionRun>): EvolutionRun {
  return {
    id: "supervised_20260531_163627",
    score: 0,
    status: "inconclusive",
    summary: "这轮监督评测没有形成可用对比证据，建议修正评测或复跑。",
    diagnosis: "",
    decision: "INCONCLUSIVE",
    endedAt: "",
    bundleName: "terminal_bench_core_v1",
    baselineScore: 0,
    candidateScore: 0,
    deltaScore: 0,
    riskLevel: "pending_review",
    riskReasons: [],
    proposalStatus: "missing",
    runtimeEffect: "not_applied",
    agentConsumption: "advisory",
    availableActions: [],
    nextAction: "需观察",
    sourceDecisionPath: "",
    sourceProposalPath: "",
    activeAdvisoryCount: 0,
    caseDiagnostics: [],
    canDelete: true,
    deleteBlockReason: "",
    runSemantics: {
      runStatus: "inconclusive",
      runStatusLabel: "评测完成 · 无结论",
      stage: "demo_bundle",
      stageLabel: "demo_bundle",
      diagnosis: "",
      nextAction: "需观察",
    },
    outcomeSemantics: {
      decision: "INCONCLUSIVE",
      decisionLabel: "评测无结论",
      proposalStatus: "missing",
      proposalStatusLabel: "提案缺失",
      runtimeEffect: "not_applied",
      runtimeEffectLabel: "未应用",
      runtimeExplanation: "",
      isRuntimeApplied: false,
    },
    actionStates: {},
    ...overrides,
  };
}

describe("buildSupervisedRunRecordDisplay", () => {
  it("turns timestamp-like run ids into readable run titles", () => {
    const display = buildSupervisedRunRecordDisplay(run({}), "zh", labels);

    expect(display.title).toContain("05/31");
    expect(display.title).toContain("16:36");
    expect(display.title).toContain("terminal_bench_core_v1");
    expect(display.subtitle).toBe("评测无结论 · baseline 0 / candidate 0");
    expect(display.idLabel).toBe("supervised_20260531_163627");
  });

  it("prefers endedAt when the record has a real timestamp", () => {
    const display = buildSupervisedRunRecordDisplay(
      run({
        id: "supervised_20260531_163627",
        endedAt: "2026-06-01T09:08:00",
      }),
      "zh",
      labels,
    );

    expect(display.title).toContain("06/01");
    expect(display.title).toContain("09:08");
  });

  it("falls back to a clear unknown-time label instead of showing opaque ids as the title", () => {
    const display = buildSupervisedRunRecordDisplay(
      run({
        id: "supervised_latest",
        endedAt: "",
        bundleName: "",
      }),
      "zh",
      labels,
    );

    expect(display.title).toContain("时间未知");
    expect(display.idLabel).toBe("supervised_latest");
  });

  it("renders REJECT as a governance non-adoption label instead of a failure label", () => {
    const display = buildSupervisedRunRecordDisplay(
      run({
        decision: "REJECT",
        baselineScore: 100,
        candidateScore: 100,
      }),
      "zh",
      labels,
    );

    expect(display.subtitle).toBe("候选未采纳 · baseline 100 / candidate 100");
    expect(display.subtitle).not.toContain("失败");
  });
});
