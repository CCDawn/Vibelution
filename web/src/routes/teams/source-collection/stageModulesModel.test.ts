import { describe, expect, it } from "vitest";

import {
  buildSourceCollectionBoardChrome,
  buildSourceCollectionCompletionFlowNodes,
  buildSourceCollectionStandaloneStageModules,
  type SourceCollectionStageModule,
} from "./stageModulesModel";

const module: SourceCollectionStageModule = {
  id: "finding",
  label: "Find",
  metric: "1",
  summary: "ok",
  inputLabel: "in",
  outputLabel: "out",
  nextLabel: "next",
  state: "active",
  status: "running",
  detailLabel: "detail",
  actionLabel: "go",
  actionDisabled: false,
  actionTone: "primary",
  actionIcon: "play",
  projection: null,
  onAction: () => undefined,
  onDetail: () => undefined,
};

describe("stageModulesModel", () => {
  it("picks board current module and next-step label", () => {
    const chrome = buildSourceCollectionBoardChrome({
      lang: "zh",
      sourceCollectionStageModules: [module],
      sourceCollectionStageFocusLabel: "focus",
    });
    expect(chrome.sourceCollectionBoardCurrentModule?.id).toBe("finding");
    expect(chrome.sourceCollectionBoardNextStepLabel).toBe("Find");
  });

  it("falls back completion flow nodes from stage modules", () => {
    const nodes = buildSourceCollectionCompletionFlowNodes({
      selectedTeamKnowledgeCollectionWorkRun: null,
      sourceCollectionStageModules: [module],
    });
    expect(nodes).toHaveLength(1);
    expect(nodes[0]?.stageId).toBe("finding");
    expect(nodes[0]?.status).toBe("running");
  });

  it("maps standalone stage modules without dumping summary", () => {
    const standalone = buildSourceCollectionStandaloneStageModules({
      lang: "en",
      sourceCollectionStageModules: [module],
      selectedSourceCollectionStageId: "finding",
      sourceCollectionStageActionReadinessFor: () => ({ disabled: false, loading: false, reason: "" }),
      sourceCollectionActionDisabledTitle: (_r, fallback) => fallback,
    });
    expect(standalone[0]?.selected).toBe(true);
    expect(standalone[0]?.nextLabel).toContain("Next:");
    expect(JSON.stringify(standalone)).not.toContain("summary");
  });
});
