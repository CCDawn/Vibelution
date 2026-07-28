import { describe, expect, it } from "vitest";

import {
  buildResearchProjectAgentTaskIdempotencyKey,
  latestResearchProjectAgentTaskByKind,
  researchProjectAgentTaskStatusQueryKey,
} from "./useResearchProjectAgentTasks";
import type { TeamResearchProjectAgentTask } from "../../../api/types";
import hookSource from "./useResearchProjectAgentTasks.ts?raw";
import launcherSource from "../../TeamResearchStageLauncherPanel.tsx?raw";

function task(
  taskKind: TeamResearchProjectAgentTask["taskKind"],
  taskId: string,
  updatedAt: string,
): TeamResearchProjectAgentTask {
  return {
    schemaVersion: 1,
    taskId,
    idempotencyKey: `key-${taskId}`,
    taskKind,
    taskTitle: taskKind,
    teamId: "team-a",
    researchProjectId: "project-a",
    experimentName: "实验 A",
    targetRef: "",
    agentId: `agent-${taskKind}`,
    teamRole: taskKind,
    roleKey: taskKind,
    roleLabel: taskKind,
    sessionId: `session-${taskId}`,
    sessionTitle: `实验 A｜${taskKind}`,
    sessionAttempt: 1,
    sessionCreated: true,
    retryOfSessionId: "",
    retrySourceTaskId: "",
    formalRetry: false,
    status: "completed",
    turn: { accepted: true, turnId: "turn-a", status: "accepted", acceptedAt: updatedAt },
    resultRefs: [],
    failureCode: "",
    returnTo: "/teams?team=team-a",
    returnLabel: "返回科研工作台",
    createdAt: updatedAt,
    updatedAt,
    chatRoute: `/chat?session=session-${taskId}`,
  };
}

describe("useResearchProjectAgentTasks", () => {
  it("isolates task status by team and active research project", () => {
    expect(researchProjectAgentTaskStatusQueryKey("team-a", "project-a")).toEqual([
      "teams",
      "team-a",
      "research-projects",
      "project-a",
      "agent-tasks",
    ]);
  });

  it("selects the latest task for each fixed responsibility", () => {
    const older = task("experiment_design", "older", "2026-07-27T01:00:00Z");
    const newer = task("experiment_design", "newer", "2026-07-27T02:00:00Z");
    const evidence = task("experiment_evidence_review", "evidence", "2026-07-27T03:00:00Z");

    expect(latestResearchProjectAgentTaskByKind([newer, evidence, older], "experiment_design")?.taskId).toBe("newer");
    expect(latestResearchProjectAgentTaskByKind([newer, evidence, older], "iteration_decision")).toBeNull();
  });

  it("creates bounded click keys without coupling to direct sessions", () => {
    expect(buildResearchProjectAgentTaskIdempotencyKey("experiment_design", "nonce-a")).toBe(
      "research-project-ui:experiment_design:nonce-a",
    );
    expect(hookSource).toContain("getResearchProjectAgentTaskStatus");
    expect(hookSource).toContain("startResearchProjectAgentTask");
    expect(launcherSource).toContain("payload.chatRoute");
    expect(launcherSource).toContain("navigate(payload.chatRoute)");
    expect(hookSource).not.toContain("directSessionId");
  });
});
