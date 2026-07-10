import { describe, expect, it } from "vitest";

import routeSource from "./KernelTaskCenterRoute.tsx?raw";
import styles from "./KernelTaskCenterRoute.styles";
import stylesSource from "./KernelTaskCenterRoute.styles.ts?raw";
import routerSource from "../app/router.tsx?raw";

function hasRealBackgroundToken(className: string) {
  return className
    .split(/\s+/)
    .some((token) => token.startsWith("bg-[") || token.startsWith("[background:"));
}

function expectBackgroundAware(className: string) {
  expect(hasRealBackgroundToken(className)).toBe(true);
  const backgroundTokens = className
    .split(/\s+/)
    .filter((token) => token.startsWith("bg-[") || token.startsWith("[background:"));
  expect(backgroundTokens.some((token) => token.includes("color-mix(in_srgb") && token.includes("transparent"))).toBe(true);
}

describe("KernelTaskCenterRoute layout contract", () => {
  it("routes Kernel task center controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).not.toMatch(/<button\b/);
  });

  it("maps Kernel task state and facts through shared VUI compositions", () => {
    expect(routeSource).toContain("VSurface");
    expect(routeSource).toContain("VMetricStrip");
    expect(routeSource).toContain("VStateSurface");
    expect(routeSource).toContain("VActionGroup");
    expect(routeSource).toContain('ariaLabel={copy.taskList}');
    expect(routeSource).toContain('ariaLabel={copy.detail}');
    expect(styles.taskRowClass).toContain("w-full");
    expect(styles.taskRowSelectedClass).toContain("border-");
  });

  it("is wired as a read-only kernel route", () => {
    expect(routerSource).toContain('path: "kernel"');
    expect(routerSource).toContain("<KernelTaskCenterRoute />");
    expect(routeSource).toContain("listKernelTasks(status, 120)");
    expect(routeSource).toContain("getKernelTaskTimeline(selectedTaskId)");
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain("selectKernelTaskId(tasks, requestedTaskId)");
    expect(routeSource).not.toContain("useMutation");
    expect(routeSource).not.toContain('method: "POST"');
  });

  it("shows TaskLedger authority and delivery/wake evidence", () => {
    expect(routeSource).toContain("timeline.readModel.truthSource");
    expect(routeSource).toContain("timeline.readModel.projection");
    expect(routeSource).toContain("copy.factAuthority");
    expect(routeSource).toContain("timeline.deliveries.map");
    expect(routeSource).toContain("delivery.wake?.wakeStatus");
    expect(routeSource).toContain("timeline.projectionRefs");
    expect(routeSource).toContain("timeline.runtimeEvidenceRefs");
  });

  it("keeps the route local and shell-language only", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const COPY = {");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("distinguishes a globally empty task list from a status-filtered empty result", () => {
    expect(routeSource).toContain('noMatchingTasks: "没有符合筛选条件的任务"');
    expect(routeSource).toContain('noMatchingTasks: "No tasks match this filter"');
    expect(routeSource).toContain("title={status ? copy.noMatchingTasks : copy.noTasks}");
  });

  it("keeps the route root background-aware", () => {
    expect(styles.routeClass).not.toContain("bg-[var(--surface-page)]");
    expect(styles.routeClass).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.routeClass).toContain("min-w-0");
    expect(styles.routeClass).toContain("max-w-full");
    expect(styles.routeClass).toContain("overflow-x-hidden");
    expectBackgroundAware(styles.headerClass);
    expect(styles.headerClass).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  });

  it("keeps repeated Kernel panels as light background-aware surfaces", () => {
    [
      styles.paneClass,
      styles.detailHeaderClass,
      styles.deliveryRowClass,
      styles.lifecycleSectionClass,
      styles.lifecycleRowClass,
      styles.emptyStateClass,
    ].forEach(expectBackgroundAware);

    [
      styles.paneClass,
      styles.detailHeaderClass,
      styles.lifecycleSectionClass,
    ].forEach((className) => {
      expect(className).not.toContain("shadow-[var(--vui-shadow-hairline)]");
      expect(className).not.toContain("bg-[var(--surface-panel)]");
      expect(className).not.toContain("bg-[var(--surface-card)]");
    });
  });

  it("keeps the Kernel ledger as a flat bordered structure", () => {
    expect(styles.ledgerSectionClass).toContain("grid");
    expect(styles.ledgerSectionClass).toContain("border-t");
    expect(styles.ledgerSectionClass).toContain("pt-2");
    expect(styles.ledgerSectionClass).not.toContain("bg-");
    expect(styles.ledgerSectionClass).not.toContain("[background:");
    expect(styles.ledgerSectionClass).not.toContain("rounded-[var(--radius-panel)]");
    expect(styles.ledgerSectionClass).not.toContain("shadow-");

    expect(styles.ledgerBucketClass).toContain("grid");
    expect(styles.ledgerBucketClass).toContain("content-start");
    expect(styles.ledgerBucketClass).not.toContain("bg-");
    expect(styles.ledgerBucketClass).not.toContain("[background:");
    expect(styles.ledgerBucketClass).not.toContain("rounded-[var(--radius-panel)]");
    expect(styles.ledgerBucketClass).not.toContain("cardSurface");
    expect(styles.ledgerBucketClass).not.toContain("shadow-");
  });

  it("keeps Kernel panel surface tokens centralized in route-local constants", () => {
    expect(stylesSource).toContain("const panelSurface");
    expect(stylesSource).toContain("const cardSurface");
    expect(stylesSource).toContain("const rowSurface");
  });

  it("keeps Kernel mobile layout bounded without horizontal page overflow", () => {
    expect(styles.workspaceClass).toContain("min-w-0");
    expect(styles.workspaceClass).toContain("max-w-full");
    expect(styles.workspaceClass).toContain("overflow-x-hidden");
    expect(styles.taskPaneClass).toContain("min-w-0");
    expect(styles.detailPaneClass).toContain("min-w-0");
    expect(styles.detailPaneClass).toContain("max-w-full");
    expect(styles.taskRowClass).toContain("min-w-0");
    expect(styles.taskRowClass).toContain("max-w-full");
  });

  it("uses independent scroll regions for the task list, detail ledger, and event stream", () => {
    expect(styles.routeClass).toContain("overflow-hidden");
    expect(styles.workspaceClass).toContain("overflow-hidden");
    expect(styles.taskPaneClass).toContain("overflow-hidden");
    expect(styles.taskListClass).toContain("overflow-auto");
    expect(styles.taskListClass).toContain("overflow-x-hidden");

    expect(styles.detailPaneClass).toContain("grid-cols-[minmax(0,1fr)_minmax(300px,0.86fr)]");
    expect(styles.detailPaneClass).toContain("grid-rows-[minmax(0,1fr)]");
    expect(styles.detailPaneClass).toContain("overflow-hidden");
    expect(styles.detailContentClass).toContain("overflow-auto");
    expect(styles.detailContentClass).toContain("overflow-x-hidden");

    expect(styles.lifecycleSectionClass).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.lifecycleSectionClass).toContain("overflow-hidden");
    expect(styles.lifecycleTimelineClass).toContain("overflow-auto");
    expect(styles.lifecycleTimelineClass).toContain("overflow-x-hidden");
    expect(styles.deliveryGridClass).toContain("overflow-auto");
    expect(styles.deliveryGridClass).toContain("overflow-x-hidden");
    expect(routeSource).toContain("styles.detailContentClass");
  });

  it("wraps long Kernel ids, refs, paths, and errors inside their panels", () => {
    expect(styles.detailHeaderClass).toContain("max-w-full");
    expect(styles.detailTitleClass).toContain("truncate");
    expect(styles.deliveryRowClass).toContain("max-w-full");
    expect(styles.deliveryRowTopClass).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(styles.mutedLineClass).toContain("break-words");
    expect(styles.warningLineClass).toContain("break-words");
    expect(styles.lifecycleSummaryClass).toContain("break-words");
    expect(styles.chipCodeClass).toContain("max-w-full");
    expect(styles.chipCodeClass).toContain("break-all");
    expect(styles.chipCodeClass).toContain("whitespace-normal");
    expect(styles.emptyStateClass).toContain("break-words");
  });

  it("keeps Kernel header actions content-sized", () => {
    expect(styles.headerActionsClass).toContain("flex-wrap");
    expect(styles.statusFilterClass).toContain("w-fit");
    expect(styles.statusFilterClass).toContain("max-w-full");
    expect(styles.iconButtonClass).toContain("h-[34px]");
    expect(styles.iconButtonClass).toContain("w-[34px]");
    expect(styles.iconButtonClass).not.toContain("w-full");
  });

  it("presents Kernel as a ledger-first task chain instead of a logs surface", () => {
    expect(routeSource).toContain("copy.taskChain");
    expect(routeSource).toContain("copy.evidenceRefs");
    expect(routeSource).toContain("copy.lifecycleTimeline");
    expect(routeSource).not.toContain("copy.runtimeRefs");
    expect(routeSource).not.toContain("copy.timeline");
    expect(routeSource).not.toContain("运行证据");
    expect(routeSource).not.toContain("Runtime evidence");
    expect(routeSource).not.toContain("时间线");
    expect(routeSource).not.toContain("/logs");

    expect(stylesSource).toContain("ledgerFlowClass");
    expect(stylesSource).toContain("ledgerBucketClass");
    expect(stylesSource).toContain("evidenceRefListClass");
    expect(stylesSource).toContain("lifecycleTimelineClass");
    expect(stylesSource).not.toContain("timelineListClass");
    expect(stylesSource).not.toContain("timelineRowClass");
  });

  it("allows Kernel task rows to render multiline content inside VButton", () => {
    expect(routeSource).toContain("<VButton");
    expect(stylesSource).toContain("data-slot=vui-button-content");
    expect(stylesSource).toContain("data-slot=vui-button-label");
    expect(stylesSource).toContain("!h-auto");
    expect(styles.taskRowClass).toContain("!min-h-[72px]");
    expect(styles.taskRowClass).not.toContain("!min-h-[112px]");
    expect(stylesSource).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(stylesSource).toContain("whitespace-normal");
  });
});
