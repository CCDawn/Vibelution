import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { ConfigDiagnosis } from "../api/types";
import ConfigDiagnosisPanel, { type ConfigDiagnosisPanelCopy } from "./ConfigDiagnosisPanel";
import { groupConfigDiagnosisIssues } from "./configDiagnosisPresentation";

const repeatedMissingKeyIssues = [
  "mental_model: provider `ai-pixel_ad214f09` 缺少 API Key",
  "subagent_worker: provider `ai-pixel_ad214f09` 缺少 API Key",
  "supervised_baseline: provider `ai-pixel_ad214f09` 缺少 API Key",
  "supervised_candidate: provider `ai-pixel_ad214f09` 缺少 API Key",
];

const copy: ConfigDiagnosisPanelCopy = {
  diagnosticsTitle: "诊断与保存",
  diagnosticsBody: "先处理根因，再保存配置。",
  blockingIssues: "阻塞根因",
  warningSignals: "警告信号",
  suggestedActions: "建议动作",
  noBlocking: "当前没有阻塞问题。",
  noWarnings: "当前没有警告。",
  noSuggestions: "当前没有额外建议动作。",
  rootCauseMetric: "根因",
  affectedReferenceMetric: "受影响引用",
  warningMetric: "警告",
  affectedReferences: "受影响的配置引用",
  showAffectedReferences: "查看受影响引用",
  repairProviderCredential: "设置 API Key",
};

describe("config diagnosis presentation", () => {
  it("groups repeated configuration references under one root cause", () => {
    const groups = groupConfigDiagnosisIssues(repeatedMissingKeyIssues);

    expect(groups).toEqual([
      {
        id: "provider `ai-pixel_ad214f09` 缺少 API Key",
        message: "provider `ai-pixel_ad214f09` 缺少 API Key",
        references: ["mental_model", "subagent_worker", "supervised_baseline", "supervised_candidate"],
        rawItems: repeatedMissingKeyIssues,
        repair: { kind: "provider-api-key", providerId: "ai-pixel_ad214f09" },
      },
    ]);
  });

  it("keeps unrelated and unscoped issues as separate root causes", () => {
    const groups = groupConfigDiagnosisIssues([
      "mental_model: provider ai-pixel 缺少 API Key",
      "provider 192 使用了本地 API base",
      "research_card: model route is incomplete",
    ]);

    expect(groups.map((group) => group.message)).toEqual([
      "provider ai-pixel 缺少 API Key",
      "provider 192 使用了本地 API base",
      "model route is incomplete",
    ]);
    expect(groups[1]?.references).toEqual([]);
    expect(groups[2]?.references).toEqual(["research_card"]);
  });

  it("renders one actionable blocker with collapsed affected references", () => {
    const diagnosis: ConfigDiagnosis = {
      blocking_issues: repeatedMissingKeyIssues,
      warnings: ["192 provider 使用了本地 API base"],
      suggested_actions: ["Shell 配置已启用"],
    };

    const markup = renderToStaticMarkup(createElement(ConfigDiagnosisPanel, {
      diagnosis,
      copy,
      repairableProviderIds: ["ai-pixel_ad214f09"],
      onRepairProvider: vi.fn(),
    }));

    expect(markup).toContain("1</strong><span>根因");
    expect(markup).toContain("4</strong><span>受影响引用");
    expect(markup).toContain("provider `ai-pixel_ad214f09` 缺少 API Key");
    expect(markup).toContain("查看受影响引用 · 4");
    expect(markup).toContain('data-provider-repair="ai-pixel_ad214f09"');
    expect(markup).toContain("设置 API Key");
    expect(markup.match(/provider `ai-pixel_ad214f09` 缺少 API Key/g)).toHaveLength(1);
  });
});
