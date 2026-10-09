// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";
import { compareAIBacktests, downloadAIBacktestComparison, previewForkAIBacktest } from "./financialBacktests";
import type { AIBacktestComparisonResult } from "./types/financialBacktests";

afterEach(() => {
  resetControlTokenForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("posts same-data fork previews and uses the run-scoped comparison endpoint", async () => {
  seedControlTokenForTests("test-token");
  const payload: AIBacktestComparisonResult = {
    comparisonId: "comparison-1",
    axis: "strategy",
    status: "incomplete",
    reasons: [{ code: "run_incomplete", runIds: ["run-1"], message: "任务尚未完成" }],
    dataHash: null,
    commonParamsHash: null,
    outOfSampleStartDate: null,
    rows: [],
    notice: "比较说明",
  };
  const fetch = vi.fn<typeof globalThis.fetch>(async () => new Response(JSON.stringify(payload), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  await previewForkAIBacktest("agent/one", "run/one", { strategy: "changed", modelId: "provider/model", maxTokens: 5000 });
  await compareAIBacktests("agent/one", { runIds: ["run-1", "run-2"], axis: "strategy" });
  const requests = fetch.mock.calls.map(([url, init]) => ({
    url: String(url),
    body: JSON.parse(String(init?.body)),
  }));
  expect(requests[0]).toEqual({
    url: "/api/financial-backtests/agent%2Fone/runs/run%2Fone/fork-preview",
    body: { strategy: "changed", modelId: "provider/model", maxTokens: 5000 },
  });
  expect(requests[1]).toEqual({
    url: "/api/financial-backtests/agent%2Fone/runs/compare",
    body: { runIds: ["run-1", "run-2"], axis: "strategy" },
  });
});

it("downloads the comparison manifest currently shown by the UI", async () => {
  const result: AIBacktestComparisonResult = {
    comparisonId: "comparison/2026:1",
    axis: "model",
    status: "incompatible",
    reasons: [{ code: "different_data", runIds: ["run-2"], message: "冻结行情不同" }],
    dataHash: null,
    commonParamsHash: null,
    outOfSampleStartDate: null,
    rows: [],
    notice: "不作收益排名",
  };
  const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
  const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
  const createObjectURL = vi.fn(() => "blob:test-comparison");
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const createElement = document.createElement.bind(document);
  const click = vi.fn();
  let anchor: HTMLAnchorElement | null = null;
  vi.spyOn(document, "createElement").mockImplementation(((tag: string) => {
    const element = createElement(tag);
    if (tag.toLowerCase() === "a") {
      anchor = element as HTMLAnchorElement;
      Object.defineProperty(anchor, "click", { configurable: true, value: click });
    }
    return element;
  }) as typeof document.createElement);

  try {
    downloadAIBacktestComparison(result);
    const blob = createObjectURL.mock.calls[0]?.[0] as unknown as Blob;
    expect(blob.type).toBe("application/json");
    expect(await blob.text()).toContain('"comparisonId": "comparison/2026:1"');
    expect(anchor?.download).toBe("financial-backtest-comparison-comparison_2026_1.json");
    expect(click).toHaveBeenCalledOnce();
  } finally {
    if (originalCreateObjectURL) Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
    else Reflect.deleteProperty(URL, "createObjectURL");
    if (originalRevokeObjectURL) Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
    else Reflect.deleteProperty(URL, "revokeObjectURL");
  }
});
