import { describe, expect, it } from "vitest";

import {
  buildSourceCollectionBoardChrome,
  buildSourceCollectionCompletionFlowNodes,
  buildSourceCollectionStandaloneStageModules,
  pickSourceCollectionPipelineModule,
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
  it("picks board current module and next-step label from nextLabel", () => {
    const chrome = buildSourceCollectionBoardChrome({
      lang: "zh",
      sourceCollectionStageModules: [module],
      sourceCollectionStageFocusLabel: "focus",
    });
    expect(chrome.sourceCollectionBoardCurrentModule?.id).toBe("finding");
    expect(chrome.sourceCollectionBoardNextStepLabel).toBe("next");
  });

  it("pipeline primary skips done finding and owns extraction", () => {
    const finding: SourceCollectionStageModule = {
      ...module,
      id: "finding",
      label: "找资料",
      state: "done",
      actionLabel: "搜索下一批",
      nextLabel: "进入资料提炼",
    };
    const extraction: SourceCollectionStageModule = {
      ...module,
      id: "extraction",
      label: "提炼",
      state: "pending",
      actionLabel: "Agent 提炼资料",
      nextLabel: "Agent 继续提炼",
    };
    const picked = pickSourceCollectionPipelineModule([finding, extraction]);
    expect(picked?.id).toBe("extraction");
    expect(picked?.actionLabel).toBe("Agent 提炼资料");
    const chrome = buildSourceCollectionBoardChrome({
      lang: "zh",
      sourceCollectionStageModules: [finding, extraction],
      sourceCollectionStageFocusLabel: "focus",
    });
    expect(chrome.sourceCollectionBoardNextStepLabel).toBe("Agent 继续提炼");
  });

  it("pipeline primary hands off to extraction when finding nextLabel is handoff even if state still pending", () => {
    const finding: SourceCollectionStageModule = {
      ...module,
      id: "finding",
      label: "找资料",
      state: "pending",
      actionLabel: "搜索下一批",
      nextLabel: "进入资料提炼",
    };
    const extraction: SourceCollectionStageModule = {
      ...module,
      id: "extraction",
      label: "提炼",
      state: "idle",
      actionLabel: "Agent 提炼资料",
      nextLabel: "进入资料关系整理",
    };
    expect(pickSourceCollectionPipelineModule([finding, extraction])?.id).toBe("extraction");
  });

  it("keeps pipeline on relations when graph missing links would block ingestion", () => {
    const finding: SourceCollectionStageModule = {
      ...module,
      id: "finding",
      state: "done",
      nextLabel: "进入资料提炼",
    };
    const extraction: SourceCollectionStageModule = {
      ...module,
      id: "extraction",
      state: "done",
      nextLabel: "进入资料关系整理",
    };
    const relations: SourceCollectionStageModule = {
      ...module,
      id: "relations",
      label: "整理关系",
      state: "done",
      actionLabel: "Agent 整理关系",
      nextLabel: "进入资料入库",
    };
    const ingestion: SourceCollectionStageModule = {
      ...module,
      id: "ingestion",
      label: "入库",
      state: "failed",
      actionLabel: "Agent 继续入库",
      nextLabel: "完成入库",
    };
    const picked = pickSourceCollectionPipelineModule(
      [finding, extraction, relations, ingestion],
      { nodeCount: 19, edgeCount: 19, missingLinkCount: 60 },
    );
    expect(picked?.id).toBe("relations");
    expect(picked?.actionLabel).toBe("Agent 整理关系");
  });

  it("lets ingestion run with a poor graph once relations is done (backend has no such gate)", () => {
    const finding: SourceCollectionStageModule = { ...module, id: "finding", state: "done" };
    const extraction: SourceCollectionStageModule = { ...module, id: "extraction", state: "done" };
    const relations: SourceCollectionStageModule = {
      ...module,
      id: "relations",
      state: "done",
      nextLabel: "进入资料入库",
    };
    const ingestion: SourceCollectionStageModule = { ...module, id: "ingestion", state: "pending" };
    const picked = pickSourceCollectionPipelineModule(
      [finding, extraction, relations, ingestion],
      { nodeCount: 19, edgeCount: 0, missingLinkCount: 60 },
    );
    expect(picked?.id).toBe("ingestion");
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
