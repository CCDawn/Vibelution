import { describe, expect, it } from "vitest";

import viewSource from "./ConversationView.tsx?raw";
import typeSource from "./conversationViewTypes.ts?raw";

describe("ConversationView Agent permission control contract", () => {
  it("renders the permission control in the Codex composer toolbar", () => {
    expect(typeSource).toContain("permissionControl?: ConversationPermissionControl");
    expect(viewSource).toContain("<AgentPermissionPresetControl");
    expect(viewSource.indexOf("<AgentPermissionPresetControl")).toBeGreaterThan(
      viewSource.indexOf("composerToolbarStart"),
    );
    expect(viewSource.indexOf("<AgentPermissionPresetControl")).toBeLessThan(
      viewSource.indexOf("composerToolbarEnd"),
    );
  });
});
