// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import type { LauncherMaintenanceSummary, LauncherMaintenancePlan } from "../api/types";
import { LauncherProjectMaintenancePanel } from "./LauncherProjectMaintenancePanel";

const copy: ComponentProps<typeof LauncherProjectMaintenancePanel>["copy"] = {
  maintenanceActiveWorkPolicy: "有进行中的任务时不会执行。", maintenanceApply: "确认执行",
  maintenanceCleanStart: "清理", maintenanceEmptyItems: "无须清理", maintenanceEstimated: "预计释放",
  maintenanceFactoryRuntime: "恢复", maintenanceHint: "预览", maintenanceLoading: "正在读取",
  maintenanceOwnerLauncher: "Launcher", maintenancePanelTitle: "维护", maintenancePlanEmpty: "没有目标",
  maintenancePlanMissingForProfile: "请先预览", maintenancePlanProfileMismatch: "重新预览",
  maintenanceSummaryUnavailable: "维护清单读取失败", maintenancePlanReady: "预览就绪",
  maintenancePreview: "生成预览", maintenanceProfile: "范围", maintenanceTargets: "目标", maintenanceTitle: "维护",
};
const summary = { profiles: [{ id: "clean_start", itemIds: [] }], items: [] } as unknown as LauncherMaintenanceSummary;
const plan = { profileId: "clean_start", planId: "secret-id", planHash: "secret-hash", estimatedBytes: 5, targetCount: 1, preview: { items: [] } } as unknown as LauncherMaintenancePlan;
const base = { copy, maintenanceProfile: "clean_start" as const, plan, loading: false, error: false, retryLabel: "重试", onRetry: vi.fn(), previewPending: false, applyPending: false, onProfileChange: vi.fn(), onPreview: vi.fn(), onApply: vi.fn() };

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("maintenance summary state", () => {
  it("shows failure and retry without presenting empty or zero totals or allowing an old plan", () => {
    const html = renderToStaticMarkup(<LauncherProjectMaintenancePanel {...base} error />);
    expect(html).toContain("维护清单读取失败");
    expect(html).toContain("重试");
    expect(html).not.toContain("无须清理");
    expect(html).not.toContain("0 B");
    expect(html).not.toContain("预览就绪");
    expect(html).not.toContain("secret-id");
    expect(html.match(/维护清单读取失败/g)).toHaveLength(1);
    expect(html).not.toContain("生成预览");
    expect(html).not.toContain("确认执行");
    expect(html).not.toContain("范围");
  });
  it("only shows empty after a successful list", () => {
    const html = renderToStaticMarkup(<LauncherProjectMaintenancePanel {...base} summary={summary} />);
    expect(html).toContain("无须清理");
    expect(html).toContain("0 B");
    expect(html).not.toContain("维护清单读取失败");
    expect(html).not.toContain("预览就绪");
    expect(html).not.toContain("secret-id");
  });
  it("does not display totals while loading", () => {
    const html = renderToStaticMarkup(<LauncherProjectMaintenancePanel {...base} loading />);
    expect(html).toContain("正在读取");
    expect(html).not.toContain("0 B");
    expect(html).not.toContain("无须清理");
    expect(html.match(/正在读取/g)).toHaveLength(1);
    expect(html).not.toContain("生成预览");
    expect(html).not.toContain("确认执行");
    expect(html).not.toContain("重试");
  });
  it("retries with the supplied read-only action", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const retry = vi.fn();
    await act(async () => root.render(<LauncherProjectMaintenancePanel {...base} error onRetry={retry} />));
    const button = [...host.querySelectorAll("button")].find((element) => element.textContent?.includes("重试"));
    expect(button).toBeDefined();
    await act(async () => button?.click());
    expect(retry).toHaveBeenCalledOnce();
    expect(base.onApply).not.toHaveBeenCalled();
    await act(async () => root.unmount());
    host.remove();
  });
  it("hides cached data and stale actions when the refresh fails", () => {
    const html = renderToStaticMarkup(<LauncherProjectMaintenancePanel {...base} summary={summary} error />);
    expect(html.match(/维护清单读取失败/g)).toHaveLength(1);
    expect(html).toContain("重试");
    expect(html).not.toContain("无须清理");
    expect(html).not.toContain("0 B");
    expect(html).not.toContain("生成预览");
    expect(html).not.toContain("确认执行");
  });
  it("treats an incomplete item list as unknown rather than empty", () => {
    const incomplete = { ...summary, profiles: [{ id: "clean_start", itemIds: ["missing"] }] } as LauncherMaintenanceSummary;
    const html = renderToStaticMarkup(<LauncherProjectMaintenancePanel {...base} summary={incomplete} />);
    expect(html).toContain("维护清单读取失败");
    expect(html).not.toContain("无须清理");
    expect(html).not.toContain("0 B");
  });

  it("does not allow executing a preview with no targets", () => {
    const populated = { ...summary, profiles: [{ id: "clean_start", itemIds: ["cache"] }], items: [{ id: "cache", name: "缓存", size: "0 B", sizeBytes: 0, candidateCount: 0 }] } as unknown as LauncherMaintenanceSummary;
    const emptyPlan = { ...plan, targetCount: 0 };
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<LauncherProjectMaintenancePanel {...base} summary={populated} plan={emptyPlan} />);
    const apply = [...host.querySelectorAll("button")].find((button) => button.textContent?.includes("确认执行"));
    expect(apply?.disabled).toBe(true);
  });

});
