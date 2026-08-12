import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import type { ResearchWorkflowSnapshot } from "./core";
import type { CommandOffer } from "./commands";
import type { WorkflowEventEnvelope } from "./events";

const coreSource = readFileSync(resolve(import.meta.dirname, "core.ts"), "utf8");

describe("researchWorkflow formal contracts (T6)", () => {
  it("snapshot type forbids UI-only fields in source", () => {
    expect(coreSource).not.toMatch(/selectedNodeId\s*:/);
    expect(coreSource).not.toMatch(/viewport\s*:/);
    expect(coreSource).not.toMatch(/hover\s*:/);
    expect(coreSource).toContain("latestEventSequence");
    expect(coreSource).toContain("commandOffers");
    expect(coreSource).toContain("generatedAt");
  });

  it("accepts a typed snapshot and event envelope shape", () => {
    const offer: CommandOffer = {
      command: "start_node",
      nodeId: "source_finding",
      available: true,
      label: "启动",
      reasonCode: "ready",
      blockerIds: [],
      idempotencyKey: "offer:run-1:source_finding:start_node:v1",
      expectedRunVersion: 1,
      payload: {},
    };
    const snapshot: ResearchWorkflowSnapshot = {
      run: {
        runId: "run-1",
        teamId: "research-team",
        workflowId: "challenge-cup-research",
        workflowVersionId: "challenge-cup-research-v2.1.0",
        threadId: "thread-1",
        projectId: "challenge-sci-096",
        questionId: "SCI-096",
        status: "running",
        runVersion: 1,
        inputSnapshotHash: "a".repeat(64),
        bindingSnapshotSetId: "binding-set-1",
        activeNodeId: "source_finding",
        parentRunId: null,
        forkedFromCheckpointId: null,
        completionKind: null,
        terminalReason: null,
        createdAtMs: 1,
        updatedAtMs: 1,
        completedAtMs: null,
      },
      definition: { workflowId: "challenge-cup-research" },
      nodeAttempts: {},
      activeNodeIds: ["source_finding"],
      pendingHumanTasks: [],
      commandOffers: [offer],
      handoffSummary: { countsByStatus: {}, refs: [], count: 0 },
      agentBindingSummary: {
        bindingSnapshotSetId: "binding-set-1",
        bindingSnapshotIds: [],
        count: 0,
      },
      budgetSummary: { safetyLimits: {}, receiptRefs: [], receiptCount: 0 },
      latestEventSequence: 3,
      generatedAt: "2026-08-12T14:00:00.000Z",
    };
    const event: WorkflowEventEnvelope = {
      eventId: "evt-1",
      sequence: 1,
      runId: "run-1",
      teamId: "research-team",
      runVersion: 1,
      type: "run_created",
      correlationId: "corr-1",
      occurredAt: "2026-08-12T14:00:00.000Z",
      payload: {},
    };
    expect(snapshot.latestEventSequence).toBe(3);
    expect(event.sequence).toBe(1);
  });
});
