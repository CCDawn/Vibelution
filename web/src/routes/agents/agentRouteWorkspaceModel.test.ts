import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent } from "../../api/types";
import {
  buildLightweightAgentWorkspace,
  filterAgents,
  findRuntimeFocusEvidence,
  referenceLabel,
  selectedAgentFromList,
} from "./agentRouteWorkspaceModel";

describe("agentRouteWorkspaceModel", () => {
  it("builds a lightweight workspace and filters archived agents", () => {
    const agents = [
      { agentId: "a1", status: "active", primaryMode: "chat", references: [], health: [] },
      { agentId: "a2", status: "archived", primaryMode: "chat", references: [], health: [] },
    ] as AgentConfigWorkspaceAgent[];
    const workspace = buildLightweightAgentWorkspace(agents, Date.now());
    expect(workspace.summary.activeAgentCount).toBe(1);
    expect(workspace.agents).toHaveLength(2);

    const visible = filterAgents(workspace, "active", "");
    expect(visible.map((item) => item.agentId)).toEqual(["a1"]);
    const archived = filterAgents(workspace, "archived", "");
    expect(archived.map((item) => item.agentId)).toEqual(["a2"]);
    expect(selectedAgentFromList(visible, "missing", agents, "active")?.agentId).toBe("a1");
  });

  it("labels references and resolves runtime focus evidence reasons", () => {
    expect(referenceLabel({ kind: "team" } as never, "zh")).toContain("团队");
    const result = findRuntimeFocusEvidence(
      {
        agentId: "a1",
        directSessionId: "s1",
        runtimeStatus: { sessionId: "s1", runId: "run-9" },
      } as AgentConfigWorkspaceAgent,
      {
        matches: [{ matchedFields: { sessionId: "s1" } }],
      } as never,
    );
    expect(result.reason).toBe("session");
  });
});
