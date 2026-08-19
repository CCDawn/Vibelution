import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type {
  AgentEffectiveConfigurationField,
  AgentMemoryPolicyOption,
  AgentModelChoice,
  AgentRunSnapshot,
  AgentToolPolicyOption,
  AgentToolPolicySource,
  PromptTemplate,
} from "../api/types";
import { VuiProvider } from "../components/vui/VuiProvider";
import {
  AgentFocusedOverviewPanel,
  effectiveConfigurationSourceLabel,
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
    expect(focusedEffectiveValue({ key: "enabled", effectiveValue: true }, "zh"))
      .toEqual({ primary: "已启用" });
    expect(focusedEffectiveValue({
      key: "contextCompression",
      effectiveValue: { mode: "custom", maxTokenLimit: 12_000 },
    }, "en")).toEqual({
      primary: "12K tokens before compression",
      secondary: "Custom threshold",
    });
    expect(focusedEffectiveValue({ key: "secret", effectiveValue: { token: "hidden" } }, "zh"))
      .toEqual({ primary: "已配置" });
  });

  it("maps effective IDs to real names and behavior summaries", () => {
    const dialogueModel = {
      label: "Llama 3.2",
      providerLabel: "本地 OpenAI-compatible",
      providerKind: "openai-compatible",
      contextWindow: 1_000_000,
    } as AgentModelChoice;
    const promptTemplate = {
      promptTemplateId: "prompt-challenge-cup-experiment-planner",
      name: "Challenge Cup Experiment Planner",
      category: "research",
      sourceType: "workspace_file",
    } as PromptTemplate;
    const toolPolicy = {
      policyId: "tool-agent-internal",
      allowedToolCount: 12,
      blockedToolCount: 2,
      preferredToolCount: 1,
      networkAccess: "controlled",
      mutationAccess: "restricted",
      maxCallsPerTurn: 20,
    } as AgentToolPolicyOption;
    const memoryPolicy = {
      policyId: "memory-agent-internal",
      privateMemoryRoot: "workspace/agent/memory",
      readSharedGroupCount: 2,
      writeSharedGroupCount: 1,
      readKnowledgeBaseCount: 3,
      proposeKnowledgeBaseCount: 1,
      reviewKnowledgeBaseCount: 0,
      hasInboxPath: true,
    } as AgentMemoryPolicyOption;

    expect(focusedEffectiveValue(
      { key: "dialogueModel", effectiveValue: "local_main/llama3.2" },
      "zh",
      { dialogueModel },
    )).toEqual({
      primary: "Llama 3.2",
      secondary: "本地 OpenAI-compatible · 上下文 100 万 tokens",
      rawId: "local_main/llama3.2",
    });
    expect(focusedEffectiveValue(
      { key: "promptTemplate", effectiveValue: "prompt-challenge-cup-experiment-planner" },
      "zh",
      { promptTemplate },
    )).toEqual({
      primary: "Challenge Cup Experiment Planner",
      secondary: "科研模板 · 工作区文件",
      rawId: "prompt-challenge-cup-experiment-planner",
    });
    expect(focusedEffectiveValue(
      { key: "toolPolicy", effectiveValue: "tool-agent-internal" },
      "zh",
      { toolPolicy, toolPolicySource: { mutatingToolCount: 3 } as AgentToolPolicySource },
    )).toEqual({
      primary: "12 个工具可用",
      secondary: "3 个可写/命令工具 · 受控网络 · 每轮最多 20 次",
      rawId: "tool-agent-internal",
    });
    expect(focusedEffectiveValue(
      { key: "memoryPolicy", effectiveValue: "memory-agent-internal" },
      "zh",
      { memoryPolicy },
    )).toEqual({
      primary: "私有记忆已配置",
      secondary: "共享组：读 2 / 写 1 · 知识库：读 3 / 提议 1 / 评审 0 · 含收件箱",
      rawId: "memory-agent-internal",
    });
  });

  it("does not invent names from internal slugs and translates policy semantics", () => {
    expect(focusedEffectiveValue({
      key: "promptTemplate",
      effectiveValue: "prompt-unknown-slug",
    }, "zh")).toEqual({
      primary: "prompt-unknown-slug",
      secondary: "仅有内部标识",
    });
    expect(focusedEffectiveValue({
      key: "delegation",
      effectiveValue: { allowSubagents: false, maxConcurrent: 0, maxDepth: 0 },
    }, "zh")).toEqual({ primary: "未启用" });
    expect(focusedEffectiveValue({
      key: "supervision",
      effectiveValue: {
        supervisionEnabled: true,
        reviewMode: "advisory",
        evidenceLevel: "standard",
      },
    }, "zh")).toEqual({ primary: "建议评审，不阻断", secondary: "标准证据" });
    expect(effectiveConfigurationSourceLabel("shared_policy", "zh")).toBe("共享策略");
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
    expect(markup).toContain("已生效");
    expect(markup).not.toContain(">可用<");
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

  it("renders readable primary and supporting values while retaining the raw ID as trace metadata", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <AgentFocusedOverviewPanel
          {...props({
            effectiveFields: [{
              key: "dialogueModel",
              label: "对话模型",
              effectiveValue: "local_main/llama3.2",
              source: { kind: "agent", id: "a1", label: "Agent 模型绑定" },
              inheritanceChain: [],
              status: "ready",
            }],
            effectiveResources: {
              dialogueModel: {
                label: "Llama 3.2",
                providerLabel: "本地 OpenAI-compatible",
                providerKind: "openai-compatible",
                contextWindow: 1_000_000,
              } as AgentModelChoice,
            },
          })}
        />
      </VuiProvider>,
    );

    expect(markup).toContain("Llama 3.2");
    expect(markup).toContain("本地 OpenAI-compatible");
    expect(markup).toContain('data-effective-value-id="local_main/llama3.2"');
    expect(markup).toContain("此 Agent");
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
