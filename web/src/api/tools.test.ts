import { afterEach, describe, expect, it, vi } from "vitest";
import { deleteTool, setGeneratedToolEnabled } from "./tools";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";

import apiSource from "./tools.ts?raw";
import agentsRouteSource from "../routes/AgentsRoute.tsx?raw";
import wizardSource from "../routes/agent-create/AgentCreateWizardDialog.tsx?raw";
import routeSource from "../routes/ToolsRoute.tsx?raw";

describe("bounded tool writes", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); resetControlTokenForTests(); });
  it.each([
    ["enable", () => setGeneratedToolEnabled("a/b", false), "/api/tools/generated/a%2Fb/enabled", "PUT"],
    ["delete", () => deleteTool("a/b"), "/api/tools/a%2Fb", "DELETE"],
  ] as const)("bounds %s and never automatically repeats the write", async (_name, execute, endpoint, method) => {
    vi.useFakeTimers(); seedControlTokenForTests();
    const fetchMock = vi.fn((_input: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);
    let failure: unknown;
    const pending = execute().catch(error => { failure = error; });
    await vi.advanceTimersByTimeAsync(60_001);
    expect(failure).toMatchObject({ name: "TimeoutError" });
    await pending;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]).toMatchObject([endpoint, { method }]);
  });
});

describe("tools catalog API", () => {
  it("owns the tools JSON transports", () => {
    expect(apiSource).toContain("export function fetchToolRegistry");
    expect(apiSource).toContain("export function fetchToolImage2Models");
    expect(apiSource).toContain("export function setGeneratedToolEnabled");
    expect(apiSource).toContain("export function deleteTool");
    expect(apiSource).toContain("export function testTool");
    expect(apiSource).toContain("export function setToolImage2DefaultModel");
    expect(apiSource).toContain("export function fetchWebSearchToolHealth");
    expect(apiSource).toContain("export function bulkSetGeneratedToolsEnabled");
    expect(apiSource).toContain("export function bulkDeleteToolRegistry");
    expect(apiSource).toContain('"/api/tools"');
    expect(apiSource).toContain('"/api/tools/image2/models"');
    expect(apiSource).toContain("/api/tools/generated/${encodeURIComponent(toolId)}/enabled");
    expect(apiSource).toContain("/api/tools/${encodeURIComponent(toolId)}");
    expect(apiSource).toContain("/api/tools/${encodeURIComponent(payload.toolId)}/test");
    expect(apiSource).toContain('"/api/tools/image2/default-model"');
    expect(apiSource).toContain('"/api/tools/web-search/health"');
    expect(apiSource).toContain('"/api/tools/generated/bulk-enabled"');
    expect(apiSource).toContain('"/api/tools/bulk-delete"');
  });

  it("keeps ToolsRoute free of tools JSON paths", () => {
    expect(routeSource).toContain("fetchToolRegistry(");
    expect(routeSource).toContain("fetchToolImage2Models(");
    expect(routeSource).toContain("setGeneratedToolEnabled(");
    expect(routeSource).toContain("deleteTool(");
    expect(routeSource).toContain("testTool(");
    expect(routeSource).toContain("setToolImage2DefaultModel(");
    expect(routeSource).toContain("fetchWebSearchToolHealth(");
    expect(routeSource).toContain("bulkSetGeneratedToolsEnabled(");
    expect(routeSource).toContain("bulkDeleteToolRegistry(");
    expect(routeSource).not.toContain("/api/tools/");
    expect(routeSource).not.toContain('from "../api/client"');
  });

  it("keeps AgentsRoute and the create wizard on fetchToolRegistry", () => {
    expect(agentsRouteSource).toContain("fetchToolRegistry(");
    expect(agentsRouteSource).not.toContain('"/api/tools"');
    expect(wizardSource).toContain("fetchToolRegistry(");
    expect(wizardSource).not.toContain('"/api/tools"');
  });
});
