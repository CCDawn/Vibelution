import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { buildComposerContextRingModel } from "../../routes/chat/composerContextModel";
import { ComposerContextRingPanel } from "./ComposerContextRing";

function buildModel(options: {
  lang?: "zh" | "en";
  cacheSource?: string;
  cacheUsageObserved?: boolean;
} = {}) {
  return buildComposerContextRingModel({
    usageUsed: 110,
    usageLimit: 220,
    hitPercent: 40,
    detailAvailable: true,
    lang: options.lang ?? "zh",
    cacheSource: options.cacheSource ?? "provider_usage",
    cacheUsageObserved: options.cacheUsageObserved ?? true,
    segments: [
      {
        key: "history",
        label: "历史",
        tokens: 80,
        cachePolicy: "cacheable",
        observedStatus: "observed_miss",
        contentPreview: "之前的消息",
      },
      {
        key: "current_user",
        label: "本轮输入",
        tokens: 10,
        cachePolicy: "never_cache",
        observedStatus: "not_observed",
      },
      {
        key: "agent_context",
        label: "Agent 上下文",
        tokens: 10,
        cachePolicy: "cacheable",
        observedStatus: "not_observed",
      },
    ] as never,
  });
}

describe("ComposerContextRingPanel", () => {
  it("separates composition from cache and names every state", () => {
    const html = renderToStaticMarkup(
      <ComposerContextRingPanel model={buildModel()} lang="zh" />,
    );
    expect(html).toContain('data-composer-context-composition="true"');
    expect(html).toContain('data-composer-context-cache="true"');
    expect(html).toContain('data-cache-state="observed"');
    expect(html).toContain("上轮真实命中 40%");
    expect(html).toContain("未命中 80%");
    expect(html).toContain("不可缓存 10%");
    expect(html).toContain("未观测 10%");
    expect(html).not.toContain('data-cache-kind="hit"');
    expect(html).toContain('data-context-badge="miss"');
    expect(html).toContain('data-context-badge="never"');
    expect(html).toContain('data-context-badge="unknown"');
    expect(html).toContain('data-context-pct="true"');
    expect(html).toContain("80%");
  });

  it("keeps content previews collapsed and expandable per row", () => {
    const html = renderToStaticMarkup(
      <ComposerContextRingPanel model={buildModel()} lang="zh" />,
    );
    expect(html).toContain('data-context-row="history"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("data-context-preview");
    expect(html).not.toContain("之前的消息");
  });

  it("does not paint an unobserved cache as a miss", () => {
    const html = renderToStaticMarkup(
      <ComposerContextRingPanel
        model={buildModel({ cacheUsageObserved: false })}
        lang="zh"
      />,
    );
    expect(html).toContain('data-cache-state="missing"');
    expect(html).toContain("上游未返回缓存命中");
    expect(html).not.toContain("上轮真实命中");
  });

  it("renders english state names without chinese leakage", () => {
    const html = renderToStaticMarkup(
      <ComposerContextRingPanel
        model={buildModel({ lang: "en", cacheUsageObserved: false })}
        lang="en"
      />,
    );
    expect(html).toContain("upstream cache usage missing");
    expect(html).toContain("unobserved");
    expect(html).not.toContain("未观测");
  });
});
