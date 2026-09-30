// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const query = vi.hoisted(() => ({ current: {} as Record<string, unknown>, refetch: vi.fn(), lang: "zh" }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => query.current }));
vi.mock("../app/pollingPolicy", () => ({ resolvePollingInterval: () => false, usePageVisibility: () => true }));
vi.mock("../i18n/useAppI18n", () => ({ useAppI18n: () => ({ lang: query.lang }) }));
import { UsageRoute } from "./UsageRoute";
import routeSource from "./UsageRoute.tsx?raw";
import utilitySource from "../app/AppShellUtilityMenu.tsx?raw";
import settingsSource from "../app/AppShellSettingsMenu.tsx?raw";
import styles from "./UsageRoute.styles";

const zero = {
  inputTokens: 0, cachedInputTokens: 0, outputTokens: 0, reasoningOutputTokens: 0,
  totalTokens: 0, callCount: 0, observedCallCount: 0, estimatedCallCount: 0, missingCallCount: 0,
};
const week = {
  ...zero, inputTokens: 1000, outputTokens: 200, totalTokens: 1200, cachedInputTokens: 250,
  reasoningOutputTokens: 50, callCount: 10, observedCallCount: 7, estimatedCallCount: 2, missingCallCount: 1,
  cacheHitRate: 0.9,
};
const summary = {
  globalTokenUsage: { today: { ...week, totalTokens: 500 }, last7Days: week, allTime: { ...week, totalTokens: 12000 } },
  lastTokenUsage: { source: "missing", totalTokens: 0, eventId: "event-demo", provider: "example", model: "test-model" },
  diagnostics: { source: "usage_ledger", schemaVersion: 1, skippedRecordCount: 2 },
};
let host: HTMLDivElement;
let root: Root;
async function render(state: Record<string, unknown> = {}) {
  query.current = { data: summary, isPending: false, isFetching: false, isError: false, refetch: query.refetch, ...state };
  await act(async () => root.render(createElement(MemoryRouter, null, createElement(UsageRoute))));
}
function text(id: string) { return host.querySelector('[data-testid="' + id + '"]')?.textContent; }
async function click(name: string, selector = "button") {
  const element = [...host.querySelectorAll<HTMLButtonElement>(selector)].find(node => node.textContent?.includes(name));
  expect(element).toBeDefined();
  await act(async () => {
    if (element!.getAttribute("role") === "tab") element!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    else element!.click();
  });
}
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  query.lang = "zh";
  query.refetch.mockReset();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

describe("Usage settings page", () => {
  it("uses the existing API, settings recipe and settings-only entry", async () => {
    await render();
    expect(routeSource).toContain("fetchUsageSummary");
    expect(routeSource).toContain('queryKeys.usageSummary("global")');
    expect(host.querySelector('[data-vui-recipe="settings-form-page"]')).not.toBeNull();
    expect(host.querySelector('a[href="/config"]')).not.toBeNull();
    expect(settingsSource).toContain('to="/usage"');
    expect(utilitySource).not.toContain('to="/usage"');
    expect(styles.page).toContain("overflow-y-auto");
    expect(styles.metrics).toContain("max-[700px]:grid-cols-2");
  });
  it("defaults to seven days and switches all metrics without using latest-call source as global state", async () => {
    await render();
    expect(text("usage-total")).toBe("1,200");
    expect(text("usage-calls")).toBe("10");
    expect(host.textContent).not.toContain("此时间范围内暂无调用");
    await click("今日", '[role="tab"]');
    expect(text("usage-total")).toBe("500");
    await click("全部时间", '[role="tab"]');
    expect(text("usage-total")).toBe("12,000");
  });
  it("uses cached input divided by all input, not the backend observed-only cache rate", async () => {
    await render();
    expect(text("usage-cache-share")).toBe("25.0%");
    expect(host.textContent).toContain("7 / 10 次");
    expect(host.textContent).toContain("70.0% 覆盖率");
    expect(host.textContent).not.toContain("可信度");
  });
  it("keeps diagnostics hidden until requested, and distinguishes missing latest usage from zero", async () => {
    await render();
    expect(host.querySelector("#usage-diagnostics")).toBeNull();
    expect(host.textContent).not.toContain("usage_ledger");
    await click("最近一次调用与诊断");
    expect(host.querySelector("#usage-diagnostics")?.textContent).toContain("event-demo");
    expect(host.querySelector("#usage-diagnostics")?.textContent).toContain("缺少用量");
    expect(host.querySelector("#usage-diagnostics")?.textContent).not.toContain("0 tokens");
    await click("最近一次调用与诊断");
    expect(host.querySelector("#usage-diagnostics")).toBeNull();
  });
  it("retains nonzero data during refresh and disables duplicate refreshes", async () => {
    await render({ isFetching: true });
    expect(text("usage-total")).toBe("1,200");
    expect(host.textContent).toContain("同步中");
    expect(host.querySelector('[data-vui="loading-value"]')).toBeNull();
    expect([...host.querySelectorAll("button")].find(b => b.textContent === "刷新")?.disabled).toBe(true);
  });
  it("retains the last successful values after a failed refresh and can retry", async () => {
    await render({ isError: true, error: new Error("stale warning") });
    expect(text("usage-total")).toBe("1,200");
    expect(host.textContent).toContain("保留上次成功读取的数据");
    expect(host.textContent).toContain("stale warning");
    await click("刷新");
    expect(query.refetch).toHaveBeenCalledOnce();
  });
  it("does not turn initial loading or unavailable data into factual zeros", async () => {
    await render({ data: undefined, isPending: true, isFetching: true });
    expect(host.querySelector('[data-vui="loading-value"]')).not.toBeNull();
    expect(host.textContent).toContain("正在加载 Token 用量");
    expect(host.textContent).not.toContain("暂无调用");
    await render({ data: undefined, isError: true, error: new Error("unavailable") });
    expect(text("usage-total")).toBe("—");
    expect(text("usage-cache-share")).toBe("—");
    expect(host.textContent).toContain("unavailable");
    expect(host.textContent).not.toContain("0 次");
  });
  it("shows loaded zero counts with no fabricated percentage", async () => {
    await render({ data: { ...summary, globalTokenUsage: { last7Days: zero } } });
    expect(text("usage-total")).toBe("0");
    expect(text("usage-cache-share")).toBe("—");
    expect(host.textContent).toContain("此时间范围内暂无调用");
    expect(host.textContent).not.toContain("0.0%");
  });
  it("does not interpret an absent range as empty", async () => {
    await render({ data: { ...summary, globalTokenUsage: {} } });
    expect(text("usage-total")).toBe("—");
    expect(host.textContent).toContain("此时间范围的统计暂不可用");
    expect(host.textContent).not.toContain("暂无调用");
  });
  it("marks unobserved cache counts unavailable and reports partial coverage", async () => {
    await render({ data: { ...summary, globalTokenUsage: { last7Days: { ...week, cacheUsageObserved: false } } } });
    expect(text("usage-cache-share")).toBe("—");
    expect(host.textContent).toContain("不代表完整缓存用量");
  });
  it("supports English without untranslated state labels", async () => {
    query.lang = "en"; await render({ data: undefined, isError: true });
    expect(host.textContent).toContain("Usage statistics");
    expect(host.textContent).toContain("Usage unavailable");
    expect(host.textContent).not.toContain("不可用");
  });
});
