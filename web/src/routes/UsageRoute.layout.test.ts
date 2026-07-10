import { describe, expect, it } from "vitest";

import routeSource from "./UsageRoute.tsx?raw";
import stylesSource from "./UsageRoute.styles.ts?raw";
import styles from "./UsageRoute.styles";

describe("UsageRoute layout contract", () => {
  const overflowGuardStyles = [
    styles.page,
    styles.metricBand,
    styles.primaryColumn,
    styles.compositionPanel,
    styles.rollupPanel,
    styles.recordPanel,
    styles.usageList,
    styles.detailGrid,
    styles.breakdownList,
  ] as const;

  it("renders a compact operational token usage route from the usage summary API", () => {
    expect(routeSource).toContain('fetchJson<UsageSummaryResponse>("/api/usage/summary")');
    expect(routeSource).toContain("queryKeys.usageSummary");
    expect(routeSource).toContain("globalTokenUsage");
    expect(routeSource).toContain("lastTokenUsage");
    expect(routeSource).toContain("rollupFilters");
    expect(routeSource).toContain("Token 构成");
    expect(routeSource).toContain("Token composition");
    expect(routeSource).toContain("计数概览");
    expect(routeSource).toContain("Counting overview");
    expect(routeSource).toContain("最近会话");
    expect(routeSource).toContain("Latest session");
    expect(routeSource).toContain("最近 Agent");
    expect(routeSource).toContain("Latest agent");
    expect(routeSource).toContain("provider_usage");
    expect(routeSource).toContain("estimated");
    expect(routeSource).toContain("missing");
    expect(routeSource).toContain("reasoningOutputTokens");
    expect(routeSource).not.toContain("cost");
    expect(routeSource).not.toContain("billing");
  });

  it("uses a metric strip and distinguishes not-called usage from zero usage", () => {
    expect(routeSource).toContain("VMetricStrip");
    expect(routeSource).toContain("VStateSurface");
    expect(routeSource).toContain('lastSource === "not_called"');
    expect(routeSource).toContain("尚未调用");
    expect(routeSource).toContain("Not called yet");
    expect(styles.overviewBand).toContain("min-w-0");
  });

  it("keeps the usage page dense with shared hierarchy instead of hero or nested-card composition", () => {
    expect(styles.page).toBeTypeOf("string");
    expect(styles.overviewBand).toBeTypeOf("string");
    expect(styles.emptyState).toBeTypeOf("string");
    expect(styles.metricBand).toBeTypeOf("string");
    expect(stylesSource).toContain("grid-cols-[minmax(0,1fr)_minmax(280px,360px)]");
    expect(stylesSource).toContain("bg-vui-surface-panel/88");
    expect(stylesSource).toContain("min-h-0");
    expect(styles.usageRow).toContain("hover:bg-[var(--vui-surface-row-hover)]");
    expect(styles.emptyState).toContain("mx-3 mt-2");
    expect(styles.compositionPanel).toContain("p-2");
    expect(styles.rollupPanel).toContain("p-2");
    expect(styles.recordPanel).toContain("p-2");
    expect(stylesSource).not.toContain("grid-cols-[minmax(260px,0.82fr)_minmax(0,1.18fr)_minmax(260px,0.8fr)]");
    expect(stylesSource).not.toContain("rounded-lg");
    expect(stylesSource).not.toContain("bg-vui-surface-row-hover");
    expect(stylesSource).not.toContain("rounded-[2rem]");
    expect(stylesSource).not.toContain("text-6xl");
    expect(stylesSource).not.toContain("from-purple");
  });

  it("guards the Usage workbench against horizontal overflow on mobile", () => {
    for (const className of overflowGuardStyles) {
      expect(className).toContain("min-w-0");
      expect(className).toContain("max-w-full");
    }

    expect(styles.page).toContain("overflow-x-hidden");
    expect(styles.metricBand).toContain("overflow-x-hidden");
    expect(styles.metricBand).toContain("max-[860px]:overflow-x-hidden");
    expect(styles.primaryColumn).toContain("max-[980px]:overflow-x-hidden");
    expect(styles.recordPanel).toContain("max-[980px]:overflow-x-hidden");
    expect(styles.usageList).toContain("overflow-x-hidden");
    expect(styles.detailGrid).toContain("overflow-x-hidden");
    expect(styles.breakdownList).toContain("overflow-x-hidden");
    expect(stylesSource).not.toContain("overflow-visible");
  });

  it("keeps chips, rows, and detail values bounded by their content", () => {
    expect(styles.header).toContain("max-[720px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.headerMeta).toContain("[&_[data-vui=\"status-strip-item\"]]:grid-cols-[auto_minmax(0,1fr)]");
    expect(styles.headerMeta).toContain("[&_[data-vui=\"status-strip-item\"]_span]:text-ellipsis");
    expect(styles.countPill).toContain("w-fit");
    expect(styles.countPill).toContain("max-w-full");
    expect(styles.countPill).toContain("whitespace-nowrap");
    expect(styles.sourceTile).toContain("[&_span]:text-ellipsis");
    expect(styles.sourceTile).toContain("[&_strong]:text-[0.9rem]");
    expect(styles.usageRow).toContain("grid-cols-[minmax(96px,0.64fr)_minmax(0,1fr)_minmax(58px,max-content)_minmax(54px,max-content)]");
    expect(styles.usageRow).toContain("max-[620px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.usageRow).toContain("[&_code]:max-w-full");
    expect(styles.usageRowWide).toContain("max-[620px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.detailRow).toContain("max-[520px]:grid-cols-[minmax(0,1fr)]");
  });
});
