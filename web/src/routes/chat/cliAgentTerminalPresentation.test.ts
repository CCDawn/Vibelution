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
    expect(canInputTerminal({ status: "stopping", canInput: true, alive: true } as any)).toBe(false);
  });

  it("labels a live process that is being stopped before its interaction history", () => {
    const session = { status: "stopping", alive: true, userClosed: true, canInput: false, interactionState: "closed" } as any;
    expect(terminalStatusText(session, false, "zh")).toBe("停止中");
    expect(terminalStatusText(session, false, "en")).toBe("Stopping");
    expect(terminalStatusText({ ...session, userClosed: false, interactionState: "history" }, false, "zh")).toBe("停止中");
  });

  it("maps resumable terminal errors", () => {
    const err = new Error(JSON.stringify({ detail: { canResume: true, interactionState: "resumable" } }));
    expect(terminalErrorMessage(err, "en")).toContain("Resume the session");
  });

  it("keeps stopping input errors distinct from a finished close", () => {
    const err = new Error(JSON.stringify({ detail: { status: "stopping", interactionState: "closed", canInput: false } }));
    expect(terminalErrorMessage(err, "zh")).toBe("终端正在停止，不能继续输入。");
    expect(terminalErrorMessage(err, "en")).toContain("stopping");
  });
});
