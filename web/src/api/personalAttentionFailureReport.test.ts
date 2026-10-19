import { afterEach, describe, expect, it, vi } from "vitest";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";
import {
  resetHumanAttentionFailureReporterForTests,
  reportHumanAttentionDeliveryFailure,
} from "./personalAttentionFailureReport";

const ENDPOINT = "/api/personal-assistant/attention/report-delivery-failure";

function okResponse() {
  return { ok: true, status: 200, json: async () => ({}) } as Response;
}

function flushMicrotasks() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

afterEach(() => {
  resetHumanAttentionFailureReporterForTests();
  resetControlTokenForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("human attention delivery failure reporter", () => {
  it("posts one bounded renderer report per id and never throws", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    reportHumanAttentionDeliveryFailure({
      id: "kr-1",
      kind: "knowledge_review",
      severity: "high",
      reason: "notify rejected: shell gone",
      title: "知识待复核",
    });
    await flushMicrotasks();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [input, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(input).toBe(ENDPOINT);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      id: "kr-1",
      kind: "knowledge_review",
      severity: "high",
      stage: "renderer",
      reason: "notify rejected: shell gone",
      title: "知识待复核",
    });
  });
  it("dedupes the same id in-process and caps the daily report budget", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    reportHumanAttentionDeliveryFailure({ id: "kr-2", kind: "anomaly", reason: "r" });
    reportHumanAttentionDeliveryFailure({ id: "kr-2", kind: "anomaly", reason: "r" });
    await flushMicrotasks();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    for (let index = 3; index < 14; index += 1) {
      reportHumanAttentionDeliveryFailure({ id: `kr-${index}`, kind: "anomaly", reason: "r" });
    }
    await flushMicrotasks();
    // 1 (kr-2) + 9 further ids = 10 reports; the rest hit the daily cap.
    expect(fetchMock).toHaveBeenCalledTimes(10);
  });
  it("swallows transport failures and missing ids", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);
    expect(() =>
      reportHumanAttentionDeliveryFailure({ id: "kr-3", kind: "anomaly", reason: "r" }),
    ).not.toThrow();
    reportHumanAttentionDeliveryFailure({ id: "", kind: "anomaly", reason: "r" });
    await flushMicrotasks();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
