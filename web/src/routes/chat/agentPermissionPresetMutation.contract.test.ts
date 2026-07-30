import { describe, expect, it } from "vitest";

import routeSource from "../ChatCodingRoute.tsx?raw";
import apiSource from "../../api/agents.ts?raw";
import mutationSource from "./useAgentPermissionPresetMutation.ts?raw";

describe("chat Agent permission preset mutation contract", () => {
  it("writes the owning Agent with revision-bound concurrency control", () => {
    expect(mutationSource).toContain("updateAgentPermissionPreset");
    expect(apiSource).toContain("permissionPreset: payload.permissionPreset");
    expect(apiSource).toContain("expectedConfigRevision: payload.expectedConfigRevision");
    expect(apiSource).toContain("/api/agents/");
    expect(mutationSource).not.toContain("/api/sessions/");
  });

  it("projects the active session Agent into the composer control", () => {
    expect(routeSource).toContain("useAgentPermissionPresetMutation");
    expect(routeSource).toContain("permissionControl:");
    expect(routeSource).toContain("activeSessionAgent.permissionPreset");
    expect(routeSource).toContain("activeSessionAgent.configRevision");
  });
});
