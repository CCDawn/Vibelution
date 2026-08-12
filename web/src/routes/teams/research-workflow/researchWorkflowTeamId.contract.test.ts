import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "../../../api/client";
import {
  createResearchWorkflowRun,
  fetchEffectiveAgentBindings,
  fetchResearchWorkflowBudget,
  fetchResearchWorkflowEvaluation,
  fetchResearchWorkflowExperimentCampaigns,
  fetchResearchWorkflowHandoffs,
  fetchResearchWorkflowHypotheses,
  fetchResearchWorkflowResearchLedger,
  listResearchWorkflowRuns,
  putResearchWorkflowAgentBindings,
  submitResearchWorkflowCommand,
} from "../../../api/researchWorkflow";

vi.mock("../../../api/client", () => ({
  fetchJson: vi.fn(),
}));

const mockedFetchJson = vi.mocked(fetchJson);

describe("researchWorkflow teamId contract", () => {
  beforeEach(() => {
    mockedFetchJson.mockReset();
  });

  it("uses canonical teamId for every team-scoped read", async () => {
    mockedFetchJson.mockResolvedValue({ workflowId: "challenge-cup-research", runs: [] });
    await listResearchWorkflowRuns("challenge-cup-research", { teamId: "research-team" });
    expect(mockedFetchJson).toHaveBeenCalledWith(
      "/api/research/workflows/challenge-cup-research/runs?teamId=research-team",
    );

    mockedFetchJson.mockResolvedValue({
      workflowId: "challenge-cup-research",
      workflowVersionId: "v1",
      teamId: "research-team",
      bindings: [],
    });
    await fetchEffectiveAgentBindings("challenge-cup-research", { teamId: "research-team" });
    expect(mockedFetchJson).toHaveBeenLastCalledWith(
      "/api/research/workflows/challenge-cup-research/agent-bindings/effective?teamId=research-team",
    );
  });

  it("fails before issuing an unscoped or blank-team request", async () => {
    await expect(
      listResearchWorkflowRuns("challenge-cup-research", { teamId: "  " }),
    ).rejects.toThrow("teamId is required");
    await expect(
      fetchEffectiveAgentBindings("challenge-cup-research", { teamId: "" }),
    ).rejects.toThrow("teamId is required");
    await expect(
      createResearchWorkflowRun({
        teamId: "\t",
        questionId: "SCI-096",
        safetyLimits: {
          stageTokens: {
            knowledge_collection: 1,
            experiment_design: 1,
            execution_iteration: 1,
          },
          toolCalls: 1,
          wallClockSeconds: 1,
          maxRetries: 1,
        },
        idempotencyKey: "create-1",
      }),
    ).rejects.toThrow("teamId is required");
    await expect(
      putResearchWorkflowAgentBindings("challenge-cup-research", {
        teamId: " ",
        workflowDefaults: {},
      }),
    ).rejects.toThrow("teamId is required");
    expect(mockedFetchJson).not.toHaveBeenCalled();
  });

  it("scopes every retained domain projection query", async () => {
    mockedFetchJson.mockResolvedValue({});

    await fetchResearchWorkflowHandoffs("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowResearchLedger("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowBudget("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowHypotheses("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowExperimentCampaigns("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowEvaluation("run-1", { teamId: "research-team" });

    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      1,
      "/api/research/workflow-runs/run-1/handoffs?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      2,
      "/api/research/workflow-runs/run-1/research-ledger?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      3,
      "/api/research/workflow-runs/run-1/budget?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      4,
      "/api/research/workflow-runs/run-1/hypotheses?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      5,
      "/api/research/workflow-runs/run-1/experiment-campaigns?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      6,
      "/api/research/workflow-runs/run-1/evaluation?teamId=research-team",
    );
  });

  it("sends create-run payloads as JSON objects", async () => {
    mockedFetchJson.mockResolvedValue({ runId: "run-1" });
    await createResearchWorkflowRun({
      teamId: "research-team",
      questionId: "question-1",
      safetyLimits: {
        stageTokens: {
          knowledge_collection: 250000,
          experiment_design: 250000,
          execution_iteration: 250000,
        },
        toolCalls: 300,
        wallClockSeconds: 21600,
        maxRetries: 2,
      },
      idempotencyKey: "create-run-1",
    });

    const init = mockedFetchJson.mock.calls[0][1] as RequestInit;
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toMatchObject({
      teamId: "research-team",
      questionId: "question-1",
      idempotencyKey: "create-run-1",
    });
  });

  it("posts typed commands only to the canonical commands entry", async () => {
    mockedFetchJson.mockResolvedValue({
      commandId: "cmd-1",
      runId: "run-1",
      status: "accepted",
      acceptedRunVersion: 4,
      idempotencyKey: "command-1",
      latestEventSequence: 2,
      problem: null,
    });
    await submitResearchWorkflowCommand({
      teamId: "research-team",
      runId: "run-1",
      command: "cancel_run",
      expectedRunVersion: 4,
      idempotencyKey: "command-1",
      nodeId: "source_finding",
      payload: {},
    });
    expect(mockedFetchJson).toHaveBeenCalledTimes(1);
    const [url, init] = mockedFetchJson.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/research/workflow-runs/run-1/commands");
    expect(url).not.toContain("/nodes/");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body).toMatchObject({
      teamId: "research-team",
      command: "cancel_run",
      expectedRunVersion: 4,
      idempotencyKey: "command-1",
      nodeId: "source_finding",
    });
  });
});
