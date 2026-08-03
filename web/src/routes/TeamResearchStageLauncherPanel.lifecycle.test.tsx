import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const source = readFileSync(
  new URL("./TeamResearchStageLauncherPanel.tsx", import.meta.url),
  "utf8",
);

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
    expect(source).toContain('presentationMode?: "overview" | "interactive"');
    expect(source).toContain('presentationMode === "overview"');
    expect(source).toContain('data-presentation={stageCardsReadOnly ? "overview" : "interactive"}');
    expect(source).toContain("ResearchWorkflowErrorSurface");
    expect(source).toContain('data-presentation={stageCardsReadOnly ? "overview-readonly" : "interactive"}');
    expect(source).toContain('lang === "zh" ? "查看阶段" : "View stage"');
    expect(source).toContain("researchExperimentMethodReadonly");
  });
});
