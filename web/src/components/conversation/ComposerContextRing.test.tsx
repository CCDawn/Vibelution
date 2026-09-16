/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildComposerContextRingModel } from "../../routes/chat/composerContextModel";
import {
  ComposerContextRing,
  ComposerContextRingPanel,
} from "./ComposerContextRing";
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => {
  if (root) await act(() => root.unmount());
  document.body.innerHTML = "";
});
async function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(() => root.render(element));
}
/** Each render appends a fresh host; scope queries to the newest one. */
function latestHost(): HTMLElement {
  return document.body.lastElementChild as HTMLElement;
}
function queryInLatestHost(selector: string): Element | null {
  return latestHost().querySelector(selector);
}
async function click(text: string) {
  const button = [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
  expect(button).toBeTruthy();
  await act(() => button!.click());
}
const modelFixtureOptions = {
  usageUsed: 85000,
  usageLimit: 1000000,
  hitPercent: 99.9,
  lang: "zh" as const,
  detailAvailable: true,
  segments: [
    {
      key: "history",
      label: "历史",
      tokens: 82000,
      status: "computed_hit",
      contentPreview: "历史内容预览",
    },
    { key: "agent_runtime", label: "规范", tokens: 388 },
  ],
};
const model = buildComposerContextRingModel(modelFixtureOptions);
describe("ComposerContextRing", () => {
  it("shows capacity and no inferred cache rate", async () => {
    await render(<ComposerContextRingPanel model={model} lang="zh" />);
    expect(
      document
        .querySelector('[role="progressbar"]')
        ?.getAttribute("aria-valuenow"),
    ).toBe("8.5");
    // Provider did not report cache usage: fail-open to an em-dash.
    expect(document.body.textContent).not.toContain("暂无上游数据");
    expect(
      document.querySelector('[data-composer-context-cache="true"]')
        ?.getAttribute("data-cache-state"),
    ).toBe("missing");
    expect(document.body.textContent).toContain("—");
    expect(document.body.textContent).not.toContain("99.9%");
    expect(document.body.textContent).not.toContain("历史内容预览");
    expect(document.body.textContent).toContain("对话历史");
  });
  it("marks generation speed as observed or missing", async () => {
    await render(<ComposerContextRingPanel model={model} lang="zh" />);
    const speedRow = queryInLatestHost('[data-composer-context-speed="true"]');
    expect(speedRow?.getAttribute("data-speed-state")).toBe("missing");
    expect(speedRow?.textContent).toContain("—");
    expect(latestHost().textContent).toContain("生成速度");
    const withSpeed = buildComposerContextRingModel({
      ...modelFixtureOptions,
      tokensPerSecond: 38.44,
    });
    await render(<ComposerContextRingPanel model={withSpeed} lang="zh" />);
    expect(
      queryInLatestHost('[data-composer-context-speed="true"]')
        ?.getAttribute("data-speed-state"),
    ).toBe("observed");
    expect(latestHost().textContent).toContain("38.4 tok/s");
  });
  it("renders the auto-compact countdown only when remaining drops below 40%", async () => {
    // usage 96% of a 1M window; threshold 620K leaves ~0 remaining → visible.
    const tight = buildComposerContextRingModel({
      ...modelFixtureOptions,
      usageUsed: 850000,
      autoCompactThresholdTokens: 620000,
    });
    await render(<ComposerContextRingPanel model={tight} lang="zh" />);
    expect(
      queryInLatestHost('[data-composer-context-auto-compact="true"]'),
    ).toBeTruthy();
    expect(latestHost().textContent).toContain("距自动压缩还剩");
    expect(latestHost().textContent).toContain("完整历史仍在");
    expect(latestHost().textContent).toContain("基于上次调用估算");
    // Plenty of room: the countdown must stay hidden (no resident noise).
    const relaxed = buildComposerContextRingModel({
      ...modelFixtureOptions,
      usageUsed: 85000,
      autoCompactThresholdTokens: 620000,
    });
    await render(<ComposerContextRingPanel model={relaxed} lang="zh" />);
    expect(
      queryInLatestHost('[data-composer-context-auto-compact="true"]'),
    ).toBeNull();
    // Threshold unknown (backend has none): never render a local guess.
    await render(<ComposerContextRingPanel model={model} lang="zh" />);
    expect(
      queryInLatestHost('[data-composer-context-auto-compact="true"]'),
    ).toBeNull();
  });
  it("shows observed cache reuse with absolute cached tokens", async () => {
    const observed = buildComposerContextRingModel({
      ...modelFixtureOptions,
      cacheSource: "provider_usage",
      cacheUsageObserved: true,
      cachedInputTokens: 55600,
      hitPercent: 63,
    });
    await render(<ComposerContextRingPanel model={observed} lang="zh" />);
    const cacheRow = queryInLatestHost('[data-composer-context-cache="true"]');
    expect(cacheRow?.getAttribute("data-cache-state")).toBe("observed");
    expect(cacheRow?.textContent).toContain("已复用 63% · 56K tokens");
  });
  it("opens source details and existing cache diagnostics", async () => {
    const onOpenDetail = vi.fn();
    await render(
      <ComposerContextRingPanel
        model={model}
        lang="zh"
        onOpenDetail={onOpenDetail}
      />,
    );
    await click("查看完整明细");
    await click("对话历史");
    expect(document.body.textContent).toContain("历史内容预览");
    await click("查看缓存诊断");
    expect(onOpenDetail).toHaveBeenCalledOnce();
    await click("上下文明细");
    expect(document.body.textContent).not.toContain("历史内容预览");
  });
  it("closes and resets when switching sessions", async () => {
    await render(
      <ComposerContextRing model={model} lang="zh" sessionId="one" />,
    );
    await act(() =>
      document
        .querySelector<HTMLButtonElement>('button[data-session="one"]')!
        .click(),
    );
    await click("查看完整明细");
    await click("对话历史");
    await act(() =>
      root.render(
        <ComposerContextRing model={model} lang="zh" sessionId="two" />,
      ),
    );
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await act(() =>
      document
        .querySelector<HTMLButtonElement>('button[data-session="two"]')!
        .click(),
    );
    expect(document.body.textContent).toContain("主要占用");
    expect(document.body.textContent).not.toContain("历史内容预览");
  });
  it("keeps an unknown capacity distinct from zero in English", async () => {
    const english = buildComposerContextRingModel({
      usageUsed: 85,
      usageLimit: 0,
      hitPercent: 0,
      lang: "en",
      detailAvailable: false,
      segments: [],
    });
    await render(<ComposerContextRingPanel model={english} lang="en" />);
    expect(document.body.textContent).toContain("Window limit unknown");
    expect(
      document
        .querySelector('[role="progressbar"]')
        ?.hasAttribute("aria-valuenow"),
    ).toBe(false);
    expect(document.body.textContent).not.toContain("0%");
  });
});
