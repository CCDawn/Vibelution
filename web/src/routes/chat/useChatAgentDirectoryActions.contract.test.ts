import { describe, expect, it } from "vitest";

import routeSource from "../ChatCodingRoute.tsx?raw";
import actionsSource from "./useChatAgentDirectoryActions.ts?raw";

describe("useChatAgentDirectoryActions contract", () => {
  it("owns agent directory context-menu actions", () => {
    expect(actionsSource).toContain("export function useChatAgentDirectoryActions");
    expect(actionsSource).toContain("handleCreateAgent");
    expect(actionsSource).toContain("openAgentContextMenu");
    expect(actionsSource).toContain("handleRenameAgent");
    expect(actionsSource).toContain("handleArchiveAgent");
    expect(actionsSource).toContain("agentCenterConfigRoute");
    expect(actionsSource).toContain("handleOpenAgentConfig");
    expect(actionsSource).toContain("pane: \"config\"");
    expect(actionsSource).toContain("returnLabel: \"chat\"");
  });

  it("is wired from ChatCodingRoute", () => {
    expect(routeSource).toContain("useChatAgentDirectoryActions(");
    expect(routeSource).not.toContain("function handleCreateAgent()");
    expect(routeSource).not.toContain("const handleRenameAgent = useCallback");
    expect(routeSource).toContain("handleArchiveAgent");
  });
});
