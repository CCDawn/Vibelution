import { describe, expect, it } from "vitest";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import {
  deriveChallengeQuestionStageProjection,
  stageOneStatusCopy,
  stageTwoInactiveHint,
  stageTwoStatusCopy,
  stageZoneTitle,
} from "./challengeQuestionStageModel";
import detail from "./challengeQuestionDetailFixture";

/** Narrow fixture view: only the fields the stage projection reads. */
function detailWith(overrides: {
  recordStatus?: string;
  gateDecision?: "pending" | "approved" | "revision_requested" | "rejected";
  plan?: Partial<ChallengeQuestionRunDetailPayload["output"]["research_plan"]>;
}): Pick<ChallengeQuestionRunDetailPayload, "record" | "output"> {
  const base = detail();
  return {
    record: { ...base.record, status: overrides.recordStatus ?? base.record.status },
    output: {
      ...base.output,
      selection: {
        ...base.output.selection,
        human_gate: {
          ...base.output.selection.human_gate,
          decision: overrides.gateDecision ?? base.output.selection.human_gate.decision,
        },
      },
      research_plan: { ...base.output.research_plan, ...(overrides.plan ?? {}) },
    },
  };
}

describe("challengeQuestionStageModel", () => {
  it("derives 假说已定 from the approved record status", () => {
    const projection = deriveChallengeQuestionStageProjection(
      detailWith({ recordStatus: "approved", gateDecision: "pending" }),
    );
    expect(projection.stageOne).toBe("hypothesis_settled");
    expect(stageOneStatusCopy(projection.stageOne, "zh")).toBe("假说已定");
  });

  it("derives 假说已定 from the selection human gate alone", () => {
    const projection = deriveChallengeQuestionStageProjection(
      detailWith({ recordStatus: "pending_review", gateDecision: "approved" }),
    );
    expect(projection.stageOne).toBe("hypothesis_settled");
  });

  it("derives 假说生成中 while neither the record nor the gate approved", () => {
    const projection = deriveChallengeQuestionStageProjection(
      detailWith({ recordStatus: "pending_review", gateDecision: "pending" }),
    );
    expect(projection.stageOne).toBe("hypothesis_generating");
    expect(stageOneStatusCopy(projection.stageOne, "zh")).toBe("假说生成中");
    expect(stageOneStatusCopy(projection.stageOne, "en")).toBe("Generating");
  });

  it("never activates stage two and labels it inactive", () => {
    const projection = deriveChallengeQuestionStageProjection(detailWith({}));
    expect(projection.stageTwoActive).toBe(false);
    expect(stageTwoStatusCopy("zh")).toBe("未激活");
    expect(stageTwoInactiveHint("zh")).toContain("需按题显式开启");
  });

  it("treats a blank research plan as no proposal and a filled one as proposal-only", () => {
    const withoutPlan = deriveChallengeQuestionStageProjection(
      detailWith({ plan: { objective: "", method: "", work_packages: [] } }),
    );
    expect(withoutPlan.hasResearchPlanProposal).toBe(false);

    const withPlan = deriveChallengeQuestionStageProjection(detailWith({}));
    expect(withPlan.hasResearchPlanProposal).toBe(true);
  });

  it("returns a generating/inactive default for missing detail payloads", () => {
    const projection = deriveChallengeQuestionStageProjection(undefined);
    expect(projection).toEqual({
      stageOne: "hypothesis_generating",
      stageTwoActive: false,
      hasResearchPlanProposal: false,
    });
  });

  it("uses descriptive zone names, never ordinals", () => {
    expect(stageZoneTitle("hypothesis", "zh")).toBe("假说生成");
    expect(stageZoneTitle("plan", "zh")).toBe("研究计划与实验");
    expect(stageZoneTitle("hypothesis", "en")).toBe("Hypothesis generation");
    expect(stageZoneTitle("plan", "en")).toBe("Research plan & experiment");
  });
});
