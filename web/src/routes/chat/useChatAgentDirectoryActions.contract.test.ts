import { describe, expect, it } from "vitest";

import routeSource from "./ChatCodingRouteWorkbench.tsx?raw";
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

  it("renames agents through an in-app draft dialog instead of a native browser prompt", () => {
    expect(actionsSource).not.toMatch(/window\.prompt\s*\(/);
    expect(actionsSource).not.toContain("promptRename");
    expect(actionsSource).toContain("setAgentRenameDraft");
    expect(actionsSource).toContain("submitAgentRename");
    expect(actionsSource).toContain("queueMicrotask");
    expect(actionsSource).toContain("renameAgent({ agentId: agentRenameDraft.agentId, displayName: title })");
  });

  it("is wired from ChatCodingRoute", () => {
    expect(routeSource).toContain("useChatAgentDirectoryActions(");
    expect(routeSource).not.toContain("function handleCreateAgent()");
    expect(routeSource).not.toContain("const handleRenameAgent = useCallback");
    expect(routeSource).toContain("handleArchiveAgent");
    expect(routeSource).toContain("AgentRenameDialog");
    expect(routeSource).toContain("agentRenameDraft");
    expect(routeSource).toContain("submitAgentRename");
    expect(actionsSource).toContain("const [agentCreateWizardOpen, setAgentCreateWizardOpen]");
    expect(actionsSource).toContain("agentCreateTriggerRef");
  });

  it("blocks only a duplicate archive for the same Agent", () => {
    expect(actionsSource).toContain("isAgentArchivePending: (agentId: string) => boolean");
    expect(actionsSource).toContain("isAgentArchivePending(agentId)");
    expect(actionsSource).not.toContain("archiveAgentPending: boolean");
    expect(routeSource).toContain("isAgentArchivePending,");
    expect(routeSource).toContain("enqueueAgentArchive(variables.agentId)");
  });
});
