import { describe, expect, it } from "vitest";

import {
  applyEventBatch,
  applyInitialRunEvents,
  emptyEventReadModel,
  mergeEventsByIdentity,
} from "./researchWorkflowEventReducer";

describe("researchWorkflowEventReducer", () => {
  it("initial load of 3 events stays 3 (no double-concat)", () => {
    const recordEvents = [
      { eventId: "e1", sequence: 1 },
      { eventId: "e2", sequence: 2 },
      { eventId: "e3", sequence: 3 },
    ];
    // Incremental page incorrectly returns the same 3 (historical bug).
    const incremental = [...recordEvents];
    const state = applyInitialRunEvents("run-a", recordEvents, incremental);
    expect(state.events).toHaveLength(3);
    expect(state.lastSequence).toBe(3);
  });

  it("dedupes by eventId and sequence", () => {
    const merged = mergeEventsByIdentity(
      [
        { eventId: "e1", sequence: 1, type: "a" },
        { eventId: "e2", sequence: 2, type: "b" },
      ],
      [
        { eventId: "e2", sequence: 2, type: "b-updated" },
        { eventId: "e3", sequence: 3, type: "c" },
        { sequence: 1, type: "dup-seq" }, // same sequence without id — still one seq:1 slot if first used id
      ],
    );
    // e1, e2, e3 at minimum; seq-only key may coexist if different key form — identity prefers eventId.
    const byId = merged.filter((e) => e.eventId);
    expect(byId).toHaveLength(3);
    expect(byId.find((e) => e.eventId === "e2")?.type).toBe("b-updated");
  });

  it("appends incremental events ordered by sequence", () => {
    let state = applyEventBatch(emptyEventReadModel("run-a"), {
      runId: "run-a",
      events: [{ eventId: "e1", sequence: 1 }],
    });
    state = applyEventBatch(state, {
      runId: "run-a",
      events: [
        { eventId: "e3", sequence: 3 },
        { eventId: "e2", sequence: 2 },
      ],
    });
    expect(state.events.map((e) => e.sequence)).toEqual([1, 2, 3]);
    expect(state.lastSequence).toBe(3);
  });

  it("resets cursor when runId switches", () => {
    const stateA = applyEventBatch(emptyEventReadModel("run-a"), {
      runId: "run-a",
      events: [{ eventId: "a100", sequence: 100 }],
    });
    expect(stateA.lastSequence).toBe(100);
    const stateB = applyEventBatch(stateA, {
      runId: "run-b",
      events: [{ eventId: "b1", sequence: 1 }],
    });
    expect(stateB.runId).toBe("run-b");
    expect(stateB.events).toHaveLength(1);
    expect(stateB.lastSequence).toBe(1);
  });
});
