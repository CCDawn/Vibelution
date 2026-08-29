import { describe, expect, it } from "vitest";

import apiSource from "./agentPlugins.ts?raw";
import lifeApiSource from "./virtualHumanLife.ts?raw";
import typeSource from "./types/virtualHumanLife.ts?raw";

describe("virtual human life frontend API", () => {
  it("owns plugin binding and companion-lobby transports outside routes", () => {
    expect(apiSource).toContain("listAgentPlugins");
    expect(apiSource).toContain("updateAgentPluginBinding");
    expect(apiSource).toContain("listVirtualHumanCompanions");
    expect(apiSource).toContain("/api/agent-plugins/virtual-human-life/companions");
    expect(apiSource).toContain('method: "PUT"');
  });

  it("owns Agent-scoped life snapshot, memory transport, and typed health state", () => {
    expect(lifeApiSource).toContain("fetchVirtualHumanSnapshot");
    expect(lifeApiSource).toContain("fetchVirtualHumanMemories");
    expect(lifeApiSource).toContain("executeVirtualHumanCommand");
    expect(lifeApiSource).toContain("/plugins/virtual-human-life/commands");
    expect(lifeApiSource).toContain('method: "POST"');
    expect(lifeApiSource).toContain("/plugins/virtual-human-life/memories");
    expect(lifeApiSource).toContain("limit");
    expect(lifeApiSource).toContain("encodeURIComponent(agentId)");
    expect(typeSource).toContain("export type VirtualHumanSnapshot");
    expect(typeSource).toContain("export type VirtualHumanSnapshotHealth");
    expect(typeSource).toContain("export type VirtualHumanEpisodicMemory");
    expect(typeSource).toContain("export type VirtualHumanCommandRequest");
    expect(typeSource).toContain("export type VirtualHumanCommandResponse");
    expect(typeSource).toContain("health?: VirtualHumanSnapshotHealth");
    expect(typeSource).toContain("export type VirtualHumanActivity");
    expect(typeSource).toContain("directSessionId: string");
  });
});
