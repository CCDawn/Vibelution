import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SourceCollectionDraft } from "../presentationModel";
import type { SourceCollectionPhaseCloseGate } from "../stageProjection";
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
  it("renders the approved topic-first search brief without a local flow-progress CTA", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceCollectionSearchBriefPanel
        lang="zh"
        draft={draft}
        modeFields={<label>搜索方式</label>}
        hasExistingRun
        onDraftChange={() => undefined}
      />,
    );

    expect(markup).toContain('data-vui-product="source-collection-search-brief"');
    expect(markup).toContain("先决定要研究什么");
    expect(markup).toContain("科研 Agent 如何完成证据检索与实验规划");
    expect(markup).toContain("搜索问题 1");
    expect(markup).toContain("删除搜索问题 2");
    expect(markup).toContain("检索式（可选）");
    expect(markup).toContain("搜索范围与来源偏好");
    expect(markup).toContain("右侧「推荐下一步」");
    expect(markup).not.toContain("按当前方案搜索下一批");
    expect(markup).not.toContain("开始搜索");
  });

  it("uses flex rows so index/input/delete stay on one line in production CSS", () => {
    // Arbitrary grid-cols were dropping in build → single-column stack (index above, × below).
    expect(styles.queryRow).toContain("flex");
    expect(styles.queryRow).toContain("items-center");
    expect(styles.queryRow).not.toContain("grid-cols-");
    expect(styles.queryInputWrap).toContain("flex-1");
    expect(styles.queryInput).toContain("!border-0");
    expect(styles.removeButton).toContain("shrink-0");
    expect(panelSource).toContain("queryInputWrap");
    expect(panelSource).toContain('role="list"');
  });

  it("exposes an honest empty-query state and points first-start to the right rail", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceCollectionSearchBriefPanel
        lang="zh"
        draft={{ ...draft, querySeeds: "", topic: "" }}
        modeFields={null}
        hasExistingRun={false}
        onDraftChange={() => undefined}
      />,
    );

    expect(markup).toContain("将直接用研究主题搜索");
    expect(markup).toContain("只在右侧「推荐下一步」开始搜集");
    expect(markup).not.toContain("开始搜索");
  });

  it("keeps draft editing only and does not own start mutation wiring", () => {
    expect(styles.actionHint).toContain("text-[var(--fg-tertiary)]");
    expect(panelSource).toContain("onDraftChange({ topic: event.target.value })");
    expect(panelSource).toContain("onDraftChange({ querySeeds:");
    expect(panelSource).not.toContain("onSubmit");
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
    expect(markup).toContain('data-compact-steps="hidden"');
    expect(markup).toContain("下一步：内容提炼");
    expect(markup).toContain("1/4");
    expect(markup).toContain("去内容提炼");
    expect(markup).toContain("运行详情");
    expect(markup).toContain("collecting");
    // Compact mode must not re-list the four stage steps (those live in TeamStagePipeline).
    expect(markup).not.toContain("phaseCloseGateSteps");
    expect(markup).toContain("阶段明细见下方");
  });
});
