import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SourceCollectionDraft } from "./teams/source-collection/presentationModel";
import type { SourceCollectionPhaseCloseGate } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionPhaseCloseGatePanel } from "./TeamSourceCollectionPhaseCloseGatePanel";
import { TeamSourceCollectionSearchBriefPanel } from "./TeamSourceCollectionSearchBriefPanel";
import panelSource from "./TeamSourceCollectionSearchBriefPanel.tsx?raw";
import styles from "./TeamSourceCollectionSearchBriefPanel.styles";

const draft: SourceCollectionDraft = {
  title: "科研 Agent 资料检索",
  topic: "科研 Agent 如何完成证据检索与实验规划",
  goal: "形成可引用的工作流证据",
  querySeeds: "科研 Agent 的标准研究流程有哪些？\n成熟项目如何保存证据锚点？",
  inputRefs: "",
  searchLanguages: "zh,en",
  sourceTypes: "paper,repository,documentation",
  maxResultsPerQuery: 10,
  collectionMode: "web_search",
  localScanRoots: "workspace/knowledge",
};

const phaseGate: SourceCollectionPhaseCloseGate = {
  runId: "dprun-20260724",
  stageRoundStatus: "collecting",
  status: "needs_continue",
  stageCount: 4,
  closedLoopCount: 1,
  stages: [
    { stageId: "finding", passed: true, status: "completed" },
    { stageId: "extraction", passed: false, status: "pending" },
    { stageId: "relations", passed: false, status: "pending" },
    { stageId: "ingestion", passed: false, status: "pending" },
  ],
  blockingReasons: ["extraction 阶段尚未形成闭环"],
};

describe("TeamSourceCollectionSearchBriefPanel", () => {
  it("renders the approved topic-first search brief with editable query rows", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceCollectionSearchBriefPanel
        lang="zh"
        draft={draft}
        modeFields={<label>搜索方式</label>}
        hasExistingRun
        canStart
        startPending={false}
        onDraftChange={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect(markup).toContain('data-vui-product="source-collection-search-brief"');
    expect(markup).toContain("先决定要研究什么");
    expect(markup).toContain("科研 Agent 如何完成证据检索与实验规划");
    expect(markup).toContain("搜索问题 1");
    expect(markup).toContain("删除搜索问题 2");
    expect(markup).toContain("搜索范围与来源偏好");
    expect(markup).toContain("会新建批次，不覆盖当前资料");
    expect(markup).toContain("按当前方案搜索下一批");
  });

  it("exposes an honest empty-query state and disables execution when the draft is invalid", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceCollectionSearchBriefPanel
        lang="zh"
        draft={{ ...draft, querySeeds: "", topic: "" }}
        modeFields={null}
        hasExistingRun={false}
        canStart={false}
        startPending={false}
        onDraftChange={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect(markup).toContain("至少补充一个问题后再开始搜索");
    expect(markup).toContain("开始搜索");
    expect(markup).toContain("disabled");
  });

  it("keeps the action content-sized and updates only the canonical draft through callbacks", () => {
    expect(styles.primaryAction).not.toContain("w-full");
    expect(panelSource).toContain("onDraftChange({ topic: event.target.value })");
    expect(panelSource).toContain("onDraftChange({ querySeeds:");
    expect(panelSource).not.toContain("fetch(");
    expect(panelSource).not.toContain("useMutation");
  });

  it("renders the compact progress card with raw runtime facts behind a disclosure", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceCollectionPhaseCloseGatePanel
        lang="zh"
        selectedRunId="dprun-20260724"
        gate={phaseGate}
        loading={false}
        compact
        onOpenStage={() => undefined}
      />,
    );

    expect(markup).toContain('data-compact="true"');
    expect(markup).toContain("下一步：内容提炼");
    expect(markup).toContain("1/4");
    expect(markup).toContain("去内容提炼");
    expect(markup).toContain("运行详情");
    expect(markup).toContain("collecting");
  });
});
