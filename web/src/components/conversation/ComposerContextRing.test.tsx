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
async function click(text: string) {
  const button = [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
  expect(button).toBeTruthy();
  await act(() => button!.click());
}
const model = buildComposerContextRingModel({
  usageUsed: 85000,
  usageLimit: 1000000,
  hitPercent: 99.9,
  lang: "zh",
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
});
describe("ComposerContextRing", () => {
  it("shows capacity and no inferred cache rate", async () => {
    await render(<ComposerContextRingPanel model={model} lang="zh" />);
    expect(
      document
        .querySelector('[role="progressbar"]')
        ?.getAttribute("aria-valuenow"),
    ).toBe("8.5");
    expect(document.body.textContent).toContain("暂无上游数据");
    expect(document.body.textContent).not.toContain("99.9%");
    expect(document.body.textContent).not.toContain("历史内容预览");
    expect(document.body.textContent).toContain("对话历史");
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
