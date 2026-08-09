/**
 * Frontend node-command registry contracts:
 * - every command a capability can expose is either executable or explicitly
 *   unavailable (no command renders as a fake clickable button);
 * - human-gate commands require the CURRENT node's pending task id.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeCommandCapability } from "../../../api/types/researchWorkflow";

const api = vi.hoisted(() => ({
  postResearchWorkflowNodeCommand: vi.fn(),
  resolveResearchWorkflowHumanTask: vi.fn(),
}));

vi.mock("../../../api/researchWorkflow", () => api);

import {
  commandLabel,
  disableReasonFor,
  executeNodeCommand,
} from "./nodeCommandAdapter";

const ALL_BACKEND_COMMANDS = [
  "start_agent_task",
  "run_smoke",
  "start_controlled_run",
  "view_artifacts",
  "rebind_node",
  "accept_handoff",
  "reject_handoff",
  "revise",
  "open_session",
  "build_package",
  "open_evidence_graph",
];

describe("nodeCommandAdapter", () => {
  beforeEach(() => {
    api.postResearchWorkflowNodeCommand.mockReset();
    api.resolveResearchWorkflowHumanTask.mockReset();
  });

  it("every backend-declared command is executable (availability from backend)", () => {
    for (const command of ALL_BACKEND_COMMANDS) {
      expect(disableReasonFor({ command, available: true, reason: "" })).toBe("");
    }
    // Backend-declared unavailability keeps its reason.
    expect(disableReasonFor({ command: "build_package", available: false, reason: "尚无迭代决策" })).toBe(
      "尚无迭代决策",
    );
  });

  it("executes non-human commands through the backend node-command API", async () => {
    api.postResearchWorkflowNodeCommand.mockResolvedValue({ command: "view_artifacts", artifacts: {} });
    const result = await executeNodeCommand(
      { runId: "run-1", nodeId: "source_finding", teamId: "t1", runVersion: 7 },
      { command: "view_artifacts", available: true, reason: "" },
    );
    expect(api.postResearchWorkflowNodeCommand).toHaveBeenCalledWith(
      "run-1",
      "source_finding",
      {
        teamId: "t1",
        expectedRunVersion: 7,
        idempotencyKey: "node:run-1:source_finding:view_artifacts:v7",
        command: "view_artifacts",
        payload: {},
      },
    );
    expect(result.command).toBe("view_artifacts");
  });

  it("passes the backend-owned Agent budget payload without inventing defaults", async () => {
    api.postResearchWorkflowNodeCommand.mockResolvedValue({ command: "start_agent_task" });
    const payload = {
      budgetRequest: {
        tokens: 250,
        toolCalls: 3,
        wallClockSeconds: 30,
        experiments: 1,
        computeUnits: 5,
      },
    };

    await executeNodeCommand(
      { runId: "run-1", nodeId: "source_finding", teamId: "t1", runVersion: 7 },
      {
        command: "start_agent_task",
        available: true,
        reason: "",
        idempotencyKey: "agent-task:nr-run-1-source_finding-a1",
        payload,
      },
    );

    expect(api.postResearchWorkflowNodeCommand).toHaveBeenCalledWith(
      "run-1",
      "source_finding",
      expect.objectContaining({ payload }),
    );
    expect(api.postResearchWorkflowNodeCommand).toHaveBeenCalledWith(
      "run-1",
      "source_finding",
      expect.objectContaining({
        idempotencyKey: "agent-task:nr-run-1-source_finding-a1",
      }),
    );
  });

  it("fails closed when an Agent start capability has no backend budget payload", async () => {
    await expect(
      executeNodeCommand(
        { runId: "run-1", nodeId: "source_finding", teamId: "t1", runVersion: 7 },
        { command: "start_agent_task", available: true, reason: "" },
      ),
    ).rejects.toThrow("启动 Agent 任务缺少后端幂等与预算契约");
    expect(api.postResearchWorkflowNodeCommand).not.toHaveBeenCalled();
  });

  it("fails closed when an Agent start capability has no backend idempotency key", async () => {
    await expect(
      executeNodeCommand(
        { runId: "run-1", nodeId: "source_finding", teamId: "t1", runVersion: 7 },
        {
          command: "start_agent_task",
          available: true,
          reason: "",
          payload: { budgetRequest: { tokens: 250 } },
        },
      ),
    ).rejects.toThrow("启动 Agent 任务缺少后端幂等与预算契约");
    expect(api.postResearchWorkflowNodeCommand).not.toHaveBeenCalled();
  });

  it("executes human-gate commands with the CURRENT node's pending task id", async () => {
    api.resolveResearchWorkflowHumanTask.mockResolvedValue({ runId: "run-1" });
    await executeNodeCommand(
      { runId: "run-1", nodeId: "knowledge_handoff", teamId: "t1", runVersion: 8, pendingHumanTaskId: "ht-current" },
      { command: "accept_handoff", available: true, reason: "" },
    );
    expect(api.resolveResearchWorkflowHumanTask).toHaveBeenCalledWith(
      "run-1",
      "ht-current",
      {
        teamId: "t1",
        expectedRunVersion: 8,
        idempotencyKey: "node:run-1:knowledge_handoff:accept_handoff:v8",
        decision: "accept",
      },
    );
  });

  it("rejects a human-gate command without the current node's task id", async () => {
    await expect(
      executeNodeCommand(
        { runId: "run-1", nodeId: "knowledge_handoff", teamId: "t1", runVersion: 3 },
        { command: "accept_handoff", available: true, reason: "" },
      ),
    ).rejects.toThrow("当前节点没有待处理的人工任务");
    expect(api.resolveResearchWorkflowHumanTask).not.toHaveBeenCalled();
  });

  it("rejects unavailable capabilities before any API call", async () => {
    await expect(
      executeNodeCommand(
        { runId: "run-1", nodeId: "source_finding", teamId: "t1", runVersion: 3 },
        { command: "run_smoke", available: false, reason: "缺少 planId" },
      ),
    ).rejects.toThrow("缺少 planId");
    expect(api.postResearchWorkflowNodeCommand).not.toHaveBeenCalled();
  });

  it("labels every known command", () => {
    for (const command of ALL_BACKEND_COMMANDS) {
      expect(commandLabel(command).length).toBeGreaterThan(0);
    }
  });
});
