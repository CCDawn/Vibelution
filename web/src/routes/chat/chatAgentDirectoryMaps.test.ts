import { describe, expect, it } from "vitest";

import type { AgentInstance } from "../../api/types";
import {
  buildAgentsByCode,
  buildAgentsById,
  buildArchiveVisibleAgents,
} from "./chatAgentDirectoryMaps";

function agent(overrides: Partial<AgentInstance> = {}): AgentInstance {
  return {
    agentId: "agent-1",
    agentCode: "luna",
    displayName: "Luna",
    ...overrides,
  } as AgentInstance;
}

describe("chatAgentDirectoryMaps", () => {
  it("indexes agents by id and non-empty code", () => {
    const agents = [
      agent({ agentId: "a1", agentCode: "luna" }),
      agent({ agentId: "a2", agentCode: "  " }),
      agent({ agentId: "a3", agentCode: "gpt" }),
    ];
    expect([...buildAgentsById(agents).keys()]).toEqual(["a1", "a2", "a3"]);
    expect([...buildAgentsByCode(agents).keys()]).toEqual(["luna", "gpt"]);
  });

  it("hides agents that are pending archive", () => {
    const visible = buildArchiveVisibleAgents(
      [agent({ agentId: "keep" }), agent({ agentId: "gone" })],
      new Set(["gone"]),
    );
    expect(visible.map((item) => item.agentId)).toEqual(["keep"]);
  });
});
