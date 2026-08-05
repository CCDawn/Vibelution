import { describe, expect, it } from "vitest";

import {
  canInputTerminal,
  terminalErrorMessage,
  terminalStatusText,
} from "./cliAgentTerminalPresentation";

describe("cliAgentTerminalPresentation", () => {
  it("labels connecting and live sessions", () => {
    expect(terminalStatusText(null, true, "en")).toBe("Connecting");
    expect(terminalStatusText({ alive: true } as any, false, "zh")).toBe("运行中");
  });

  it("gates input by canInput flag", () => {
    expect(canInputTerminal(null)).toBe(false);
    expect(canInputTerminal({ canInput: true } as any)).toBe(true);
    expect(canInputTerminal({ canInput: false, alive: true } as any)).toBe(false);
  });

  it("maps resumable terminal errors", () => {
    const err = new Error(JSON.stringify({ detail: { canResume: true, interactionState: "resumable" } }));
    expect(terminalErrorMessage(err, "en")).toContain("Resume the session");
  });
});
