import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "../../../api/client";
import {
  createResearchWorkflowRun,
  fetchEffectiveAgentBindings,
  fetchResearchWorkflowCanvas,
  fetchResearchWorkflowBudget,
  fetchResearchWorkflowEvaluation,
  fetchResearchWorkflowEvents,
  fetchResearchWorkflowExperimentCampaigns,
  fetchResearchWorkflowHandoffs,
  fetchResearchWorkflowHypotheses,
  fetchResearchWorkflowNodeDetail,
  fetchResearchWorkflowResearchLedger,
  fetchResearchWorkflowRun,
  listResearchWorkflowRuns,
  postResearchWorkflowCommand,
  postResearchWorkflowNodeCommand,
  putResearchWorkflowAgentBindings,
  putResearchWorkflowSessionBinding,
  resolveResearchWorkflowHumanTask,
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
    await expect(createResearchWorkflowRun({ teamId: "\t" })).rejects.toThrow("teamId is required");
    await expect(
      putResearchWorkflowAgentBindings("challenge-cup-research", {
        teamId: " ",
        workflowDefaults: {},
      }),
    ).rejects.toThrow("teamId is required");
    expect(mockedFetchJson).not.toHaveBeenCalled();
  });

  it("scopes every run query and versions every run command", async () => {
    mockedFetchJson.mockResolvedValue({});

    await fetchResearchWorkflowRun("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowCanvas("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowNodeDetail("run-1", "source_finding", {
      teamId: "research-team",
    });
    await fetchResearchWorkflowEvents("run-1", { teamId: "research-team", afterSequence: 7 });
    await fetchResearchWorkflowHandoffs("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowResearchLedger("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowBudget("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowHypotheses("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowExperimentCampaigns("run-1", { teamId: "research-team" });
    await fetchResearchWorkflowEvaluation("run-1", { teamId: "research-team" });

    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      1,
      "/api/research/workflow-runs/run-1?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      2,
      "/api/research/workflow-runs/run-1/canvas?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      3,
      "/api/research/workflow-runs/run-1/nodes/source_finding?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      4,
      "/api/research/workflow-runs/run-1/events?teamId=research-team&afterSequence=7",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      5,
      "/api/research/workflow-runs/run-1/handoffs?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      6,
      "/api/research/workflow-runs/run-1/research-ledger?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      7,
      "/api/research/workflow-runs/run-1/budget?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      8,
      "/api/research/workflow-runs/run-1/hypotheses?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      9,
      "/api/research/workflow-runs/run-1/experiment-campaigns?teamId=research-team",
    );
    expect(mockedFetchJson).toHaveBeenNthCalledWith(
      10,
      "/api/research/workflow-runs/run-1/evaluation?teamId=research-team",
    );

    const command = {
      teamId: "research-team",
      idempotencyKey: "command-1",
      expectedRunVersion: 4,
    };
    await postResearchWorkflowCommand("run-1", { ...command, command: "cancel", payload: {} });
    await postResearchWorkflowNodeCommand("run-1", "source_finding", {
      ...command,
      command: "start_agent_task",
      payload: {},
    });
    await resolveResearchWorkflowHumanTask("run-1", "task-1", {
      ...command,
      decision: "accept",
    });
    await putResearchWorkflowSessionBinding("run-1", "source_finding", {
      ...command,
      sessionId: "session-1",
      taskId: "task-1",
      turnId: "turn-1",
    });

    for (const call of mockedFetchJson.mock.calls.slice(10)) {
      const init = call[1] as RequestInit;
      const body = JSON.parse(String(init.body));
      expect(init.headers).toEqual({ "Content-Type": "application/json" });
      expect(body).toMatchObject(command);
    }
  });

  it("sends create-run payloads as JSON objects", async () => {
    mockedFetchJson.mockResolvedValue({ runId: "run-1" });
    await createResearchWorkflowRun({
      teamId: "research-team",
      projectId: "research-project",
      questionId: "question-1",
      researchBriefHash: "sha256:brief",
      datasetRefs: [],
      metricContract: {},
      constraintSnapshot: {},
      competitionRuleRef: "rules/ref",
      competitionRuleVersion: "v1",
      trackAndRubricSnapshot: {},
      researchObjectiveContract: {},
      sourcePolicy: {},
      budgetPolicy: {},
      stopPolicy: {},
      environmentSnapshotRef: "environment/ref",
      modelRoutingPolicy: {},
      evaluationContract: {},
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
});
