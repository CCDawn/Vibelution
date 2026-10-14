import { describe, expect, it } from "vitest";

import viewSource from "./ConversationView.tsx?raw";
import composerSource from "./useConversationComposer.tsx?raw";
import typeSource from "./conversationViewTypes.ts?raw";

describe("ConversationView Agent permission control contract", () => {
  it("renders the permission control in the Codex composer toolbar", () => {
    expect(typeSource).toContain("permissionControl?: ConversationPermissionControl");
    expect(viewSource).toContain("permissionControl,");
    expect(composerSource).toContain("<AgentPermissionPresetControl");
    expect(composerSource.indexOf("<AgentPermissionPresetControl")).toBeGreaterThan(
      composerSource.indexOf("composerToolbarStart"),
    );
    expect(composerSource.indexOf("<AgentPermissionPresetControl")).toBeLessThan(
      composerSource.indexOf("composerToolbarEnd"),
    );
  });
});
