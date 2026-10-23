import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TeamFlow, TeamFlowRun } from "./types/genericTeamWorkflow";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ fetchJson: transport, fetchJsonWithTimeout: transport }));
import {
  commandTeamFlowRun,
  getTeamFlowRecoveryBinding,
  listTeamFlowArtifacts,
  listTeamFlows,
  revokeTeamFlowRecoveryBinding,
  saveTeamFlow,
  saveTeamFlowRecoveryBinding,
  startTeamFlowRun,
  teamFlowKeys,
} from "./genericTeamWorkflows";

const flow: TeamFlow = { id: "flow-1", name: "My flow", description: "", fields: [], steps: [], revision: 3, updatedAt: "" };

describe("team-scoped user workflow transport", () => {
  beforeEach(() => { transport.mockReset(); });
  it("preserves an exact Session source without adding execution fields", async () => {
    const supervisor: TeamFlow = { ...flow, steps: [{ id: "source", label: "Session task", kind: "session",
      owner: "", instruction: "", sessionSource: { sessionId: "session-1", turnId: "turn-1", agentId: "agent-1" } }] };
    await saveTeamFlow("team-a", supervisor);
    expect(JSON.parse(transport.mock.calls[0][1].body).flow.steps[0]).toEqual(supervisor.steps[0]);
    expect(JSON.parse(transport.mock.calls[0][1].body).flow.steps[0]).not.toHaveProperty("researchSource");
  });
  it("sends saved revisions and keeps workflow/run identities separate", async () => {
    await saveTeamFlow("team-a", flow);
    const [url, request] = transport.mock.calls[0];
    expect(url).toBe("/api/teams/team-a/workflows/flow-1");
    expect(JSON.parse(request.body)).toEqual({ flow, expectedRevision: 3 });
    await startTeamFlowRun("team-a", flow, { custom: "value" }, "stable-submit");
    const legacyRunBody = JSON.parse(transport.mock.calls[1][1].body);
    expect(legacyRunBody).toEqual({ values: { custom: "value" }, expectedRevision: 3, idempotencyKey: "stable-submit" });
    expect(legacyRunBody).not.toHaveProperty("localIntegration");
  });
  it("sends local integration consent only when provided and preserves encoded run paths", async () => {
    const integration = {
      acknowledge: true as const,
      allowedFiles: ["src/feature.ts", "tests/feature.test.ts"],
      teamId: "team /a",
      validForSeconds: 900,
    };
    await startTeamFlowRun("team /a", { ...flow, id: "flow /b" }, {}, "stable-submit", integration);
    expect(transport.mock.calls[0][0]).toBe("/api/teams/team%20%2Fa/workflows/flow%20%2Fb/runs");
    expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual({
      values: {},
      expectedRevision: 3,
      idempotencyKey: "stable-submit",
      localIntegration: integration,
    });
  });
  it("uses exact run revision for commands and scopes artifact reads to the team", async () => {
    await commandTeamFlowRun("team-b", { id: "run-2", revision: 7 } as TeamFlowRun, "stop");
    expect(transport.mock.calls[0][0]).toBe("/api/teams/team-b/workflow-runs/run-2/commands");
    expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual({ action: "stop", expectedRevision: 7 });
    await listTeamFlowArtifacts("team-b", "run-2");
    expect(transport.mock.calls[1][0]).toBe("/api/teams/team-b/workflow-runs/run-2/artifacts");
    expect(teamFlowKeys.runs("team-a")).not.toEqual(teamFlowKeys.runs("team-b"));
  });
  it("reads the encoded recovery binding without sending a write request", async () => {
    const signal = new AbortController().signal;
    await getTeamFlowRecoveryBinding("team /a", "flow /b", signal);
    expect(transport.mock.calls[0]).toEqual([
      "/api/teams/team%20%2Fa/workflows/flow%20%2Fb/recovery-binding",
      { signal },
    ]);
    expect(transport.mock.calls[0][1]).not.toHaveProperty("method");
    expect(transport.mock.calls[0][1]).not.toHaveProperty("body");
  });
  it("sends typed binding and revoke payloads to their encoded endpoints", async () => {
    const request = {
      expectedRevision: 4,
      repairFlowId: "repair-flow",
      assistantAgentId: "assistant",
      directorAgentId: "director",
      developerAgentId: "developer",
      reviewerAgentId: "reviewer",
      acknowledgeAutomaticRecovery: true,
      replaySafety: "idempotent" as const,
      maxAttempts: 2,
      maxRepairAttempts: 1,
      repairTimeoutSeconds: 600,
      validForSeconds: 7200,
    };
    await saveTeamFlowRecoveryBinding("team-a", "flow/a", request);
    expect(transport.mock.calls[0][0]).toBe("/api/teams/team-a/workflows/flow%2Fa/recovery-binding");
    expect(transport.mock.calls[0][1].method).toBe("PUT");
    expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual(request);

    await revokeTeamFlowRecoveryBinding("team-a", "flow/a", { expectedRevision: 5 });
    expect(transport.mock.calls[1][0]).toBe("/api/teams/team-a/workflows/flow%2Fa/recovery-binding/revoke");
    expect(transport.mock.calls[1][1].method).toBe("POST");
    expect(JSON.parse(transport.mock.calls[1][1].body)).toEqual({ expectedRevision: 5 });
  });
  it("sends deployment evidence only when supplied for the new command", async () => {
    const run = { id: "run-3", revision: 8 } as TeamFlowRun;
    await commandTeamFlowRun("team-a", run, "confirm_deployment", "artifact://deploy/3");
    expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual({
      action: "confirm_deployment",
      expectedRevision: 8,
      evidenceRef: "artifact://deploy/3",
    });
    await commandTeamFlowRun("team-a", run, "confirm");
    expect(JSON.parse(transport.mock.calls[1][1].body)).toEqual({ action: "confirm", expectedRevision: 8 });
  });
  it("rejects empty team scope before transport", () => {
    expect(() => listTeamFlows("")).toThrow("请先选择团队");
    expect(transport).not.toHaveBeenCalled();
  });
  it("bounds management writes and reports uncertain timeouts without resending", async () => {
    transport.mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    const failure = await startTeamFlowRun("team-a", flow, {}, "stable-submit").catch(error => error);
    expect(failure.message).toContain("结果尚未确认");
    expect(failure.name).toBe("TeamFlowWriteOutcomeUnknownError");
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][1].timeoutMs).toBe(60_000);
  });
  it("bounds and cancels the authoritative flow readback", async () => {
    const signal = new AbortController().signal;
    await listTeamFlows("team-a", signal);
    expect(transport.mock.calls[0]).toEqual(["/api/teams/team-a/workflows", { signal, timeoutMs: 10_000 }]);
  });
});
