import { describe, expect, it } from "vitest";

import type { AgentInstance } from "../api/types";
import {
  agentDirectorySessionCount,
  agentDirectorySection,
  isSessionMoreRecent,
  isVisibleDirectoryAgent,
  visibleDirectoryAgents,
} from "./AgentConversationDirectory";
import { buildAgentDirectoryPartition } from "./agentConversationDirectoryModel";
import directorySource from "./AgentConversationDirectory.tsx?raw";
import styles from "./AgentConversationDirectory.styles";

function agent(overrides: Partial<AgentInstance> = {}): AgentInstance {
  return {
    agentId: "agent-1",
    agentCode: "A001",
    displayName: "会话 Agent",
    kind: "persistent",
    primaryMode: "chat",
    roleKey: "",
    llmBindings: { dialogue: { modelId: "model-primary" } },
    promptTemplateId: "prompt-chat-default",
    directSessionId: "",
    workspacePath: "workspace/agents/agent-1",
    toolPolicyId: "tool-agent-1",
    memoryPolicyId: "memory-agent-1",
    createdBy: "user",
    status: "active",
    metadata: { conversationIndexKind: "personal_agent" },
    createdAt: "2026-07-21T00:00:00Z",
    updatedAt: "2026-07-21T00:00:00Z",
    ...overrides,
  };
}

describe("AgentConversationDirectory", () => {
  it("renders Agent identity as the left navigation item and keeps session count as metadata", () => {
    expect(directorySource).toContain('aria-label={lang === "zh" ? "Agent 目录" : "Agent directory"}');
    expect(directorySource).toContain("agentDisplayInfo(agent, lang, { resolveModelLabel })");
    expect(directorySource).toContain("display.functionLabel");
    expect(directorySource).toContain("display.modelLabel");
    expect(directorySource).toContain("sessionCountByAgentId");
    expect(directorySource).toContain('aria-current={active ? "page" : undefined}');
    expect(directorySource).toContain('data-selected={active ? "true" : undefined}');
    expect(directorySource).toContain("onContextMenu={(event) => onContextMenu(event, agent, latestSession ?? null)}");
    expect(directorySource).toContain("onPress={() => onOpenAgent(agent, latestSession ?? null)}");
  });

  it("aggregates session activity into agent row indicators without gray idle dots", () => {
    expect(directorySource).toContain("resolveAgentActivityTone");
    expect(directorySource).toContain("resolveSessionActivityTone");
    expect(directorySource).toContain("sessionIdsNeedingApproval");
    expect(directorySource).toContain("runtimeRunningSessionIds");
    expect(directorySource).toContain("LoaderCircle");
    expect(directorySource).toContain("agentActivityRunning");
    expect(directorySource).toContain("agentActivityApproval");
    expect(directorySource).toContain("agentActivityError");
    expect(directorySource).toContain("agentActivityCompleted");
    expect(directorySource).not.toContain("agentStatusRunning");
    expect(styles.agentActivityRunning).toContain("state-success");
    expect(styles.agentActivityApproval).toContain("state-warning");
    expect(styles.agentActivityError).toContain("state-error");
    expect(styles.agentActivityCompleted).toContain("accent-cool");
  });

  it("orders mixed server-local and optimistic ISO timestamps by actual time", () => {
    const optimisticLocalTime = new Date(2026, 7, 10, 2, 52, 48).toISOString();

    expect(isSessionMoreRecent(
      { updatedAt: optimisticLocalTime, lastActive: "" },
      { updatedAt: "2026-08-10T00:59:41", lastActive: "" },
    )).toBe(true);
  });

  it("nests team chat and member agents under collapsible team blocks", () => {
    expect(directorySource).toContain("buildAgentDirectoryPartition");
    expect(directorySource).toContain("teamBlocks.map(renderTeamBlock)");
    expect(directorySource).toContain("TeamConversationIndexItem");
    expect(directorySource).toContain('displayTitle={lang === "zh" ? "团队群聊" : "Team chat"}');
    expect(directorySource).toContain("onOpenGroupRoom");
    expect(directorySource).toContain("teams = []");
  });

  it("counts an active hidden direct session without double-counting a visible summary", () => {
    const hiddenDirectAgent = agent({
      directSessionId: "session-hidden-direct",
      metadata: {
        conversationIndexKind: "hidden",
        directSessionVisibility: "active_session",
      },
    });

    expect(agentDirectorySessionCount(hiddenDirectAgent, 0, new Set())).toBe(1);
    expect(agentDirectorySessionCount(hiddenDirectAgent, 1, new Set(["session-hidden-direct"]))).toBe(1);
    expect(agentDirectorySessionCount(hiddenDirectAgent, 1, new Set(["session-visible"]))).toBe(2);
  });

  it("uses plain multi-line button layout so avatar/title/meta are not crushed into a nowrap label", () => {
    expect(directorySource).toContain('contentLayout="plain"');
    expect(styles.agentRow).toContain("!grid");
    expect(styles.agentRow).toContain("!h-auto");
    expect(styles.agentRow).toContain("!w-full");
    expect(styles.agentRow).toContain("grid-cols-[32px_minmax(0,1fr)_0.875rem]");
    expect(styles.agentRow).toContain("!items-stretch");
    expect(styles.agentStatusSlot).toContain("h-full");
    expect(styles.agentStatusSlot).toContain("w-3.5");
    expect(styles.agentStatusSlot).toContain("self-stretch");
    expect(styles.agentStatusSlot).toContain("place-items-center");
    expect(directorySource).toContain("data-agent-status-slot");
    expect(styles.agentTitle).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.agentTitle).toContain("[color:var(--fg-primary)]");
    expect(styles.agentMeta).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.agentMeta).not.toContain("text-[var(--vui-font-xs)]");
  });

  it("keeps the selected Agent row visible above the transparent base fill", () => {
    expect(styles.agentRow).toContain("!bg-transparent");
    expect(styles.agentRowActive).toContain("!bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]");
    expect(styles.agentRowActive).toContain("data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]");
    expect(styles.agentRowActive).not.toContain("shadow-[var(--vui-shadow-inset-accent)]");
  });

  it("keeps active no-session chat Agents visible and separates special Agents from team members", () => {
    const noSessionChatAgent = agent();
    const specialAgent = agent({
      agentId: "agent-observer",
      displayName: "观察员",
      primaryMode: "self_evolution",
      roleKey: "observer",
      directSessionId: "session-observer",
      conversationIndexKind: "hidden",
      conversationIndexVisibility: "hidden",
      metadata: { conversationIndexKind: "hidden" },
    });
    const teamAgent = agent({
      agentId: "agent-team",
      displayName: "团队成员",
      primaryMode: "research",
      roleKey: "source_finder",
      directSessionId: "session-team",
      conversationIndexKind: "team_agent",
      conversationIndexVisibility: "team_private",
      metadata: { conversationIndexKind: "team_agent" },
    });

    expect(isVisibleDirectoryAgent(noSessionChatAgent)).toBe(true);
    expect(agentDirectorySection(noSessionChatAgent)).toBe("conversation");
    expect(isVisibleDirectoryAgent(specialAgent)).toBe(true);
    expect(agentDirectorySection(specialAgent)).toBe("special");
    expect(isVisibleDirectoryAgent(teamAgent)).toBe(false);
  });

  it("no longer dumps all team members into the flat special section", () => {
    const personalAgent = agent();
    const teamMember = agent({
      agentId: "agent-team-member",
      displayName: "资料寻找",
      primaryMode: "research",
      roleKey: "source_finder",
      conversationIndexKind: "team_agent",
      conversationIndexVisibility: "team_private",
      metadata: { conversationIndexKind: "team_agent" },
    });
    const partition = buildAgentDirectoryPartition({
      agents: [personalAgent, teamMember],
      teams: [{
        teamId: "research-team",
        name: "挑战杯团队",
        description: "",
        purpose: "",
        status: "active",
        teamKind: "research",
        teamCategory: "research",
        teamSource: "manual",
        members: [{
          memberId: "m1",
          agentId: "agent-team-member",
          agentCode: "T1",
          agentName: "资料寻找",
          role: "source_finder",
          purpose: "",
          agentStatus: "active",
        }],
        memberCount: 1,
        linkedChatRoomId: "room-1",
        canvasPath: "",
        createdAt: "",
        updatedAt: "",
        canvas: { path: "", nodeCount: 0, edgeCount: 0 },
      }],
    });

    expect(partition.conversationAgents.map((item) => item.agentId)).toEqual(["agent-1"]);
    expect(partition.specialAgents).toEqual([]);
    expect(partition.teamBlocks[0]?.agents.map((item) => item.agentId)).toEqual(["agent-team-member"]);
    // Flat helper no longer auto-promotes experiment team agents into the flat list.
    expect(visibleDirectoryAgents([personalAgent, teamMember], []).map((item) => item.agentId)).toEqual(["agent-1"]);
  });

  it("renders separate conversation and special Agent section labels and team blocks", () => {
    expect(directorySource).toContain('lang === "zh" ? "会话 Agent" : "Conversation Agents"');
    expect(directorySource).toContain('lang === "zh" ? "特殊 Agent" : "Special Agents"');
    expect(directorySource).toContain("teamBlocks.map(renderTeamBlock)");
  });

  it("keeps each Agent directory section independently collapsible and accessible", () => {
    expect(directorySource).toContain("DEFAULT_COLLAPSED_DIRECTORY_SECTIONS");
    expect(directorySource).toContain("const [collapsedSections, setCollapsedSections]");
    expect(directorySource).toContain('import { ConversationIndexSection } from "./ConversationIndexSection"');
    expect(directorySource).toContain("<ConversationIndexSection");
    expect(directorySource).toContain("expanded={expanded}");
    expect(directorySource).toContain("toggleSection");
    expect(styles.agentSection).toContain("gap-1.5");
    expect(styles.agentDirectoryList).toContain("gap-1.5");
    expect(styles.agentDirectoryList).toContain("pl-1");
  });
});
