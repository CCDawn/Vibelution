import { describe, expect, it } from "vitest";

import apiSource from "./agents.ts?raw";
import mutationSource from "../routes/chat/useAgentPermissionPresetMutation.ts?raw";

describe("Agent permission preset API", () => {
  it("owns the revision-bound Agent permission transport", () => {
    expect(apiSource).toContain("/api/agents/");
    expect(apiSource).toContain("permissionPreset: payload.permissionPreset");
    expect(apiSource).toContain("expectedConfigRevision: payload.expectedConfigRevision");
  });

  it("keeps React Query orchestration free of direct transport calls", () => {
    expect(mutationSource).toContain("updateAgentPermissionPreset");
    expect(mutationSource).not.toContain('from "../../api/client"');
    expect(mutationSource).not.toContain("fetchJson");
    expect(mutationSource).not.toContain("/api/agents/");
  });
});
