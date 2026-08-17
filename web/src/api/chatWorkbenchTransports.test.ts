import { describe, expect, it } from "vitest";

import chatApiSource from "./chat.ts?raw";
import filesApiSource from "./files.ts?raw";
import agentsApiSource from "./agents.ts?raw";
import workbenchSource from "../routes/chat/ChatCodingRouteWorkbench.tsx?raw";

describe("chat workbench remaining transports", () => {
  it("owns child-session and file-content reads in domain APIs", () => {
    expect(chatApiSource).toContain("export function listSessionChildSessions");
    expect(chatApiSource).toContain("/child-sessions");
    expect(filesApiSource).toContain("export function fetchFileContent");
    expect(filesApiSource).toContain("/api/files/content?path=");
    expect(agentsApiSource).toContain("export function updateAgent");
    expect(agentsApiSource).toContain("export function archiveAgent");
  });

  it("keeps ChatCodingRouteWorkbench free of inline JSON paths", () => {
    expect(workbenchSource).toContain("listSessionChildSessions(");
    expect(workbenchSource).toContain("updateAgent(");
    expect(workbenchSource).toContain("archiveAgent(");
    expect(workbenchSource).toContain("fetchFileContent(");
    expect(workbenchSource).not.toContain('from "../../api/client"');
    expect(workbenchSource).not.toContain("/api/sessions/");
    expect(workbenchSource).not.toContain("/api/agents/");
    expect(workbenchSource).not.toContain("/api/files/");
  });
});
