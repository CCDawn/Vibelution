import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TokenCoreStatusPanel, type TokenCoreStatusMetric } from "./TokenCoreStatusPanel";

const tokenCoreStatusMetrics: TokenCoreStatusMetric[] = [
  {
    key: "cache",
    label: "缓存",
    value: "--",
    meta: "暂无详情",
    title: "缓存详情不可用",
    percent: 0,
    tone: "cache",
  },
  {
    key: "modelInput",
    label: "模型输入",
    value: "12k",
    meta: "上一轮",
    title: "模型输入 token",
    percent: 40,
    tone: "modelInput",
  },
];

describe("TokenCoreStatusPanel", () => {
  it("disables the cache detail trigger until details exist", () => {
    const unavailableHtml = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: false,
        cacheDetailOpen: true,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: tokenCoreStatusMetrics,
        onOpenCacheDetail: () => undefined,
      }),
    );
    const availableHtml = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: true,
        cacheDetailOpen: true,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: tokenCoreStatusMetrics,
        onOpenCacheDetail: () => undefined,
      }),
    );
    const availableClosedHtml = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: true,
        cacheDetailOpen: false,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: tokenCoreStatusMetrics,
        onOpenCacheDetail: () => undefined,
      }),
    );

    expect(unavailableHtml).toContain("disabled");
    expect(unavailableHtml).toContain("aria-disabled=\"true\"");
    expect(unavailableHtml).not.toContain("aria-expanded");
    expect(unavailableHtml).not.toContain("aria-controls=\"cache-detail-dialog\"");
    expect(availableHtml).not.toContain("aria-disabled=\"true\"");
    expect(availableHtml).toContain("aria-expanded=\"true\"");
    expect(availableHtml).toContain("aria-controls=\"cache-detail-dialog\"");
    expect(availableClosedHtml).toContain("aria-expanded=\"false\"");
    expect(availableClosedHtml).toContain("aria-controls=\"cache-detail-dialog\"");
  });

  it("shows the compact ring value and keeps the full count in the accessible name", () => {
    const html = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: false,
        cacheDetailOpen: false,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: [
          {
            key: "modelInput",
            label: "模型输入",
            value: "128,000",
            displayValue: "128k",
            meta: "128,000 / 200,000 · 64%",
            title: "模型输入 128,000",
            percent: 64,
            tone: "modelInput",
          },
        ],
        onOpenCacheDetail: () => undefined,
      }),
    );

    expect(html).toContain(">128k</span>");
    expect(html).toContain("128,000 / 200,000");
    expect(html).toContain('aria-label="模型输入 128,000. 128,000 / 200,000 · 64%"');
  });
});
