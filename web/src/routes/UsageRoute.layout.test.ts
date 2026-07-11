import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const usageQueryState = vi.hoisted(() => ({
  current: {} as Record<string, unknown>,
  invalidateQueries: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => usageQueryState.current,
  useQueryClient: () => ({ invalidateQueries: usageQueryState.invalidateQueries }),
}));
vi.mock("../app/pollingPolicy", () => ({
  resolvePollingInterval: () => false,
  usePageVisibility: () => true,
}));
vi.mock("../i18n/useAppI18n", () => ({ useAppI18n: () => ({ lang: "zh" }) }));

import routeSource from "./UsageRoute.tsx?raw";
import stylesSource from "./UsageRoute.styles.ts?raw";
import styles from "./UsageRoute.styles";
import { UsageRoute } from "./UsageRoute";

const ZERO_ROLLUP = {
  inputTokens: 0,
  cachedInputTokens: 0,
  cacheReadInputTokens: 0,
  cacheCreationInputTokens: 0,
  uncachedInputTokens: 0,
  outputTokens: 0,
  reasoningOutputTokens: 0,
  totalTokens: 0,
  callCount: 0,
  observedCallCount: 0,
  estimatedCallCount: 0,
  missingCallCount: 0,
  notCalledCount: 0,
  latencyMs: 0,
  cacheHitRate: 0,
};

const LOADED_ZERO_SUMMARY = {
  scope: "global",
  globalTokenUsage: { allTime: ZERO_ROLLUP, today: ZERO_ROLLUP, last7Days: ZERO_ROLLUP },
  sessionTokenUsage: ZERO_ROLLUP,
  agentTokenUsage: ZERO_ROLLUP,
  scopeTokenUsage: ZERO_ROLLUP,
};

function renderUsage(state: Record<string, unknown>) {
  usageQueryState.current = {
    data: undefined,
    error: null,
    isError: false,
    isFetching: false,
    isPending: false,
    refetch: vi.fn(),
    ...state,
  };
  return renderToStaticMarkup(createElement(UsageRoute));
}

describe("UsageRoute layout contract", () => {
  beforeEach(() => {
    usageQueryState.invalidateQueries.mockReset();
  });
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
    expect(stylesSource).toContain("grid-cols-[minmax(0,1fr)_minmax(280px,360px)]");
    expect(stylesSource).toContain("bg-vui-surface-panel/88");
    expect(stylesSource).toContain("min-h-0");
    expect(styles.heroMetric).toContain("rounded-[var(--radius-panel)]");
    expect(styles.usageRow).toContain("hover:bg-[var(--vui-surface-row-hover)]");
    expect(styles.errorState).toContain("rounded-[var(--radius-control)]");
    expect(styles.heroMetric).toContain("[&_strong]:text-[1.18rem]");
    expect(styles.overviewStat).toContain("[&_strong]:text-[0.96rem]");
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

  it("distinguishes pending rollups from loaded zero values", () => {
    expect(routeSource).toContain("deriveQueryPresentation");
    expect(routeSource).toContain("<VLoadingValue");
    expect(routeSource).not.toContain("function rollupOrEmpty");
    expect(routeSource).not.toContain("const allTime = rollupOrEmpty");
    expect(routeSource).toContain('usagePresentation === "initial-loading"');
    expect(routeSource).toContain('usagePresentation === "refreshing"');
  });

  it("reserves stable metric heights while values load", () => {
    expect(styles.heroMetric).toContain("grid min-h-[76px]");
    expect(styles.overviewStat).toContain("grid min-h-[58px]");
    expect(styles.sourceTile).toContain("grid min-h-[50px]");
  });

  it.each([
    ["initial-loading", { isFetching: true, isPending: true }, 'data-vui="loading-value"'],
    ["loaded-zero", { data: LOADED_ZERO_SUMMARY }, ">0<"],
    ["refreshing-with-data", { data: LOADED_ZERO_SUMMARY, isFetching: true }, "同步中"],
    ["error-with-data", { data: LOADED_ZERO_SUMMARY, error: new Error("stale"), isError: true }, "stale"],
  ])("renders the %s query presentation", (_name, state, expected) => {
    expect(renderUsage(state)).toContain(expected);
  });

  it("renders unavailable values and retry without zero projection for error-empty", () => {
    const markup = renderUsage({ error: new Error("usage unavailable"), isError: true });
    expect(markup).toContain('data-tone="error"');
    expect(markup).toContain("usage unavailable");
    expect(markup).toContain("重试");
    expect(markup).not.toContain(">0<");
  });
});
