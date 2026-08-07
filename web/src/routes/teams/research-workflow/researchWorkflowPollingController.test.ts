import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResearchWorkflowPollingController } from "./researchWorkflowPollingController";

describe("ResearchWorkflowPollingController", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not full-refresh when snapshot exists but events are empty", async () => {
    const fetchEvents = vi.fn(async () => ({
      events: [],
      snapshot: { status: "waiting_human" },
    }));
    const onEvents = vi.fn();
    const onNeedsRefresh = vi.fn();
    const ctl = new ResearchWorkflowPollingController({
      fetchEvents,
      onEvents,
      onNeedsRefresh,
      intervalMs: 2500,
    });
    ctl.setRun("run-a", 0);
    ctl.start();
    await ctl.tick();
    expect(fetchEvents).toHaveBeenCalledWith("run-a", 0);
    expect(onEvents).not.toHaveBeenCalled();
    expect(onNeedsRefresh).not.toHaveBeenCalled();
    ctl.dispose();
  });

  it("switches run B cursor after run A sequence=100", async () => {
    const calls: Array<{ runId: string; after: number }> = [];
    const fetchEvents = vi.fn(async (runId: string, after: number) => {
      calls.push({ runId, after });
      return { events: [{ eventId: `${runId}-1`, sequence: after + 1 }] };
    });
    const ctl = new ResearchWorkflowPollingController({
      fetchEvents,
      onEvents: vi.fn(),
      intervalMs: 2500,
    });
    ctl.setRun("run-a", 100);
    await ctl.tick();
    expect(calls[0]).toEqual({ runId: "run-a", after: 100 });
    ctl.setRun("run-b", 1);
    await ctl.tick();
    expect(calls[1]).toEqual({ runId: "run-b", after: 1 });
    ctl.dispose();
  });

  it("slow run A response cannot overwrite run B", async () => {
    let resolveA: (v: unknown) => void = () => {};
    const fetchEvents = vi.fn((runId: string) => {
      if (runId === "run-a") {
        return new Promise((resolve) => {
          resolveA = resolve;
        });
      }
      return Promise.resolve({ events: [{ eventId: "b1", sequence: 1 }] });
    });
    const applied: string[] = [];
    const ctl = new ResearchWorkflowPollingController({
      fetchEvents: fetchEvents as never,
      onEvents: async (runId) => {
        applied.push(runId);
      },
      intervalMs: 2500,
    });
    ctl.setRun("run-a", 0);
    const tickA = ctl.tick();
    ctl.setRun("run-b", 0);
    await ctl.tick();
    resolveA({ events: [{ eventId: "a1", sequence: 1 }] });
    await tickA;
    expect(applied).toEqual(["run-b"]);
    ctl.dispose();
  });

  it("timer does not create parallel in-flight requests", async () => {
    let resolveFetch: (v: unknown) => void = () => {};
    let inflight = 0;
    let maxInflight = 0;
    const fetchEvents = vi.fn(() => {
      inflight += 1;
      maxInflight = Math.max(maxInflight, inflight);
      return new Promise((resolve) => {
        resolveFetch = (v) => {
          inflight -= 1;
          resolve(v);
        };
      });
    });
    const ctl = new ResearchWorkflowPollingController({
      fetchEvents: fetchEvents as never,
      onEvents: vi.fn(),
      intervalMs: 100,
    });
    ctl.setRun("run-a", 0);
    const first = ctl.tick();
    // Force another tick while first is in flight (must not start second fetch).
    const second = ctl.tick();
    const third = ctl.tick();
    expect(maxInflight).toBe(1);
    expect(fetchEvents).toHaveBeenCalledTimes(1);
    resolveFetch({ events: [] });
    await Promise.all([first, second, third]);
    ctl.dispose();
  });

  it("unmount dispose cancels further polling", async () => {
    const fetchEvents = vi.fn(async () => ({ events: [] }));
    const ctl = new ResearchWorkflowPollingController({
      fetchEvents,
      onEvents: vi.fn(),
      intervalMs: 1000,
    });
    ctl.setRun("run-a", 0);
    ctl.start();
    ctl.dispose();
    await ctl.tick();
    expect(fetchEvents).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5000);
    expect(fetchEvents).not.toHaveBeenCalled();
  });
});
