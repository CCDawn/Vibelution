import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { ConversationSummary, SessionReferenceAttachment, SessionSummary, Team } from "../api/types";
import { ConversationIndexTree, type ConversationIndexGroup } from "./ConversationIndexTree";

function directConversation(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversationId: "session-1",
    directSessionId: "session-1",
    type: "direct_agent",
    title: "用户改名",
    agentId: "agent-1",
    agentCode: "A030",
    agentDisplayName: "顾明澈",
    status: "idle",
    summary: "会话摘要",
    updatedAt: "2026-06-09T00:00:00.000Z",
    workspacePath: "C:/workspace",
    ...overrides,
  };
}

function groupConversation(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversationId: "room-1",
    type: "group_room",
    title: "项目群聊",
    status: "idle",
    summary: "群聊摘要",
    updatedAt: "2026-06-09T00:00:00.000Z",
    workspacePath: "C:/workspace",
    participantCount: 3,
    ...overrides,
  };
}

function team(overrides: Partial<Team> = {}): Team {
  return {
    teamId: "team-1",
    name: "研究团队",
    purpose: "团队目的",
    status: "active",
    members: [],
    memberCount: 2,
    linkedChatRoomId: "team-room-1",
    linkedChatRoom: {
      roomId: "team-room-1",
      title: "团队群聊",
      status: "idle",
    },
    teamKind: "research",
    teamCategory: "科研",
    teamSource: "",
    teamTemplateId: "",
    createdAt: "",
    updatedAt: "",
    ...overrides,
  };
}

function renderTree(overrides: Partial<{
  filteredConversationsCount: number;
  filteredStandaloneGroupConversations: ConversationSummary[];
  filteredTeams: Team[];
  groupedConversations: ConversationIndexGroup[];
}> = {}) {
  const direct = directConversation();
  const group = groupConversation();
  const groupedConversations = [{
    groupKey: "chat",
    label: "用户会话",
    items: [direct, group],
  }];
  return renderToStaticMarkup(
    <MemoryRouter>
    <ConversationIndexTree
      activeGroupRoomId="room-1"
      activeSessionId="session-1"
      addToReviewSucceededLabel="已加入评审"
      agentsById={new Map()}
      avatarImageUrlFrom={() => ""}
      avatarInitials={() => "A0"}
      buildSessionReferencePayload={(session: SessionSummary, displayName: string, summary: string): SessionReferenceAttachment => ({
        referenceId: `session:${session.id}`,
        kind: "session",
        sessionId: session.id,
        title: session.title,
        agentDisplayName: displayName,
        summary,
        createdAt: "2026-06-09T00:00:00.000Z",
      })}
      collapsedConversationGroups={{}}
      conversationGroupLabel={(groupKey) => (groupKey === "teams" ? "团队" : "未归属群聊")}
      deleteBusyLabel="会话忙碌"
      editingSessionId={null}
      editingSessionTitle=""
      filteredConversationsCount={2}
      filteredStandaloneGroupConversations={[groupConversation({ conversationId: "standalone-room", roomId: "standalone-room", title: "未归属群聊" })]}
      filteredTeams={[team()]}
      formatTime={() => "06/09"}
      groupPanelActive={false}
      groupedConversations={groupedConversations}
      isBusyPhase={() => false}
      lang="zh"
      renamePending={false}
      renameSessionId=""
      searchHasTerm={false}
      sessionComposerErrors={{}}
      sessionsById={new Map()}
      statusLabel={(status) => status}
      t={(key) => key}
      onCancelRename={() => undefined}
      onContextMenu={() => undefined}
      onDragReference={() => undefined}
      onOpenDirectSession={() => undefined}
      onOpenGroupRoom={() => undefined}
      onRenameTitleChange={() => undefined}
      onSubmitRename={() => undefined}
      onToggleConversationGroup={() => undefined}
      {...overrides}
    />
    </MemoryRouter>,
  );
}

describe("ConversationIndexTree", () => {
  it("renders direct, grouped room, team, and standalone group sections together", () => {
    const markup = renderTree();

    expect(markup).toContain("用户会话");
    expect(markup).toContain("用户改名");
    expect(markup).toContain("项目群聊");
    expect(markup).toContain("研究团队");
    expect(markup).toContain("未归属群聊");
    expect(markup).toContain("团队群聊");
  });

  it("collapses conversation groups without removing team and standalone sections", () => {
    const markup = renderTree({
      groupedConversations: [{ groupKey: "chat", label: "用户会话", items: [directConversation()] }],
      collapsedConversationGroups: { chat: true },
    });

    expect(markup).toContain("用户会话");
    expect(markup).not.toContain("用户改名");
    expect(markup).toContain("研究团队");
    expect(markup).toContain("未归属群聊");
  });
});
