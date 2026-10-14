import { describe, expect, it } from "vitest";

import chatApiSource from "./chat.ts?raw";
import filesApiSource from "./files.ts?raw";
import agentsApiSource from "./agents.ts?raw";
import workbenchSource from "../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import sessionDetailQueriesSource from "../routes/chat/useChatSessionDetailQueries.ts?raw";
import agentArchiveFlowSource from "../routes/chat/useChatAgentArchiveFlow.ts?raw";
import sessionMutationsSource from "../routes/chat/useChatSessionMutations.ts?raw";
import railPreviewSource from "../routes/chat/useChatRailPreview.ts?raw";

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
    expect(workbenchSource).toContain("useChatSessionDetailQueries(");
    expect(sessionDetailQueriesSource).toContain("listSessionChildSessions(");
    expect(workbenchSource).toContain("useChatSessionMutations(");
    expect(sessionMutationsSource).toContain("updateAgent(");
    expect(workbenchSource).toContain("useChatAgentArchiveFlow(");
    expect(agentArchiveFlowSource).toContain("archiveAgent(");
    expect(workbenchSource).toContain("useChatRailPreview(");
    expect(railPreviewSource).toContain("fetchFileContent(");
    for (const source of [workbenchSource, sessionDetailQueriesSource, agentArchiveFlowSource, sessionMutationsSource, railPreviewSource]) {
      expect(source).not.toContain('from "../../api/client"');
      expect(source).not.toContain("/api/sessions/");
      expect(source).not.toContain("/api/agents/");
      expect(source).not.toContain("/api/files/");
    }
  });
});
