import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const source = readFileSync(
  new URL("./TeamResearchStageLauncherPanel.tsx", import.meta.url),
  "utf8",
);
const propsSource = readFileSync(
  new URL("./teams/researchStageLauncherProps.ts", import.meta.url),
  "utf8",
);
const modelSource = readFileSync(
  new URL("./teams/experimentLoopModel.ts", import.meta.url),
  "utf8",
);
const panelAndProps = `${source}\n${propsSource}`;

describe("TeamResearchStageLauncherPanel lifecycle truth", () => {
  it("uses lifecycle truth for completed knowledge collection", () => {
    expect(source).toContain("researchKnowledgeLifecycleStatusLabel");
    expect(source).toContain('stage1.status === "ready_for_hypothesis"');
    expect(source).toContain("知识搜集已形成可用假设");
  });

  it("explains the concrete evidence required after human review", () => {
    expect(source).toContain('stage3.status === "needs_more_evidence"');
    expect(source).toContain("正式 baseline");
    expect(source).toContain("目标数据集多 seed");
    expect(source).toContain("机制/反证证据");
  });

  it("keeps overview stage cards read-only without competing start CTAs", () => {
    expect(propsSource).toContain('presentationMode?: "overview" | "interactive"');
    expect(source).toContain('presentationMode === "overview"');
    expect(source).toContain('data-presentation={stageCardsReadOnly ? "overview" : "interactive"}');
    expect(source).toContain("ResearchWorkflowErrorSurface");
    expect(source).toContain('data-presentation={stageCardsReadOnly ? "overview-readonly" : "interactive"}');
    expect(source).toContain('lang === "zh" ? "查看阶段" : "View stage"');
    expect(source).toContain("researchExperimentMethodReadonly");
    expect(panelAndProps).toContain("flattenResearchStageLauncherProps");
  });

  it("projects authoritative Program v2 truth while keeping legacy state read-only", () => {
    expect(source).toContain("competitionProgramProjection");
    expect(source).toContain("competitionProgramProjection.completion.completed");
    expect(source).toContain("fullCatalogResultSet");
    expect(source).toContain("requiredDeepExperiments");
    expect(source).toContain("Program v2 交付状态");
    expect(source).toContain("两个实验使用独立 Theme 与独立 Campaign");
    expect(modelSource).toContain("@deprecated Read-only compatibility projection");
    // The legacy projection can still describe the old stage cards, but it
    // cannot decide Program v2 completion.
    expect(source).toContain("challengeProgramProjection");
    expect(source).not.toContain("challengeTeamSurface");
    expect(source).not.toContain("ChallengeQuestionDetailPanel");
  });
});
