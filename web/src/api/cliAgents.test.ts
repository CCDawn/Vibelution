import { describe, expect, it } from "vitest";

import apiSource from "./cliAgents.ts?raw";
import panelSource from "../routes/chat/CliAgentRunTerminalPanel.tsx?raw";
import hookSource from "../routes/chat/useChatCliAgentTerminal.ts?raw";

describe("cliAgents catalog API", () => {
  it("owns CLI terminal session transports", () => {
    expect(apiSource).toContain("export function ensureCliAgentTerminalSession");
    expect(apiSource).toContain("export function sendCliAgentTerminalInput");
    expect(apiSource).toContain("export function resizeCliAgentTerminal");
    expect(apiSource).toContain("export function stopCliAgentTerminalSession");
    expect(apiSource).toContain('"/api/cli-agents/terminal-sessions/ensure"');
    expect(apiSource).toContain("/terminal-sessions/${encodeURIComponent(sessionId)}/stop");
  });

  it("keeps CLI terminal route modules free of cli-agents paths", () => {
    expect(panelSource).toContain("ensureCliAgentTerminalSession<");
    expect(panelSource).toContain("sendCliAgentTerminalInput<");
    expect(panelSource).toContain("resizeCliAgentTerminal<");
    expect(panelSource).not.toContain('"/api/cli-agents/terminal-sessions/ensure"');
    expect(panelSource).toContain("EventSource(`/api/cli-agents/terminal-sessions/");
    expect(hookSource).toContain("stopCliAgentTerminalSession<");
    expect(hookSource).not.toMatch(/[`'"]\/api\/cli-agents\//);
  });
});
