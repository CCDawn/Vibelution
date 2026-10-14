/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VuiProvider } from "../components/vui";
import {
  SupervisedConversationWorkspace,
  type SupervisedConversationWorkspaceProps,
} from "./SupervisedConversationWorkspace";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
let root: Root | null = null;

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: width,
  });
}

function buttonByText(container: ParentNode, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll<HTMLButtonElement>("button"))
    .find((candidate) => candidate.textContent?.includes(text));
  if (!button) throw new Error(`button not found: ${text}`);
  return button;
}

const defaultProps: SupervisedConversationWorkspaceProps = {
  lang: "zh" as const,
  title: "研究资料溯源质量改进",
  sourceLabel: "研究资料溯源 · 20 个样本",
  sourceSummary: "20 个样本 · 人工审批",
  phases: [
    { id: "baseline", label: "基线评测", statusLabel: "已完成", current: false },
    { id: "improve", label: "自改", statusLabel: "运行中", current: true },
    { id: "evaluate", label: "复跑评分", statusLabel: "待执行", current: false, disabled: true },
  ],
  selectedStepId: "improve",
  steps: [
    { id: "baseline", label: "基线评测" },
    { id: "improve", label: "自改" },
    { id: "evaluate", label: "复跑评分", disabled: true },
    { id: "approval", label: "审批与生效", disabled: true },
  ],
  onSelectStep: vi.fn(),
  showFollowLive: false,
  onFollowLive: vi.fn(),
  onNew: vi.fn(),
  onSource: vi.fn(),
  onHistory: vi.fn(),
  onLibrary: vi.fn(),
  onSettings: vi.fn(),
  setupOpen: false,
  setup: <div>New supervised run setup</div>,
  conversation: <div>Native Agent conversation</div>,
  footer: <div>Approval and run state</div>,
  evidenceTabs: [
    { id: "changes", label: "改动", content: <div>Changed files evidence</div> },
    { id: "scores", label: "评分", content: <div>Evaluation score evidence</div> },
    { id: "progress", label: "进度", content: <div>Run progress evidence</div> },
  ],
  hasRun: true,
};

function renderWorkspace(overrides: Partial<SupervisedConversationWorkspaceProps> = {}) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(
      <VuiProvider>
        <SupervisedConversationWorkspace {...defaultProps} {...overrides} />
      </VuiProvider>,
    );
  });
  return host;
}

async function clickAndFlush(button: HTMLElement) {
  await act(async () => {
    button.click();
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
  });
}

async function selectTabAndFlush(tab: HTMLElement) {
  await act(async () => {
    tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0, ctrlKey: false }));
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
  });
}

async function openDropdown(button: HTMLElement) {
  await act(async () => {
    button.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  setViewport(1280);
});

afterEach(async () => {
  if (root) {
    await act(async () => {
      root?.unmount();
    });
  }
  host?.remove();
  root = null;
  host = null;
  document.body.style.overflow = "";
  vi.restoreAllMocks();
});

describe("SupervisedConversationWorkspace interactions", () => {
  it("keeps results and current actions visible beside the native conversation on desktop", () => {
    const container = renderWorkspace({ resultSummary: <div>Real candidate summary</div> });
    const main = container.querySelector('[data-vui="split-main"]')!;
    const result = container.querySelector('aside[aria-label="结果与操作"]')!;
    expect(main.textContent).toContain("Native Agent conversation");
    expect(main.textContent).not.toContain("Approval and run state");
    expect(result.textContent).toContain("Approval and run state");
    expect(result.textContent).toContain("Real candidate summary");
    expect(result.textContent).toContain("20 个样本 · 人工审批");
    expect(container.querySelector('[data-vui-layout-id="evolution"]')).not.toBeNull();
    expect(container.querySelector('header button[aria-label="结果与操作"]')).toBeNull();
  });

  it("keeps result actions visible when selecting another evidence tab", async () => {
    const container = renderWorkspace();
    const result = container.querySelector('aside[aria-label="结果与操作"]')!;
    const changes = Array.from(result.querySelectorAll<HTMLElement>('[role="tab"]')).find(tab => tab.textContent === "改动")!;
    await selectTabAndFlush(changes);
    expect(result.textContent).toContain("Changed files evidence");
    expect(result.textContent).toContain("Approval and run state");
    expect(container.querySelector('[data-vui="split-main"]')?.textContent).toContain("Native Agent conversation");
  });

  it("moves source and phase context to the right and leaves the left rail for runs", async () => {
    const onSelectStep = vi.fn();
    const container = renderWorkspace({ onSelectStep });
    const left = container.querySelector('aside[aria-label="运行导航"]')!;
    const result = container.querySelector('aside[aria-label="结果与操作"]')!;
    expect(left.textContent).not.toContain("20 个样本");
    expect(left.textContent).not.toContain("基线评测");
    expect(result.textContent).toContain("20 个样本");
    expect(buttonByText(result, "复跑评分").disabled).toBe(true);
    await clickAndFlush(buttonByText(result, "基线评测"));
    expect(onSelectStep).toHaveBeenCalledWith("baseline");
    expect(container.querySelector('[data-vui="split-main"] button[aria-label="进化阶段"]')).not.toBeNull();
  });

  it("uses container width for responsive result access without removing the transcript", async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const rect = originalRect.call(this);
      return this.dataset.vuiRegion === "supervised-conversation-workspace" ? { ...rect, width: 760 } as DOMRect : rect;
    });
    const container = renderWorkspace();
    expect(container.querySelector('aside[aria-label="结果与操作"]')).toBeNull();
    await clickAndFlush(buttonByText(container, "结果与操作"));
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain("Approval and run state");
    expect(dialog.textContent).toContain("20 个样本");
    expect(container.querySelector('[data-vui="split-main"]')?.textContent).toContain("Native Agent conversation");
  });

  it("keeps the right column permanent at medium desktop widths and makes navigation a drawer", async () => {
    setViewport(1000);
    const container = renderWorkspace();
    expect(container.querySelector('aside[aria-label="运行导航"]')).toBeNull();
    expect(container.querySelector('aside[aria-label="结果与操作"]')).not.toBeNull();
    await clickAndFlush(container.querySelector('button[aria-label="运行导航"]')!);
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("运行历史");
    expect(container.querySelector('[data-vui="split-main"]')?.textContent).toContain("Native Agent conversation");
  });

  it("routes phase, source and new-run actions to their existing owners", async () => {
    const container = renderWorkspace();
    await clickAndFlush(container.querySelector<HTMLButtonElement>('button[aria-label="进化阶段"]')!);
    const option = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]')).find(item => item.textContent?.includes("基线评测"))!;
    await clickAndFlush(option);
    await clickAndFlush(container.querySelector('button[aria-label="评估集"]')!);
    await clickAndFlush(buttonByText(container.querySelector('[role="toolbar"]')!, "新建"));
    expect(defaultProps.onSelectStep).toHaveBeenCalledWith("baseline");
    expect(defaultProps.onSource).toHaveBeenCalledOnce();
    expect(defaultProps.onNew).toHaveBeenCalledOnce();
  });

  it("keeps the optional full conversation in the existing more menu", async () => {
    const onOpenConversation = vi.fn();
    const container = renderWorkspace({ onOpenConversation });
    await openDropdown(buttonByText(container, "更多"));
    const item = Array.from(document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')).find(item => item.textContent?.includes("打开完整会话"))!;
    await clickAndFlush(item);
    expect(onOpenConversation).toHaveBeenCalledOnce();
  });

  it("places setup in the right column and provides a clear central explanation", () => {
    const container = renderWorkspace({ setupOpen: true });
    expect(container.querySelector('[data-vui="split-aside"]')?.textContent).toContain("New supervised run setup");
    expect(container.querySelector('[data-vui="split-main"]')?.textContent).toContain("先确认目标，再看进化过程");
    expect(container.textContent).not.toContain("Native Agent conversation");
  });

  it("opens setup on mobile and exposes a fixed result entry", () => {
    setViewport(390);
    const container = renderWorkspace({ setupOpen: true });
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("New supervised run setup");
    expect(container.querySelector('[data-vui="split-main"]')?.textContent).toContain("结果与操作");
  });

  it("keeps empty-run settings accessible without displaying nonexistent phases", () => {
    const container = renderWorkspace({ hasRun: false });
    expect(container.querySelector('button[aria-label="进化阶段"]')).toBeNull();
    expect(container.querySelector('aside[aria-label="结果与操作"]')?.textContent).toContain("运行配置");
    expect(container.querySelector('[data-has-run="false"]')).not.toBeNull();
  });

  it("shows only the active track's run list and preserves track switching", async () => {
    const onTrackChange = vi.fn();
    const container = renderWorkspace({ activeTrack: "supervised", onTrackChange, runGroups: [
      { id: "supervised", label: "监督进化", runs: [{ id: "s", title: "监督目标", status: "运行中", selected: true, onSelect: vi.fn() }] },
      { id: "self", label: "自进化", runs: [{ id: "a", title: "自进化目标", status: "待审查", selected: false, onSelect: vi.fn() }] },
    ] });
    const rail = container.querySelector('aside[aria-label="运行导航"]')!;
    expect(rail.textContent).toContain("监督目标");
    expect(rail.textContent).not.toContain("自进化目标");
    const tab = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]')).find(item => item.textContent === "自进化")!;
    await selectTabAndFlush(tab);
    expect(onTrackChange).toHaveBeenCalledWith("self");
  });

  it("respects unavailable tracks without hiding the active empty list", () => {
    const container = renderWorkspace({ hasRun: false, activeTrack: "supervised", onTrackChange: vi.fn(), trackAvailability: { supervised: true, self: false }, runGroups: [
      { id: "supervised", label: "监督进化", runs: [] }, { id: "self", label: "自进化", runs: [] },
    ] });
    expect(container.querySelector('aside[aria-label="运行导航"]')?.textContent).toContain("暂无运行");
    const tab = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]')).find(item => item.textContent === "自进化")!;
    expect(tab.getAttribute("data-disabled")).not.toBeNull();
  });

  it("keeps active and pending-approval runs visible while history starts collapsed", () => {
    const container = renderWorkspace({
      runGroups: [{
        id: "supervised",
        label: "监督进化",
        runs: [
          { id: "running", title: "正在运行的任务", status: "运行中", selected: false, history: false, onSelect: vi.fn() },
          { id: "approval", title: "等待审批的任务", status: "待审批", selected: false, history: false, onSelect: vi.fn() },
          { id: "old", title: "较早的失败任务", status: "失败", selected: false, history: true, onSelect: vi.fn() },
        ],
      }],
    });
    const rail = container.querySelector('aside[aria-label="运行导航"]')!;
    const historyToggle = buttonByText(rail, "历史记录");

    expect(buttonByText(rail, "正在运行的任务")).toBeDefined();
    expect(buttonByText(rail, "等待审批的任务")).toBeDefined();
    expect(historyToggle.getAttribute("aria-expanded")).toBe("false");
    expect(rail.querySelector("#evolution-history-supervised")?.hasAttribute("hidden")).toBe(true);
    expect(rail.querySelector('#evolution-history-supervised button[aria-current="page"]')).toBeNull();
  });

  it("keeps a selected terminal run visible outside the collapsed history list", () => {
    const container = renderWorkspace({
      runGroups: [{
        id: "supervised",
        label: "监督进化",
        runs: [
          { id: "selected-old", title: "当前选中的已完成任务", status: "已完成", selected: true, history: true, onSelect: vi.fn() },
          { id: "other-old", title: "其他历史任务", status: "失败", selected: false, history: true, onSelect: vi.fn() },
        ],
      }],
    });
    const rail = container.querySelector('aside[aria-label="运行导航"]')!;

    expect(buttonByText(rail, "当前选中的已完成任务").getAttribute("aria-current")).toBe("page");
    expect(rail.querySelector("#evolution-history-supervised")?.textContent).not.toContain("当前选中的已完成任务");
    expect(rail.querySelector("#evolution-history-supervised")?.hasAttribute("hidden")).toBe(true);
  });

  it("expands the first five history entries and routes the all-history action to the group", async () => {
    const onGroupHistory = vi.fn();
    const onWorkspaceHistory = vi.fn();
    const runs = Array.from({ length: 7 }, (_, index) => ({
      id: `history-${index + 1}`,
      title: `历史任务 ${index + 1}`,
      status: "失败",
      selected: false,
      history: true,
      onSelect: vi.fn(),
    }));
    const container = renderWorkspace({
      onHistory: onWorkspaceHistory,
      runGroups: [{ id: "supervised", label: "监督进化", runs, onHistory: onGroupHistory }],
    });
    const rail = container.querySelector('aside[aria-label="运行导航"]')!;
    const historyToggle = buttonByText(rail, "历史记录");

    await clickAndFlush(historyToggle);
    expect(historyToggle.getAttribute("aria-expanded")).toBe("true");
    expect(buttonByText(rail, "历史任务 1")).toBeDefined();
    expect(buttonByText(rail, "历史任务 5")).toBeDefined();
    expect(rail.querySelector("#evolution-history-supervised")?.textContent).not.toContain("历史任务 6");
    expect(rail.querySelector("#evolution-history-supervised")?.textContent).not.toContain("历史任务 7");

    await clickAndFlush(buttonByText(rail, "查看全部历史（7）"));
    expect(onGroupHistory).toHaveBeenCalledOnce();
    expect(onWorkspaceHistory).not.toHaveBeenCalled();
  });

  it("falls back to the workspace history action when a group has no history handler", async () => {
    const onHistory = vi.fn();
    const runs = Array.from({ length: 6 }, (_, index) => ({
      id: `history-${index + 1}`,
      title: `历史任务 ${index + 1}`,
      status: "失败",
      selected: false,
      history: true,
      onSelect: vi.fn(),
    }));
    const container = renderWorkspace({
      onHistory,
      runGroups: [{ id: "supervised", label: "监督进化", runs }],
    });
    const rail = container.querySelector('aside[aria-label="运行导航"]')!;

    await clickAndFlush(buttonByText(rail, "历史记录"));
    await clickAndFlush(buttonByText(rail, "查看全部历史（6）"));
    expect(onHistory).toHaveBeenCalledOnce();
  });

  it("keeps history expansion isolated per group and allows it to be collapsed again", async () => {
    const container = renderWorkspace({
      activeTrack: undefined,
      onTrackChange: vi.fn(),
      runGroups: [
        {
          id: "supervised",
          label: "监督进化",
          runs: [{ id: "s-old", title: "监督历史任务", status: "失败", selected: false, history: true, onSelect: vi.fn() }],
        },
        {
          id: "self",
          label: "自进化",
          runs: [{ id: "self-old", title: "自进化历史任务", status: "完成", selected: false, history: true, onSelect: vi.fn() }],
        },
      ],
    });
    const rail = container.querySelector('aside[aria-label="运行导航"]')!;
    const toggles = Array.from(rail.querySelectorAll<HTMLButtonElement>("button[aria-expanded]"));
    expect(toggles).toHaveLength(2);

    await clickAndFlush(toggles[0]);
    expect(toggles[0].getAttribute("aria-expanded")).toBe("true");
    expect(rail.querySelector("#evolution-history-supervised")?.hasAttribute("hidden")).toBe(false);
    expect(rail.querySelector("#evolution-history-self")?.hasAttribute("hidden")).toBe(true);
    await clickAndFlush(toggles[0]);
    expect(toggles[0].getAttribute("aria-expanded")).toBe("false");
    expect(rail.querySelector("#evolution-history-supervised")?.hasAttribute("hidden")).toBe(true);
  });

  it("remembers the desktop navigation pane visibility after remount", async () => {
    const container = renderWorkspace();
    await clickAndFlush(container.querySelector('button[aria-label="运行导航"]')!);
    expect(container.querySelector('aside[aria-label="运行导航"]')).toBeNull();

    await act(async () => { root?.unmount(); });
    host?.remove();
    root = null;
    host = null;

    const remounted = renderWorkspace();
    expect(remounted.querySelector('button[aria-label="运行导航"]')?.getAttribute("aria-expanded")).toBe("false");
    expect(remounted.querySelector('aside[aria-label="运行导航"]')).toBeNull();
  });
});
