import { describe, expect, it } from "vitest";
import { launcherCommandAccepted } from "../src/protocol/launcherProtocol.js";

describe("Launcher protocol", () => {
  it("returns a machine-readable accepted response", () => {
    expect(launcherCommandAccepted("cmd-1", "focus", "focusing launcher")).toEqual({
      schemaVersion: 1,
      commandId: "cmd-1",
      command: "focus",
      status: "accepted",
      provider: "launcher_protocol",
      message: "focusing launcher",
      activeWorkBlocked: false
    });
  });
});
