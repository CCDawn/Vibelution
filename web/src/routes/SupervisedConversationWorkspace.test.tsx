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
  it("uses the available workspace width even inside a wide application window", async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const rect = originalRect.call(this);
      return this.dataset.vuiRegion === "supervised-conversation-workspace" ? { ...rect, width: 760 } as DOMRect : rect;
    });
    const container = renderWorkspace();
    expect(container.querySelector('aside[aria-label="运行导航"]')).toBeNull();
    expect(container.textContent).toContain("Native Agent conversation");
    await clickAndFlush(buttonByText(container, "证据"));
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Changed files evidence");
    expect(container.querySelector('aside[aria-label="运行证据"]')).toBeNull();
  });

  it("temporarily closes the context rail to preserve conversation width beside evidence", async () => {
    setViewport(1000);
    const container = renderWorkspace();
    expect(container.querySelector('aside[aria-label="运行导航"]')).not.toBeNull();
    await clickAndFlush(buttonByText(container, "证据"));
    expect(container.querySelector('aside[aria-label="运行导航"]')).toBeNull();
    expect(container.querySelector('aside[aria-label="运行证据"]')).not.toBeNull();
    await clickAndFlush(container.querySelector('button[aria-label="关闭证据"]')!);
    expect(container.querySelector('aside[aria-label="运行导航"]')).not.toBeNull();
  });
  it("keeps run context in the left rail and phase/agent selection in the topbar", async () => {
    const onSelectStep = vi.fn();
    const container = renderWorkspace({ onSelectStep });
    const rail = container.querySelector('aside[aria-label="运行导航"]')!;
    expect(rail.textContent).toContain("20 个样本 · 人工审批");
    expect(container.querySelector('header button[aria-label="进化阶段"]')).not.toBeNull();
    expect(container.querySelector('header button[aria-label="评估集"]')).toBeNull();
    expect(buttonByText(rail, "复跑评分").disabled).toBe(true);
    await clickAndFlush(buttonByText(rail, "基线评测"));
    expect(onSelectStep).toHaveBeenCalledWith("baseline");
    await clickAndFlush(container.querySelector('button[aria-label="运行导航"]')!);
    expect(container.querySelector('aside[aria-label="运行导航"]')).toBeNull();
    expect(container.textContent).toContain("Native Agent conversation");
  });

  it("opens mobile context on demand and closes it after a phase is selected", async () => {
    setViewport(390);
    const onSelectStep = vi.fn();
    const container = renderWorkspace({ onSelectStep });
    expect(document.body.querySelector('aside[aria-label="运行导航"]')).toBeNull();
    await clickAndFlush(container.querySelector('button[aria-label="运行导航"]')!);
    const dialog = document.body.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain("20 个样本 · 人工审批");
    await clickAndFlush(buttonByText(dialog, "基线评测"));
    expect(onSelectStep).toHaveBeenCalledWith("baseline");
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    expect(container.textContent).toContain("Native Agent conversation");
  });

  it("routes phase, dataset, and new-run actions to their owners", async () => {
    const container = renderWorkspace();

    const phaseSelect = container.querySelector<HTMLButtonElement>('button[aria-label="进化阶段"]');
    expect(phaseSelect).not.toBeNull();
    await clickAndFlush(phaseSelect!);
    const baselineOption = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]'))
      .find((option) => option.textContent?.includes("基线评测"));
    expect(baselineOption).not.toBeUndefined();
    await clickAndFlush(baselineOption!);
    await clickAndFlush(container.querySelector('button[aria-label="评估集"]')!);
    await clickAndFlush(buttonByText(container, "新建"));

    expect(defaultProps.onSelectStep).toHaveBeenCalledWith("baseline");
    expect(defaultProps.onSource).toHaveBeenCalledOnce();
    expect(defaultProps.onNew).toHaveBeenCalledOnce();
    expect(container.querySelector('[data-vui-layout-id="evolution"]')).not.toBeNull();
    expect(container.querySelector("header")?.className).toContain("grid-rows-[48px]");
  });

  it("opens evidence beside the transcript and exposes the optional full-conversation action", async () => {
    const onOpenConversation = vi.fn();
    const container = renderWorkspace({ onOpenConversation });

    await clickAndFlush(buttonByText(container, "证据"));
    expect(container.querySelector('[data-vui="split-aside"]')?.textContent).toContain("Changed files evidence");
    expect(container.querySelector('[data-vui="split-main"]')?.textContent).toContain("Native Agent conversation");

    const close = container.querySelector<HTMLButtonElement>('button[aria-label="关闭证据"]');
    expect(close).not.toBeNull();
    await clickAndFlush(close!);
    expect(container.querySelector('[data-vui="split-aside"]')).toBeNull();

    await openDropdown(buttonByText(container, "更多"));
    const fullConversation = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((item) => item.textContent?.includes("打开完整会话"));
    expect(fullConversation).not.toBeUndefined();
    await clickAndFlush(fullConversation!);
    expect(onOpenConversation).toHaveBeenCalledOnce();
  });

  it("keeps the mobile transcript in place while evidence opens as a VDialog drawer", async () => {
    setViewport(390);
    const container = renderWorkspace();

    await clickAndFlush(buttonByText(container, "证据"));

    expect(container.querySelector('[data-vui="split-aside"]')).toBeNull();
    expect(container.querySelector('[data-vui="split-main"]')?.textContent).toContain("Native Agent conversation");
    const dialog = document.body.querySelector<HTMLElement>('[data-vui="dialog-content"]');
    expect(dialog?.getAttribute("role")).toBe("dialog");
    expect(dialog?.querySelector('[data-slot="dialog-title"]')?.textContent).toBe("运行证据");
    expect(dialog?.className).toContain("!translate-none");
    expect(dialog?.className).toContain("!transform-none");
    expect(dialog?.className).toContain("!top-0");
    expect(dialog?.className).toContain("!h-[100dvh]");
    expect(dialog?.textContent).toContain("Changed files evidence");
    expect(container.querySelector("header")?.className).toContain("!grid-rows-[44px_44px]");
  });

  it("replaces the conversation with setup and keeps cancel ownership inside that slot", () => {
    const container = renderWorkspace({ setupOpen: true });

    expect(container.textContent).toContain("New supervised run setup");
    expect(container.textContent).not.toContain("Native Agent conversation");
    expect(container.querySelector('[role="toolbar"]')?.textContent).toContain("更多");
    expect(container.querySelector('[role="toolbar"]')?.textContent).not.toContain("新建");
    expect(container.querySelector('[data-vui="split-aside"]')).toBeNull();
  });

  it("keeps phase controls out of the empty state and disables evidence without a run", () => {
    const container = renderWorkspace({ hasRun: false });

    expect(container.querySelector('button[aria-label="进化阶段"]')).toBeNull();
    expect(buttonByText(container, "证据").disabled).toBe(true);
    expect(container.querySelector('[data-has-run="false"]')).not.toBeNull();
  });

  it("switches evolution tracks through VTabs and keeps both run groups visible in setup", async () => {
    const onTrackChange = vi.fn();
    const onSelectSelfRun = vi.fn();
    const container = renderWorkspace({
      activeTrack: "supervised",
      onTrackChange,
      trackAvailability: { supervised: true, self: true },
      setupOpen: true,
      setupTitle: "开始自进化",
      runGroups: [
        {
          id: "supervised",
          label: "监督进化",
          runs: [
            { id: "supervised-1", title: "溯源质量改进", status: "运行中 · 自改", selected: true, onSelect: vi.fn() },
          ],
        },
        {
          id: "self",
          label: "自进化",
          runs: [
            { id: "self-1", title: "减少重复重试", status: "待审查", selected: false, onSelect: onSelectSelfRun },
          ],
        },
      ],
      trackContext: <div>目标：降低重复重试</div>,
    });

    const selfTrackTab = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'))
      .find((tab) => tab.textContent?.includes("自进化"));
    expect(selfTrackTab).toBeDefined();
    await selectTabAndFlush(selfTrackTab!);
    expect(onTrackChange).toHaveBeenCalledWith("self");
    expect(container.querySelector('button[aria-label="运行导航"]')).not.toBeNull();
    expect(container.textContent).toContain("开始自进化");
    expect(container.textContent).toContain("溯源质量改进");
    expect(container.textContent).toContain("减少重复重试");
    expect(container.textContent).toContain("目标：降低重复重试");

    await clickAndFlush(buttonByText(container, "减少重复重试"));
    expect(onSelectSelfRun).toHaveBeenCalledOnce();
  });

  it("shows empty run groups on the left in an empty state and respects unavailable tracks", () => {
    const container = renderWorkspace({
      hasRun: false,
      activeTrack: "supervised",
      onTrackChange: vi.fn(),
      trackAvailability: { supervised: true, self: false },
      runGroups: [
        { id: "supervised", label: "监督进化", runs: [] },
        { id: "self", label: "自进化", runs: [] },
      ],
    });

    const navigation = container.querySelector('aside[aria-label="运行导航"]');
    expect(navigation?.textContent).toContain("监督进化");
    expect(navigation?.textContent).toContain("自进化");
    expect(navigation?.textContent).toContain("暂无运行");
    expect(container.querySelector('button[aria-label="进化阶段"]')).toBeNull();
    expect(buttonByText(container, "证据").disabled).toBe(true);
    const selfTrackTab = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'))
      .find((tab) => tab.textContent?.includes("自进化"));
    expect(selfTrackTab?.getAttribute("data-disabled")).not.toBeNull();
  });
});
