import { describe, expect, it } from "vitest";

import { buildExtractionStageFlowGuide } from "./extractionStageFlowGuide";

describe("buildExtractionStageFlowGuide", () => {
  it("recommends material repair first when sources still need evidence", () => {
    const guide = buildExtractionStageFlowGuide({
      lang: "zh",
      needsAgentMaterial: true,
      pendingScreeningCount: 0,
      approvedCount: 2,
      displayedCandidateCount: 10,
      pendingImportCount: 0,
      canProceedAfterExclusions: false,
      qualityReviewPending: false,
      qualityReviewButtonText: "重新质量审查",
      recoveryActive: true,
      recoveryPrimaryLabel: "要求 Agent 补充材料",
      recoveryPrimaryKind: "continue_task",
    });

    expect(guide.currentStepId).toBe("repair");
    expect(guide.recommendedKind).toBe("supplement");
    expect(guide.recommendedLabel).toContain("补充材料");
    expect(guide.showQualityReviewSecondary).toBe(true);
    expect(guide.steps.find((step) => step.id === "repair")?.state).toBe("current");
    expect(guide.steps.find((step) => step.id === "review")?.state).toBe("upcoming");
    expect(guide.nowHint).toContain("大按钮");
  });

  it("promotes quality review when materials are ready and screening is pending", () => {
    const guide = buildExtractionStageFlowGuide({
      lang: "zh",
      needsAgentMaterial: false,
      pendingScreeningCount: 8,
      approvedCount: 0,
      displayedCandidateCount: 8,
      pendingImportCount: 0,
      canProceedAfterExclusions: false,
      qualityReviewPending: false,
      qualityReviewButtonText: "Agent 质量审查",
      recoveryActive: false,
    });

    expect(guide.currentStepId).toBe("review");
    expect(guide.recommendedKind).toBe("quality_review");
    expect(guide.recommendedLabel).toBe("Agent 质量审查");
    expect(guide.showQualityReviewSecondary).toBe(false);
    expect(guide.steps.find((step) => step.id === "repair")?.state).toBe("done");
  });

  it("advances to relations when approved candidates exist and nothing is pending", () => {
    const guide = buildExtractionStageFlowGuide({
      lang: "zh",
      needsAgentMaterial: false,
      pendingScreeningCount: 0,
      approvedCount: 5,
      displayedCandidateCount: 5,
      pendingImportCount: 0,
      canProceedAfterExclusions: false,
      qualityReviewPending: false,
      qualityReviewButtonText: "重新质量审查",
      recoveryActive: false,
    });

    expect(guide.currentStepId).toBe("advance");
    expect(guide.recommendedKind).toBe("advance_relations");
    expect(guide.recommendedLabel).toContain("关系整理");
  });

  it("shows wait state while quality review is running", () => {
    const guide = buildExtractionStageFlowGuide({
      lang: "zh",
      needsAgentMaterial: false,
      pendingScreeningCount: 3,
      approvedCount: 0,
      displayedCandidateCount: 3,
      pendingImportCount: 0,
      canProceedAfterExclusions: false,
      qualityReviewPending: true,
      qualityReviewButtonText: "质量审查中",
      recoveryActive: false,
    });

    expect(guide.recommendedKind).toBe("wait");
    expect(guide.recommendedLabel).toContain("质量审查中");
  });

  it("still advances when recovery is exclusion-only", () => {
    const guide = buildExtractionStageFlowGuide({
      lang: "zh",
      needsAgentMaterial: false,
      pendingScreeningCount: 0,
      approvedCount: 4,
      displayedCandidateCount: 6,
      pendingImportCount: 0,
      canProceedAfterExclusions: true,
      qualityReviewPending: false,
      qualityReviewButtonText: "重新质量审查",
      recoveryActive: true,
      recoveryPrimaryLabel: "进入 Agent 私聊",
      recoveryPrimaryKind: "chat",
    });

    expect(guide.currentStepId).toBe("advance");
    expect(guide.recommendedKind).toBe("advance_relations");
  });
});
