/** @vitest-environment happy-dom */
import { afterEach, describe, expect, it, vi } from "vitest";

import { listVirtualHumanCompanionBindings } from "./agentPlugins";
import { clearControlToken, seedControlTokenForTests } from "./client";

import apiSource from "./agentPlugins.ts?raw";
import lifeApiSource from "./virtualHumanLife.ts?raw";
import typeSource from "./types/virtualHumanLife.ts?raw";

describe("virtual human life frontend API", () => {
  afterEach(() => {
    clearControlToken();
    vi.unstubAllGlobals();
  });

  it("reads only route bindings through the typed transport and forwards cancellation", async () => {
    seedControlTokenForTests();
    const rows = [{ agentId: "companion", directSessionId: "native-session" }];
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(rows), {
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(listVirtualHumanCompanionBindings({ signal: controller.signal })).resolves.toEqual(rows);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/agent-plugins/virtual-human-life/companion-bindings");
    expect(init.signal).toBe(controller.signal);
  });

  it("owns plugin binding and companion-lobby transports outside routes", () => {
    expect(apiSource).toContain("listAgentPlugins");
    expect(apiSource).toContain("updateAgentPluginBinding");
    expect(apiSource).toContain("listVirtualHumanCompanions");
    expect(apiSource).toContain("listVirtualHumanCompanionActivity");
    expect(apiSource).toContain("/api/agent-plugins/virtual-human-life/companion-activity");
    expect(apiSource).toContain("listVirtualHumanLocations");
    expect(apiSource).toContain("/api/agent-plugins/virtual-human-life/companions");
    expect(apiSource).toContain("/api/agent-plugins/virtual-human-life/locations");
    expect(apiSource).toContain('method: "PUT"');
  });

  it("owns Agent-scoped life snapshot, memory transport, and typed health state", () => {
    expect(lifeApiSource).toContain("fetchVirtualHumanSnapshot");
    expect(lifeApiSource).toContain("fetchVirtualHumanMemories");
    expect(lifeApiSource).toContain("executeVirtualHumanCommand");
    expect(lifeApiSource).toContain("updateVirtualHumanLifeDraft");
    expect(lifeApiSource).toContain("confirmVirtualHumanLifeWorld");
    expect(lifeApiSource).toContain("/plugins/virtual-human-life/life-world/draft");
    expect(lifeApiSource).toContain("/plugins/virtual-human-life/life-world/confirm");
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
    expect(typeSource).toContain("export type VirtualHumanLifeWorld");
    expect(typeSource).toContain("export type VirtualHumanLifeStewardBinding");
    expect(typeSource).toContain("health?: VirtualHumanSnapshotHealth");
    expect(typeSource).toContain("export type VirtualHumanActivity");
    expect(typeSource).toContain("directSessionId: string");
  });
});
