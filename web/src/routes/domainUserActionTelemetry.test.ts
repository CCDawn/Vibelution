import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

const agentCreateSource = readFileSync(join(here, "agent-create/AgentCreateWizardDialog.tsx"), "utf8");
const agentConfigSource = readFileSync(join(here, "agents/useAgentConfigDraftMutations.ts"), "utf8");
const agentWorkbenchSource = readFileSync(join(here, "agents/useAgentWorkbenchMutations.ts"), "utf8");
const memoryItemSource = readFileSync(join(here, "memory/useMemoryItemMutations.ts"), "utf8");
const teamShellSource = readFileSync(join(here, "teams/useTeamShellMutations.ts"), "utf8");
const chatWorkbenchSource = readFileSync(join(here, "chat/ChatCodingRouteWorkbench.tsx"), "utf8");
const chatArchiveQueueSource = readFileSync(join(here, "chat/useChatAgentArchiveQueue.ts"), "utf8");

describe("domain user-action telemetry contract", () => {
  it("tracks agent lifecycle mutations", () => {
    expect(agentCreateSource).toContain('startUserAction("agent_create"');
    expect(agentConfigSource).toContain('startUserAction("agent_update"');
    expect(agentWorkbenchSource).toContain('startUserAction("agent_archive"');
    expect(agentWorkbenchSource).toContain('startUserAction("agent_purge"');
    expect(chatWorkbenchSource).toContain('startUserAction("agent_rename"');
    expect(chatArchiveQueueSource).toContain('startUserAction("agent_archive"');
  });

  it("tracks memory item and cleanup mutations", () => {
    expect(memoryItemSource).toContain('"memory_item_create"');
    expect(memoryItemSource).toContain('"memory_item_update"');
    expect(memoryItemSource).toContain('startUserAction("memory_item_delete"');
    expect(memoryItemSource).toContain('startUserAction("memory_item_restore"');
    expect(memoryItemSource).toContain('startUserAction("memory_cleanup_execute"');
  });

  it("tracks team shell mutations", () => {
    expect(teamShellSource).toContain('startUserAction("team_archive"');
    expect(teamShellSource).toContain('startUserAction("team_canvas_save"');
  });
});
