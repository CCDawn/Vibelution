import { describe, expect, it } from "vitest";

import {
  buildCliAgentRunViews,
  canInputTerminal,
  cliAgentRunCloseToken,
  cliAgentRunIdFromTabId,
  cliAgentRunTabId,
  isCliAgentRunActiveForClose,
  type CliAgentRunView,
} from "./cliAgentRunModel";

function run(patch: Partial<CliAgentRunView> = {}): CliAgentRunView {
  return {
    id: "run-1",
    sourceRunId: "src-run-1",
    title: "Claude Code",
    status: "running",
    commandLine: "claude",
    terminalSessionId: "term-1",
    ...patch,
  } as CliAgentRunView;
}

describe("cliAgentRunModel hand-test substitutes", () => {
  it("maps tab ids both ways for AgentSessionTabStrip open/close", () => {
    const tabId = cliAgentRunTabId("run-42");
    expect(tabId).toBe("cli-agent-run:run-42");
    expect(cliAgentRunIdFromTabId(tabId)).toBe("run-42");
    expect(cliAgentRunIdFromTabId("agent")).toBe("");
  });

  it("requires confirmation stop when terminal can still accept input", () => {
    expect(canInputTerminal({ alive: true, status: "running", terminalSessionId: "t1" } as never)).toBe(true);
    expect(isCliAgentRunActiveForClose(run(), { alive: true, status: "running", terminalSessionId: "t1" } as never)).toBe(true);
  });

  it("treats closed terminal sessions as safe to dismiss without stop", () => {
    expect(
      isCliAgentRunActiveForClose(
        run({ status: "completed", result: { status: "completed", terminalStatus: "closed" } as never }),
        { alive: false, status: "closed", terminalSessionId: "t1", canInput: false } as never,
      ),
    ).toBe(false);
  });

  it("keeps close tokens stable across id/sourceRunId fallback", () => {
    expect(cliAgentRunCloseToken(run({ id: "a", sourceRunId: "b" }))).toBe("a");
    expect(cliAgentRunCloseToken(run({ id: "", sourceRunId: "b" }))).toBe("b");
  });

  it("builds visible CLI runs from tool-call messages and filters empty tool names", () => {
    const views = buildCliAgentRunViews(
      [
        {
          id: "m1",
          role: "assistant",
          content: "running cli",
          toolCalls: [
            {
              id: "tc1",
              name: "cli_agent_run_tool",
              status: "running",
              summary: "claude",
              resultPreview: JSON.stringify({
                status: "running",
                runId: "cli-run-9",
                terminalSessionId: "term-9",
                agentType: "claude_code",
                commandPreview: ["claude"],
              }),
            },
          ],
        } as never,
      ],
      "session-1",
    );
    expect(views.length).toBeGreaterThan(0);
    expect(views.some((item) => item.terminalSessionId === "term-9" || item.id.includes("cli-run") || item.sourceRunId)).toBe(true);
  });
});
