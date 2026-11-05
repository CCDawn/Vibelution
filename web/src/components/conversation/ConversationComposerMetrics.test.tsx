// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildComposerContextRingModel } from "../../routes/chat/composerContextModel";
import type { ComposerCacheUsageModel } from "./composerCacheUsageModel";
import { ConversationComposerMetrics } from "./ConversationComposerMetrics";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let container: HTMLDivElement;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  container?.remove();
});

const contextModel = buildComposerContextRingModel({
  usageUsed: 64_000, usageLimit: 128_000, hitPercent: 63,
  cacheSource: "provider_usage", cacheUsageObserved: true, cachedInputTokens: 40_000,
  tokensPerSecond: 38.4, detailAvailable: true, lang: "zh",
  segments: [{ key: "history", label: "历史", tokens: 60_000, contentPreview: "历史内容预览" }],
});
const cacheUsage: ComposerCacheUsageModel = {
  state: "partial", sessionPercent: 55, lastCallPercent: 25,
  observedCalls: 3, totalCalls: 4, updating: true,
};

async function renderMetrics(props: Partial<React.ComponentProps<typeof ConversationComposerMetrics>> = {}) {
  if (!root) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  }
  await act(async () => root!.render(
    <ConversationComposerMetrics sessionId="session-a" lang="zh"
      contextModel={contextModel} cacheUsage={cacheUsage} {...props} />,
  ));
  return container.querySelector<HTMLButtonElement>('button[data-testid="conversation-composer-metrics-trigger"]');
}

async function clickByText(text: string) {
  const button = [...document.querySelectorAll<HTMLButtonElement>("button")]
    .find(node => node.textContent === text);
  expect(button).toBeTruthy();
  await act(async () => button!.click());
}

describe("ConversationComposerMetrics", () => {
  it("keeps one quiet entry while preserving context, last-call evidence, session rates and diagnostics", async () => {
    const onOpenContextDetail = vi.fn();
    const trigger = await renderMetrics({ onOpenContextDetail });
    expect(container.querySelectorAll("button")).toHaveLength(1);
    expect(trigger?.textContent).toBe("");
    expect(document.querySelector('[role="progressbar"]')).toBeNull();
    await act(async () => trigger!.click());
    expect(document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow")).toBe("50");
    expect(document.querySelector('[data-composer-context-cache="true"]')?.textContent).toContain("已复用 63% · 40K tokens");
    expect(document.querySelector('[data-composer-context-speed="true"]')?.textContent).toContain("38.4 tok/s");
    const sessionCache = document.querySelector('[data-composer-session-cache="true"]')!;
    expect([...sessionCache.querySelectorAll("dt")].map(node => node.textContent)).toEqual(["本会话", "最近一次"]);
    expect([...sessionCache.querySelectorAll("dd")].map(node => node.textContent)).toEqual(["55%", "25%"]);
    expect(sessionCache.textContent).toContain("3/4 次调用已上报");
    expect(sessionCache.textContent).toContain("本轮统计中");
    await clickByText("查看完整明细");
    await clickByText("查看缓存诊断");
    expect(onOpenContextDetail).toHaveBeenCalledOnce();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("supports cache-only hosts without inventing context measurements", async () => {
    const trigger = await renderMetrics({ contextModel: null, lang: "en" });
    expect(trigger?.getAttribute("aria-label")).toBe("Context and cache usage");
    await act(async () => trigger!.click());
    expect(document.querySelector('[role="progressbar"]')).toBeNull();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Cache hit rate");
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("3/4 calls reported");
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Updating this turn");
  });

  it("keeps diagnostics reachable when context has no source breakdown", async () => {
    const onOpenContextDetail = vi.fn();
    const trigger = await renderMetrics({
      contextModel: { ...contextModel, groups: [], segments: [] },
      cacheUsage: null, onOpenContextDetail,
    });
    await act(async () => trigger!.click());
    await clickByText("查看缓存诊断");
    expect(onOpenContextDetail).toHaveBeenCalledOnce();
  });

  it("restores keyboard focus on Escape and resets the open panel when the session changes", async () => {
    const trigger = await renderMetrics();
    trigger!.focus();
    await act(async () => trigger!.click());
    await vi.waitFor(() => expect(document.querySelector('[role="dialog"]')?.contains(document.activeElement)).toBe(true));
    await act(async () => {
      document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    });
    await vi.waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(trigger?.getAttribute("aria-expanded")).toBe("false");
    await act(async () => trigger!.click());
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
    await renderMetrics({ sessionId: "session-b" });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it.each(["missing", "not_called"] as const)("hides an empty entry for %s data", async state => {
    const emptyContext = buildComposerContextRingModel({
      usageUsed: 0, usageLimit: 0, hitPercent: 0, detailAvailable: false, segments: [], lang: "zh",
    });
    const trigger = await renderMetrics({
      contextModel: emptyContext,
      cacheUsage: { state, sessionPercent: null, lastCallPercent: null, observedCalls: 0, totalCalls: 0, updating: false },
    });
    expect(trigger).toBeNull();
    expect(container.textContent).toBe("");
    await renderMetrics({ contextModel: null, cacheUsage: null });
    expect(container.querySelector("button")).toBeNull();
  });

  it.each([
    ["loading", "读取中"], ["error", "暂时无法读取"], ["missing", "上游未提供数据"],
  ] as const)("preserves %s status without presenting missing rates as zero", async (state, message) => {
    const trigger = await renderMetrics({ contextModel: null, cacheUsage: {
      state, sessionPercent: null, lastCallPercent: null, observedCalls: 0,
      totalCalls: state === "missing" ? 1 : 0, updating: false,
    } });
    await act(async () => trigger!.click());
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain(message);
    expect(document.querySelector('[role="dialog"]')?.textContent).not.toContain("0%");
  });
});
