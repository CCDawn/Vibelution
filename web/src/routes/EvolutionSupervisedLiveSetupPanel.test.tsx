/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EvolutionSupervisedLiveSetupPanel,
  type EvolutionSupervisedLiveSetupPanelProps,
} from "./EvolutionSupervisedLiveSetupPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const baseProps: EvolutionSupervisedLiveSetupPanelProps = {
  lang: "zh",
  sourceKind: "dataset",
  selectedSourceValue: "dataset:webarena",
  sourceOptions: [
    {
      value: "dataset:webarena",
      label: "WebArena",
      kind: "dataset",
      caseCount: 120,
      detail: "Browser task dataset registered in the workbench.",
      status: "可运行",
    },
    {
      value: "bundle:terminal-bench",
      label: "Terminal-Bench",
      kind: "bundle",
      caseCount: 24,
      detail: "Terminal benchmark bundle.",
    },
  ],
  onSourceValueChange: () => undefined,
  datasetLimitInput: "",
  datasetLimitInputRef: { current: null },
  onDatasetLimitChange: () => undefined,
  selectedSourceLabel: "WebArena",
  selectedSourceStatusText: "Browser task dataset registered in the workbench.",
  selectedSourceEvaluationText: "Vibelution 自定义评分；非官方成绩",
  selectedSourceKindLabel: "数据集",
  selectedSourceCaseText: "120 cases",
  selectedSourceOfficialWarning: "当前评分不是官方基准成绩。",
  showMissingBundleError: false,
  approvalMode: "human",
  onApprovalModeChange: () => undefined,
  supervisedMentalModelMode: "follow",
  onMentalModelModeChange: () => undefined,
  startDisabled: false,
  startPendingVisual: false,
  startLabel: "开始监督运行",
  startTooltip: "启动监督运行",
  caseLimitLabel: "样本上限",
  caseLimitHint: "留空表示使用全部用例。",
  mentalModeLabel: "心智模型",
  mentalModeHint: "控制心智模型设置。",
  mentalModeFollowLabel: "跟随 Agent",
  mentalModeEnabledLabel: "启用",
  mentalModeDisabledLabel: "停用",
  showRunningLock: false,
  onStart: () => undefined,
};

describe("EvolutionSupervisedLiveSetupPanel", () => {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    root = null;
    host = null;
  });

  it("shows real datasets and bundles with selected evaluation metadata and persistent actions", () => {
    const markup = renderToStaticMarkup(
      <EvolutionSupervisedLiveSetupPanel {...baseProps} onCancel={() => undefined} />,
    );

    expect(markup).toContain("新建监督运行");
    expect(markup).toContain("选择评测来源");
    expect(markup).toContain("WebArena");
    expect(markup).toContain("Terminal-Bench");
    expect(markup).toContain("120 个用例");
    expect(markup).toContain("Vibelution 自定义评分；非官方成绩");
    expect(markup).toContain("当前评分不是官方基准成绩。");
    expect(markup).toContain("取消");
    expect(markup).toContain("开始监督运行");
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).not.toContain("样本预览");
  });

  it("filters the real source list, keeps advanced options available, and preserves callbacks", () => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    const onSourceValueChange = vi.fn();
    const onCancel = vi.fn();
    const onStart = vi.fn();

    act(() => {
      root?.render(
        <EvolutionSupervisedLiveSetupPanel
          {...baseProps}
          onSourceValueChange={onSourceValueChange}
          onCancel={onCancel}
          onStart={onStart}
        />,
      );
    });

    const search = host.querySelector<HTMLInputElement>('input[aria-label="搜索评测集和评测包"]');
    expect(search).not.toBeNull();
    act(() => {
      if (!search) return;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(search, "Terminal");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(host.textContent).toContain("Terminal-Bench");
    expect(host.querySelector('button[data-source-value="dataset:webarena"]')).toBeNull();

    const bundleOption = host.querySelector<HTMLButtonElement>('button[data-source-value="bundle:terminal-bench"]');
    expect(bundleOption).not.toBeNull();
    act(() => bundleOption?.click());
    expect(onSourceValueChange).toHaveBeenCalledWith("bundle:terminal-bench");

    const advancedToggle = host.querySelector<HTMLButtonElement>('button[aria-controls="supervised-run-advanced-settings"]');
    expect(advancedToggle).not.toBeNull();
    act(() => advancedToggle?.click());
    expect(host.textContent).toContain("最终审批方式");
    expect(host.textContent).toContain("心智模型");

    const cancelButton = Array.from(host.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button.textContent?.includes("取消"));
    const startButton = Array.from(host.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button.textContent?.includes("开始监督运行"));
    act(() => {
      cancelButton?.click();
      startButton?.click();
    });
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onStart).toHaveBeenCalledOnce();
  });

  it.each(["0", "-1", "1.5", "121", "not-a-number"])("blocks invalid sample limit %s before submitting", (limit) => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    const onStart = vi.fn();
    act(() => root?.render(<EvolutionSupervisedLiveSetupPanel {...baseProps} datasetLimitInput={limit} onStart={onStart} />));
    const start = Array.from(host.querySelectorAll<HTMLButtonElement>("button")).find((button) => button.textContent?.includes("开始监督运行"));
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect(start?.disabled).toBe(true);
    act(() => start?.click());
    expect(onStart).not.toHaveBeenCalled();
  });

  it.each(["", "1", "120"])("allows valid sample limit %s", (limit) => {
    const markup = renderToStaticMarkup(<EvolutionSupervisedLiveSetupPanel {...baseProps} datasetLimitInput={limit} />);
    expect(markup).not.toContain('aria-invalid="true"');
    expect(markup).not.toContain('id="supervised-sample-limit-error"');
  });
});
