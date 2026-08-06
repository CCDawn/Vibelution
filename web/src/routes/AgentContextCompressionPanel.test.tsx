import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentContextCompressionPanel, type AgentContextCompressionPolicyDraft } from "./AgentContextCompressionPanel";

const copy = {
  contextCompressionCustom: "自定义",
  contextCompressionEnabled: "启用压缩",
  contextCompressionExtractDecisions: "提取决策",
  contextCompressionInherit: "继承",
  contextCompressionKeepAi: "保留 AI 消息",
  contextCompressionMaxCount: "最大次数",
  contextCompressionMaxTokenLimit: "最大 Token",
  contextCompressionPolicy: "上下文压缩",
  contextCompressionPreserveErrors: "保留错误",
  contextCompressionSummaryChars: "摘要长度",
  contextCompressionThresholds: "阈值",
};

const policy: AgentContextCompressionPolicyDraft = {
  mode: "inherit",
  enabled: true,
  maxTokenLimit: "24000",
  maxCompressionsPerSession: "2",
  lightThreshold: "60",
  standardThreshold: "70",
  deepThreshold: "80",
  emergencyThreshold: "90",
  lightSummaryChars: "800",
  standardSummaryChars: "1200",
  deepSummaryChars: "1600",
  emergencySummaryChars: "2000",
  keepAiMessages: "3",
  preserveErrors: true,
  extractKeyDecisions: true,
};

function renderPanel(mode: AgentContextCompressionPolicyDraft["mode"]) {
  return renderToStaticMarkup(
    <AgentContextCompressionPanel
      copy={copy}
      lang="zh"
      policy={{ ...policy, mode }}
      title="继承工作区上下文压缩策略。"
      onPolicyChange={() => undefined}
      onOpenContextConfig={() => undefined}
    />,
  );
}

describe("AgentContextCompressionPanel", () => {
  it("keeps inherited mode compact and reveals controls only for custom policy", () => {
    const inheritedMarkup = renderPanel("inherit");
    const customMarkup = renderPanel("custom");

    expect(inheritedMarkup.match(/>上下文压缩</g)).toHaveLength(1);
    expect(inheritedMarkup).toContain("去上下文配置");
    expect(inheritedMarkup).not.toContain(">最大 Token<");
    expect(customMarkup).toContain(">最大 Token<");
    expect(customMarkup).toContain("保留错误");
    expect(customMarkup).toContain('tabindex="0"');
  });
});
