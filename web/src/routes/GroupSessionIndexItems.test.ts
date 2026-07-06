import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import type { ConversationSummary, Team } from "../api/types";
import {
  GroupConversationIndexItem,
  TeamConversationIndexItem,
  teamCategoryLabel,
  teamMemberPreview,
  teamMemberStatusTitle,
  teamStatusLabel,
} from "./GroupSessionIndexItems";

function team(overrides: Partial<Team>): Team {
  return {
    teamId: "team-1",
    name: "科研团队",
    description: "",
    purpose: "",
    status: "active",
    teamKind: "",
    teamCategory: "",
    teamSource: "manual",
    members: [],
    memberCount: 0,
    canvasPath: "",
    createdAt: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    canvas: {
      path: "",
      nodeCount: 0,
      edgeCount: 0,
    },
    ...overrides,
  };
}

describe("GroupSessionIndexItems helpers", () => {
  it("renders group conversation rows through native VUI row buttons", () => {
    const conversation: ConversationSummary = {
      conversationId: "room-1",
      roomId: "room-1",
      title: "团队群聊",
      type: "group_room",
      status: "active",
      updatedAt: "2026-06-09T00:00:00.000Z",
      participantCount: 3,
      summary: "",
    };
    const markup = renderToStaticMarkup(createElement(GroupConversationIndexItem, {
      active: false,
      conversation,
      fallbackSummary: "群聊会话",
      formatTime: () => "06/09 00:00",
      kindLabel: "群聊",
      lang: "zh",
      onOpen: () => undefined,
      roomId: "room-1",
      statusLabel: () => "启用中",
    }));

    expect(markup).toContain('data-vui="native-button"');
    expect(markup).not.toContain('data-vui="button"');
  });

  it("renders Team rows through native VUI row buttons", () => {
    const markup = renderToStaticMarkup(createElement(TeamConversationIndexItem, {
      active: false,
      lang: "zh",
      onOpen: () => undefined,
      roomId: "room-1",
      statusLabel: () => "启用中",
      team: team({
        linkedChatRoomId: "room-1",
        memberCount: 2,
        name: "科研团队",
      }),
      teamRoute: "/teams?team=team-1",
    }));

    expect(markup).toContain('data-vui="native-button"');
    expect(markup).not.toContain('data-vui="button"');
  });

  it("describes disabled Team rows with the missing room reason on the row button", () => {
    const markup = renderToStaticMarkup(createElement(TeamConversationIndexItem, {
      active: false,
      lang: "zh",
      onOpen: () => undefined,
      roomId: "",
      statusLabel: () => "启用中",
      team: team({
        linkedChatRoomId: "",
        memberCount: 2,
        name: "科研团队",
      }),
      teamRoute: "/teams?team=team-1",
    }));

    expect(markup).toContain('disabled=""');
    expect(markup).toContain('aria-describedby="team-row-disabled-reason-team-1"');
    expect(markup).toContain('<span id="team-row-disabled-reason-team-1" class="sr-only">团队群聊待同步</span>');
  });

  it("localizes known Team status labels and delegates unknown status to the route fallback", () => {
    const fallback = (status: string) => `status:${status}`;

    expect(teamStatusLabel("active", "zh", fallback)).toBe("启用中");
    expect(teamStatusLabel("archived", "en", fallback)).toBe("Archived");
    expect(teamStatusLabel("paused", "zh", fallback)).toBe("status:paused");
  });

  it("keeps Team member previews compact instead of listing Agent names or codes", () => {
    expect(teamMemberPreview(team({
      memberCount: 4,
      members: [
        { memberId: "1", agentId: "a1", agentCode: "A001", agentName: "广撒网", role: "search", purpose: "", agentStatus: "active" },
        { memberId: "2", agentId: "a2", agentCode: "A002", agentName: "", role: "review", purpose: "", agentStatus: "active" },
        { memberId: "3", agentId: "a3", agentCode: "A003", agentName: "证据审查", role: "evidence", purpose: "", agentStatus: "active" },
        { memberId: "4", agentId: "a4", agentCode: "A004", agentName: "未展示", role: "extra", purpose: "", agentStatus: "active" },
      ],
    }), "zh")).toBe("4人");
    expect(teamMemberPreview(team({ memberCount: 2 }), "en")).toBe("2");
    expect(teamMemberPreview(team({ memberCount: 0 }), "zh")).toBe("0人");
    expect(teamMemberStatusTitle(team({ memberCount: 0 }), "zh")).toBe("成员：0人 / 未配置成员");
  });

  it("uses Team category before kind and falls back to a localized custom label", () => {
    expect(teamCategoryLabel(team({ teamCategory: "科研", teamKind: "research" }), "zh")).toBe("科研");
    expect(teamCategoryLabel(team({ teamCategory: "", teamKind: "research" }), "en")).toBe("research");
    expect(teamCategoryLabel(team({ teamCategory: "", teamKind: "" }), "zh")).toBe("自定义团队");
  });
});
