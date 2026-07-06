import { describe, expect, it } from "vitest";

import routeSource from "./UsageRoute.tsx?raw";
import stylesSource from "./UsageRoute.styles.ts?raw";
import styles from "./UsageRoute.styles";

describe("UsageRoute layout contract", () => {
  it("renders a compact operational token usage route from the usage summary API", () => {
    expect(routeSource).toContain('fetchJson<UsageSummaryResponse>("/api/usage/summary")');
    expect(routeSource).toContain("queryKeys.usageSummary");
    expect(routeSource).toContain("globalTokenUsage");
    expect(routeSource).toContain("lastTokenUsage");
    expect(routeSource).toContain("rollupFilters");
    expect(routeSource).toContain("heroMetric");
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

  it("keeps the usage page dense without hero or nested-card composition", () => {
    expect(styles.page).toBeTypeOf("string");
    expect(styles.overviewBand).toBeTypeOf("string");
    expect(styles.heroMetric).toBeTypeOf("string");
    expect(styles.metricBand).toBeTypeOf("string");
    expect(stylesSource).toContain("grid-cols-[minmax(0,1fr)_minmax(300px,380px)]");
    expect(stylesSource).toContain("bg-vui-surface-panel/88");
    expect(stylesSource).toContain("min-h-0");
    expect(styles.heroMetric).toContain("rounded-[var(--radius-panel)]");
    expect(styles.usageRow).toContain("hover:bg-[var(--vui-surface-row-hover)]");
    expect(styles.errorState).toContain("rounded-[var(--radius-control)]");
    expect(stylesSource).not.toContain("grid-cols-[minmax(260px,0.82fr)_minmax(0,1.18fr)_minmax(260px,0.8fr)]");
    expect(stylesSource).not.toContain("rounded-lg");
    expect(stylesSource).not.toContain("bg-vui-surface-row-hover");
    expect(stylesSource).not.toContain("rounded-[2rem]");
    expect(stylesSource).not.toContain("text-6xl");
    expect(stylesSource).not.toContain("from-purple");
  });
});
