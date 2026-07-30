import { describe, expect, it } from "vitest";

import type { AgentInstance } from "../api/types";
import {
  agentDirectorySessionCount,
  agentDirectorySection,
  isVisibleDirectoryAgent,
  visibleDirectoryAgents,
} from "./AgentConversationDirectory";
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
    expect(directorySource).toContain("onContextMenu={(event) => onContextMenu(event, agent, latestSession ?? null)}");
    expect(directorySource).toContain("onPress={() => onOpenAgent(agent, latestSession ?? null)}");
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
    expect(styles.agentRow).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(styles.agentTitle).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.agentTitle).toContain("[color:var(--fg-primary)]");
    expect(styles.agentMeta).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.agentMeta).not.toContain("text-[var(--vui-font-xs)]");
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

  it("adds only experiment-backed team Agents to the flat Agent directory", () => {
    const personalAgent = agent();
    const experimentAgent = agent({
      agentId: "agent-team-experiment",
      displayName: "资料寻找",
      primaryMode: "research",
      roleKey: "source_finder",
      conversationIndexKind: "team_agent",
      conversationIndexVisibility: "team_private",
      metadata: { conversationIndexKind: "team_agent" },
    });
    const inactiveTeamAgent = agent({
      agentId: "agent-team-inactive",
      displayName: "资料入库",
      primaryMode: "research",
      roleKey: "source_ingestor",
      conversationIndexKind: "team_agent",
      conversationIndexVisibility: "team_private",
      metadata: { conversationIndexKind: "team_agent" },
    });
    const sessions = [{
      id: "session-experiment",
      title: "Alpha 实验｜资料寻找",
      agentId: experimentAgent.agentId,
      status: "ready",
      lastActive: "2026-07-27T13:47:44Z",
      updatedAt: "2026-07-27T13:47:44Z",
      currentPhase: "ready",
      experimentBinding: {
        teamId: "research-team",
        researchProjectId: "research-alpha",
        experimentName: "Alpha 实验",
        agentId: experimentAgent.agentId,
        roleKey: "source_finder",
        roleLabel: "资料寻找",
        attempt: 1,
        retryOfSessionId: "",
        createdFromTaskId: "",
        createdAt: "2026-07-27T13:47:44Z",
      },
    }];

    expect(
      visibleDirectoryAgents([personalAgent, experimentAgent, inactiveTeamAgent], sessions)
        .map((item) => item.agentId),
    ).toEqual(["agent-1", "agent-team-experiment"]);
  });

  it("renders separate conversation and special Agent section labels", () => {
    expect(directorySource).toContain('lang === "zh" ? "会话 Agent" : "Conversation Agents"');
    expect(directorySource).toContain('lang === "zh" ? "特殊 Agent" : "Special Agents"');
  });

  it("keeps each Agent directory section independently collapsible and accessible", () => {
    expect(directorySource).toContain("DEFAULT_COLLAPSED_DIRECTORY_SECTIONS");
    expect(directorySource).toContain("const [collapsedSections, setCollapsedSections]");
    expect(directorySource).toContain('import { ConversationIndexSection } from "./ConversationIndexSection"');
    expect(directorySource).toContain("<ConversationIndexSection");
    expect(directorySource).toContain("expanded={expanded}");
    expect(directorySource).toContain("onToggle={() => setCollapsedSections");
    expect(styles.agentSection).toContain("gap-1.5");
    expect(styles.agentDirectoryList).toContain("gap-1.5");
    expect(styles.agentDirectoryList).toContain("pl-1");
  });
});
