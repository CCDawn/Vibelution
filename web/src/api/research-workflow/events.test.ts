import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../client";
import type { WorkflowEventEnvelope } from "../types/research-workflow/events";
import { replayResearchWorkflowEvents } from "./events";

function envelope(sequence: number): WorkflowEventEnvelope {
  return {
    eventId: `evt-${sequence}`,
    sequence,
    runId: "run-a",
    teamId: "research-team",
    runVersion: sequence,
    type: sequence === 1 ? "run_created" : "node_starting",
    correlationId: "corr",
    occurredAt: "2026-08-12T14:00:00.000Z",
    payload: sequence === 1 ? {} : { nodeId: "source_finding", attempt: 1 },
  };
}

describe("replayResearchWorkflowEvents", () => {
  beforeEach(() => {
    resetControlTokenForTests();
    seedControlTokenForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it("follows EventPage cursors until hasMore is false", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = String(input);
      if (url.includes("afterSequence=0")) {
        return {
          ok: true,
          json: async () => ({
            runId: "run-a",
            teamId: "research-team",
            runVersion: 1,
            latestEventSequence: 3,
            afterSequence: 0,
            lastReturnedSequence: 2,
            hasMore: true,
            nextAfterSequence: 2,
            events: [envelope(1), envelope(2)],
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({
          runId: "run-a",
          teamId: "research-team",
          runVersion: 1,
          latestEventSequence: 3,
          afterSequence: 2,
          lastReturnedSequence: 3,
          hasMore: false,
          nextAfterSequence: null,
          events: [envelope(3)],
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    const events = await replayResearchWorkflowEvents({
      runId: "run-a",
      teamId: "research-team",
    });
    expect(events.map((item) => item.sequence)).toEqual([1, 2, 3]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get("X-Vibelution-Control-Token")).toBe(
        "test-control-token",
      );
    }
  });

  it("fails closed when the replay cursor does not advance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        runId: "run-a",
        teamId: "research-team",
        runVersion: 1,
        latestEventSequence: 9,
        afterSequence: 0,
        lastReturnedSequence: 0,
        hasMore: true,
        nextAfterSequence: 0,
        events: [],
      }),
    })));

    await expect(
      replayResearchWorkflowEvents({ runId: "run-a", teamId: "research-team" }),
    ).rejects.toThrow("events_replay_cursor_stuck");
  });
});
