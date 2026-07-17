import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AgentOverviewOperationsPanel } from "./AgentOverviewOperationsPanel";

const copy = {
  currentFocus: "当前运行焦点",
  recentActivity: "最近活动",
  loading: "正在读取运行信息…",
  noActivity: "尚无运行记录",
  noActivityDetail: "可从会话开始使用此 Agent，或先检查配置。",
  activityUnavailable: "活动信息暂不可用",
  latestRun: "最近运行",
  updated: "更新时间",
  nextStep: "下一步",
  openSession: "打开会话",
  openLogs: "查看日志",
  checkConfig: "检查配置",
  viewActivity: "查看完整活动",
};

describe("AgentOverviewOperationsPanel", () => {
  it("keeps current runtime and recent activity in the overview work surface", () => {
    const markup = renderToStaticMarkup(
      <AgentOverviewOperationsPanel
        copy={copy}
        state="ready"
        runtime={{
          statusLabel: "运行中",
          statusReason: "正在处理检索任务",
          summary: "检索来源并整理结论",
          latestRunId: "run-20260715-01",
          updatedAt: "07/15 14:30",
          nextStep: "查看日志确认进度",
          onOpenSession: vi.fn(),
          onOpenLogs: vi.fn(),
        }}
        activities={[
          {
            id: "run-1",
            title: "运行完成",
            body: "已输出研究摘要",
            meta: "07/15 14:30 · 12 秒",
            onOpenLogs: vi.fn(),
          },
        ]}
        onOpenActivity={vi.fn()}
        onOpenConfig={vi.fn()}
      />,
    );

    expect(markup).toContain("当前运行焦点");
    expect(markup).toContain("运行中");
    expect(markup).toContain("最近活动");
    expect(markup).toContain("已输出研究摘要");
    expect(markup).toContain("查看完整活动");
    expect(markup).toContain("查看日志");
    expect(markup).toContain("最近运行");
    expect(markup).toContain('aria-label="最近运行完整值"');
  });

  it("turns an idle Agent into a task-oriented empty state", () => {
    const markup = renderToStaticMarkup(
      <AgentOverviewOperationsPanel
        copy={copy}
        state="ready"
        runtime={{
          statusLabel: "空闲",
          statusReason: "暂无运行",
          summary: "等待会话入口触发",
          latestRunId: "-",
          updatedAt: "07/15 14:30",
          nextStep: "从会话开始使用此 Agent",
        }}
        activities={[]}
        onOpenActivity={vi.fn()}
        onOpenConfig={vi.fn()}
        onOpenSession={vi.fn()}
      />,
    );

    expect(markup).toContain("尚无运行记录");
    expect(markup).toContain("可从会话开始使用此 Agent，或先检查配置。");
    expect(markup).toContain("打开会话");
    expect(markup).toContain("检查配置");
  });

  it("keeps summary content visible when activity loading or fails", () => {
    const loadingMarkup = renderToStaticMarkup(
      <AgentOverviewOperationsPanel
        copy={copy}
        state="loading"
        runtime={{
          statusLabel: "空闲",
          statusReason: "暂无运行",
          summary: "等待会话入口触发",
          latestRunId: "-",
          updatedAt: "07/15 14:30",
          nextStep: "从会话开始使用此 Agent",
        }}
        activities={[]}
        onOpenActivity={vi.fn()}
        onOpenConfig={vi.fn()}
      />,
    );
    const errorMarkup = renderToStaticMarkup(
      <AgentOverviewOperationsPanel
        copy={copy}
        state="error"
        errorMessage="network unavailable"
        runtime={{
          statusLabel: "空闲",
          statusReason: "暂无运行",
          summary: "等待会话入口触发",
          latestRunId: "-",
          updatedAt: "07/15 14:30",
          nextStep: "从会话开始使用此 Agent",
        }}
        activities={[]}
        onOpenActivity={vi.fn()}
        onOpenConfig={vi.fn()}
      />,
    );

    expect(loadingMarkup).toContain("正在读取运行信息…");
    expect(loadingMarkup).toContain("当前运行焦点");
    expect(errorMarkup).toContain("活动信息暂不可用");
    expect(errorMarkup).toContain("network unavailable");
    expect(errorMarkup).toContain('role="alert"');
  });
});
