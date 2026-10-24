// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";

const telemetry = vi.hoisted(() => vi.fn());
vi.mock("./browserTelemetry", () => ({ postBrowserTelemetry: telemetry }));
vi.mock("./pageInstance", () => ({ getPageInstanceId: () => "document-one" }));

beforeEach(() => {
  vi.resetModules(); telemetry.mockClear();
  for (const stage of ["data_ready", "transcript_presented", "composer_ready", "interactive"]) {
    performance.clearMarks(`vibelution.chat.startup.${stage}`);
  }
});

describe("native chat startup measurement", () => {
  it.each([
    ["dataReady", "transcriptPresented", "composerReady"],
    ["composerReady", "transcriptPresented", "dataReady"],
  ] as const)("requires every fact and uses observed times even when the last fact is %s", async (...order) => {
    const { recordChatStartupMilestone: mark } = await import("./chatStartupMetrics");
    const times = { dataReady: 100, transcriptPresented: 180, composerReady: 220 };
    order.forEach((stage, index) => {
      mark("initial", stage, times[stage]);
      expect(telemetry.mock.calls.filter(([event]) => event.eventCode.endsWith("startup_interactive")))
        .toHaveLength(index === 2 ? 1 : 0);
    });
    expect(telemetry).toHaveBeenLastCalledWith(expect.objectContaining({
      eventCode: "browser.chat_route.startup_interactive",
      fields: expect.objectContaining({
        pageInstanceId: "document-one", sessionId: "initial", measurementVersion: 2,
        navigationTimeOriginMs: performance.timeOrigin,
        dataReadyMs: 100, transcriptPresentedMs: 180, composerReadyMs: 220,
        interactiveMs: 220, dataReadyToInteractiveMs: 120,
      }),
    }));
    expect(performance.getEntriesByName("vibelution.chat.startup.interactive")[0]?.startTime).toBe(220);
  });

  it("deduplicates remount reports and never combines two sessions", async () => {
    const { recordChatStartupMilestone: mark } = await import("./chatStartupMetrics");
    mark("initial", "dataReady", 10);
    mark("next", "transcriptPresented", 20);
    mark("next", "composerReady", 30);
    expect(telemetry).not.toHaveBeenCalled();
    mark("initial", "transcriptPresented", 40);
    mark("initial", "transcriptPresented", 50);
    mark("initial", "composerReady", 60);
    mark("initial", "composerReady", 70);
    mark("initial", "dataReady", 80);
    expect(telemetry.mock.calls.map(([event]) => event.eventCode)).toEqual([
      "browser.chat_route.startup_transcript_presented",
      "browser.chat_route.startup_composer_ready",
      "browser.chat_route.startup_interactive",
    ]);
  });

  it("does not accept missing identities or invalid clocks", async () => {
    const { recordChatStartupMilestone: mark } = await import("./chatStartupMetrics");
    mark("", "dataReady", 10);
    mark("initial", "dataReady", Number.NaN);
    mark("initial", "dataReady", -1);
    mark("initial", "transcriptPresented", 20);
    mark("initial", "composerReady", 30);
    expect(telemetry.mock.calls.some(([event]) => event.eventCode.endsWith("startup_interactive"))).toBe(false);
  });
});
