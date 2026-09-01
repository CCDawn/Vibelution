import { describe, expect, it } from "vitest";

import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";
import {
  applyEventBatch,
  applyFormalEvent,
  applyFormalEventBatch,
  applyInitialRunEvents,
  emptyEventReadModel,
  emptyFormalEventReadModel,
  hydrateFormalEventFromSnapshot,
  mergeEventsByIdentity,
  switchFormalEventScope,
} from "./researchWorkflowEventReducer";
import {
  applySnapshotResponse,
  beginSnapshotFetch,
  emptySnapshotReadModel,
} from "./researchWorkflowSnapshotReducer";

function evt(
  partial: Partial<WorkflowEventEnvelope> & Pick<WorkflowEventEnvelope, "sequence" | "eventId">,
): WorkflowEventEnvelope {
  return {
    runId: "run-a",
    teamId: "team-a",
    runVersion: 1,
    type: "node_running",
    correlationId: "corr",
    occurredAt: "2026-08-12T14:00:00.000Z",
    payload: {},
    ...partial,
  };
}

describe("researchWorkflowEventReducer", () => {
  it("initial load of 3 events stays 3 (no double-concat)", () => {
    const recordEvents = [
      { eventId: "e1", sequence: 1 },
      { eventId: "e2", sequence: 2 },
      { eventId: "e3", sequence: 3 },
    ];
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
        { sequence: 1, type: "dup-seq" },
      ],
    );
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

describe("formal event reducer (T6)", () => {
  it("rejects mismatched team/run and duplicates", () => {
    let state = emptyFormalEventReadModel("team-a", "run-a");
    state = applyFormalEvent(state, evt({ eventId: "e1", sequence: 1 }));
    state = applyFormalEvent(state, evt({ eventId: "e1", sequence: 1 }));
    state = applyFormalEvent(
      state,
      evt({ eventId: "e2", sequence: 2, runId: "run-other" }),
    );
    state = applyFormalEvent(
      state,
      evt({ eventId: "e3", sequence: 2, teamId: "team-other" }),
    );
    expect(state.events).toHaveLength(1);
    expect(state.lastSequence).toBe(1);
    expect(state.resyncRequired).toBe(false);
  });

  it("marks resync_required on sequence gap", () => {
    let state = emptyFormalEventReadModel("team-a", "run-a");
    state = applyFormalEvent(state, evt({ eventId: "e1", sequence: 1 }));
    state = applyFormalEvent(state, evt({ eventId: "e3", sequence: 3 }));
    expect(state.resyncRequired).toBe(true);
    expect(state.lastSequence).toBe(1);
    const after = applyFormalEvent(state, evt({ eventId: "e2", sequence: 2 }));
    expect(after.events).toHaveLength(1);
  });

  it("run switch clears cursor and errors", () => {
    let state = emptyFormalEventReadModel("team-a", "run-a");
    state = applyFormalEvent(state, evt({ eventId: "e1", sequence: 1 }));
    state = { ...state, commandError: "boom", pendingRequestId: "req-1" };
    state = switchFormalEventScope(state, { teamId: "team-a", runId: "run-b" });
    expect(state.runId).toBe("run-b");
    expect(state.lastSequence).toBe(0);
    expect(state.events).toHaveLength(0);
    expect(state.commandError).toBeNull();
    expect(state.pendingRequestId).toBeNull();
    expect(state.generation).toBe(1);
  });

  it("applies contiguous sequences deterministically", () => {
    const state = applyFormalEventBatch(emptyFormalEventReadModel("team-a", "run-a"), [
      evt({ eventId: "e1", sequence: 1 }),
      evt({ eventId: "e2", sequence: 2 }),
    ]);
    expect(state.lastSequence).toBe(2);
    expect(state.events.map((item) => item.eventId)).toEqual(["e1", "e2"]);
  });

  it("hydrates cursor from snapshot latestEventSequence without fabricating events", () => {
    const hydrated = hydrateFormalEventFromSnapshot(
      emptyFormalEventReadModel("team-a", "run-old"),
      { teamId: "team-a", runId: "run-a", latestEventSequence: 7 },
    );
    expect(hydrated.runId).toBe("run-a");
    expect(hydrated.lastSequence).toBe(7);
    expect(hydrated.events).toEqual([]);
    const next = applyFormalEvent(
      hydrated,
      evt({ eventId: "e8", sequence: 8 }),
    );
    expect(next.resyncRequired).toBe(false);
    expect(next.lastSequence).toBe(8);
    const gap = applyFormalEvent(
      hydrated,
      evt({ eventId: "e10", sequence: 10 }),
    );
    expect(gap.resyncRequired).toBe(true);
  });

  it("treats unknown event types as generic events without resync", () => {
    let state = emptyFormalEventReadModel("team-a", "run-a");
    state = applyFormalEvent(state, evt({ eventId: "e1", sequence: 1 }));
    const unknownType = "workflow.brand_new.future_event";
    state = applyFormalEvent(
      state,
      evt({ eventId: "e2", sequence: 2, type: unknownType }),
    );
    // Unknown types must not crash, dirty the state, or force a resync —
    // they advance the cursor so snapshot refresh keeps the canvas current.
    expect(state.resyncRequired).toBe(false);
    expect(state.lastSequence).toBe(2);
    expect(state.events).toHaveLength(2);
    expect(state.events[1].type).toBe(unknownType);
    // A replayed unknown frame stays ignored (dedupe by id and sequence).
    expect(
      applyFormalEvent(state, evt({ eventId: "e2", sequence: 2, type: unknownType })),
    ).toBe(state);
  });
});

describe("formal snapshot reducer (T6)", () => {
  const snapshot = (runId: string, sequence: number): ResearchWorkflowSnapshot =>
    ({
      run: { runId, teamId: "team-a", runVersion: 1 },
      definition: {},
      nodeAttempts: {},
      activeNodeIds: [],
      pendingHumanTasks: [],
      commandOffers: [],
      handoffSummary: { countsByStatus: {}, refs: [], count: 0 },
      agentBindingSummary: {
        bindingSnapshotSetId: "b",
        bindingSnapshotIds: [],
        count: 0,
      },
      budgetSummary: { safetyLimits: {}, receiptRefs: [], receiptCount: 0 },
      latestEventSequence: sequence,
      generatedAt: "2026-08-12T14:00:00.000Z",
    }) as ResearchWorkflowSnapshot;

  it("ignores slow responses from a previous run generation", () => {
    let state = emptySnapshotReadModel();
    state = beginSnapshotFetch(state, {
      teamId: "team-a",
      runId: "run-a",
      requestId: "req-a",
    });
    const genA = state.generation;
    state = beginSnapshotFetch(state, {
      teamId: "team-a",
      runId: "run-b",
      requestId: "req-b",
    });
    expect(state.generation).toBe(genA + 1);
    state = applySnapshotResponse(state, {
      teamId: "team-a",
      runId: "run-a",
      requestId: "req-a",
      generation: genA,
      snapshot: snapshot("run-a", 9),
    });
    expect(state.runId).toBe("run-b");
    expect(state.snapshot).toBeNull();
    state = applySnapshotResponse(state, {
      teamId: "team-a",
      runId: "run-b",
      requestId: "req-b",
      generation: state.generation,
      snapshot: snapshot("run-b", 2),
    });
    expect(state.snapshot?.run.runId).toBe("run-b");
    expect(state.lastSequence).toBe(2);
  });

  it("same sequence snapshot does not invent a refetch loop flag", () => {
    let state = beginSnapshotFetch(emptySnapshotReadModel(), {
      teamId: "team-a",
      runId: "run-a",
      requestId: "req-1",
    });
    state = applySnapshotResponse(state, {
      teamId: "team-a",
      runId: "run-a",
      requestId: "req-1",
      generation: state.generation,
      snapshot: snapshot("run-a", 4),
    });
    const again = applySnapshotResponse(
      { ...state, pendingRequestId: "req-2" },
      {
        teamId: "team-a",
        runId: "run-a",
        requestId: "req-2",
        generation: state.generation,
        snapshot: snapshot("run-a", 4),
      },
    );
    expect(again.resyncRequired).toBe(false);
    expect(again.lastSequence).toBe(4);
  });
});
