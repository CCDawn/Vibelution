import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type {
  AgentEffectiveConfigurationField,
  AgentRunSnapshot,
} from "../api/types";
import { VuiProvider } from "../components/vui/VuiProvider";
import {
  AgentFocusedOverviewPanel,
  focusedEffectiveValue,
  summarizeAgentRuns,
  type AgentFocusedOverviewPanelProps,
} from "./AgentFocusedOverviewPanel";

const NOW = Date.parse("2026-08-19T12:00:00Z");

function run(
  id: string,
  status: string,
  startedAt: string,
  finishedAt: string,
): AgentRunSnapshot {
  return {
    runId: id,
    status,
    startedAt,
    finishedAt,
    updatedAt: finishedAt,
  } as AgentRunSnapshot;
}

function field(index: number): AgentEffectiveConfigurationField {
  return {
    key: `field-${index}`,
    label: `配置项 ${index}`,
    effectiveValue: `值 ${index}`,
    source: { kind: "agent", id: "a1", label: "Agent 配置" },
    inheritanceChain: [],
    status: index === 1 ? "warning" : "ready",
  };
}

function props(
  patch: Partial<AgentFocusedOverviewPanelProps> = {},
): AgentFocusedOverviewPanelProps {
  return {
    lang: "zh",
    summary: {
      statusLabel: "空闲",
      statusTone: "success",
      statusDetail: "没有阻塞项",
      modelLabel: "gpt-test",
      modelDetail: "对话模型",
      revisionLabel: "r17",
      latestRunLabel: "08/19 19:40",
    },
    effectiveFields: Array.from({ length: 9 }, (_, index) => field(index)),
    activities: Array.from({ length: 7 }, (_, index) => ({
      id: `activity-${index}`,
      title: `活动 ${index}`,
      body: `活动详情 ${index}`,
      meta: `08/19 1${index}:00`,
    })),
    activityState: "ready",
    identity: {
      roleLabel: "研究执行",
      modeLabel: "研究",
      workspaceLabel: "private",
      teamNames: ["证据团队", "评审团队"],
    },
    runs: [],
    pendingApprovalCount: 2,
    attentionItems: [{
      id: "warning",
      title: "工具审批待处理",
      detail: "处理审批后再运行",
      tone: "warning",
    }],
    onOpenConfig: vi.fn(),
    onOpenActivity: vi.fn(),
    ...patch,
  };
}

describe("AgentFocusedOverviewPanel", () => {
  it("derives 24-hour run health without inventing data", () => {
    const summary = summarizeAgentRuns([
      run("success-1", "completed", "2026-08-19T10:00:00Z", "2026-08-19T10:00:01Z"),
      run("success-2", "succeeded", "2026-08-19T09:00:00Z", "2026-08-19T09:00:02Z"),
      run("failure", "failed", "2026-08-19T08:00:00Z", "2026-08-19T08:00:03Z"),
      run("old", "completed", "2026-08-17T08:00:00Z", "2026-08-17T08:00:04Z"),
    ], NOW);

    expect(summary).toEqual({
      runCount24h: 3,
      successRate: 67,
      p95DurationMs: 3_000,
    });
    expect(summarizeAgentRuns([], NOW)).toEqual({
      runCount24h: 0,
      successRate: null,
      p95DurationMs: null,
    });
  });

  it("formats effective values as concise summaries instead of raw JSON", () => {
    expect(focusedEffectiveValue({ key: "enabled", effectiveValue: true }, "zh")).toBe("已启用");
    expect(focusedEffectiveValue({
      key: "contextCompression",
      effectiveValue: { mode: "custom", maxTokenLimit: 12_000 },
    }, "en")).toBe("custom · 12,000 tokens");
    expect(focusedEffectiveValue({ key: "secret", effectiveValue: { token: "hidden" } }, "zh"))
      .toBe("已配置");
  });

  it("renders the approved dense overview and caps the two scan lists", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <AgentFocusedOverviewPanel {...props()} />
      </VuiProvider>,
    );

    expect(markup).toContain('data-agent-focused-overview="true"');
    expect(markup).toContain("gpt-test");
    expect(markup).toContain("r17");
    expect(markup).toContain("有效配置");
    expect(markup).toContain("配置项 7");
    expect(markup).not.toContain("配置项 8");
    expect(markup).toContain("活动 5");
    expect(markup).not.toContain("活动 6");
    expect(markup).toContain("身份与团队");
    expect(markup).toContain("运行健康");
    expect(markup).toContain("需要关注");
    expect(markup).toContain("证据团队");
    expect(markup).toContain("工具审批待处理");
  });

  it("keeps real configuration and identity visible when activity fails", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <AgentFocusedOverviewPanel
          {...props({
            effectiveFields: [],
            activities: [],
            activityState: "error",
            activityError: "network unavailable",
            attentionItems: [],
          })}
        />
      </VuiProvider>,
    );

    expect(markup).toContain("暂无有效配置投影");
    expect(markup).toContain("network unavailable");
    expect(markup).toContain("研究执行");
    expect(markup).toContain("当前没有阻塞、警告或待处理配置项");
  });
});
