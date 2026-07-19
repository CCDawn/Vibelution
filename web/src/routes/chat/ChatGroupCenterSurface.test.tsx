import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatGroupCenterSurface, type ChatGroupCenterSurfaceProps } from "./ChatGroupCenterSurface";

function baseProps(patch: Partial<ChatGroupCenterSurfaceProps> = {}): ChatGroupCenterSurfaceProps {
  return {
    lang: "zh",
    projectBusActive: false,
    standardGroupRoomActive: true,
    activeGroupRoom: {
      roomId: "room-1",
      title: "研究组",
      mode: "round_robin",
      purpose: "discussion",
      status: "ready",
      participants: [],
      rounds: [],
    } as never,
    activeGroupRoomId: "room-1",
    availableGroupParticipantCount: 2,
    activeGroupParticipantById: new Map(),
    projectBusTimeline: { events: [], activeAgentCount: 0 } as never,
    projectBusEvents: [],
    projectBusDraft: "",
    projectBusInterruptTargets: false,
    groupTopicDraft: "下一议题",
    groupRoomActionError: "",
    groupRoundActive: false,
    groupRoundStopping: false,
    groupStopDisabled: true,
    expandedGroupMessageIds: [],
    chatMentionTargets: [],
    userDisplayName: "我",
    projectBusRefreshing: false,
    projectBusRefreshError: "",
    projectBusSendPending: false,
    projectBusRevokePending: false,
    groupRoomRefreshing: false,
    groupRoomRefreshError: "",
    startGroupRoundPending: false,
    stopGroupRoundPending: false,
    formatTime: (value) => value,
    statusLabel: (value) => String(value || "idle"),
    groupParticipantIdentity: () => ({
      name: "Agent",
      identityLabel: "Agent",
      fullIdentityLabel: "Agent",
      avatarImageUrl: undefined,
    }),
    renderAgentAvatar: (className, _url, initials) => <span className={className}>{initials}</span>,
    avatarInitials: () => "AI",
    onProjectBusDraftChange: () => undefined,
    onProjectBusInterruptTargetsChange: () => undefined,
    onGroupTopicDraftChange: () => undefined,
    onRefreshProjectBus: () => undefined,
    onRefreshGroupRoom: () => undefined,
    onSendProjectBusMessage: () => undefined,
    onRevokeProjectBusMessage: () => undefined,
    onStartGroupRound: () => undefined,
    onStopGroupRound: () => undefined,
    onOpenMentionTarget: () => undefined,
    onToggleExpandedGroupMessage: () => undefined,
    ...patch,
  };
}

describe("ChatGroupCenterSurface hand-test substitutes", () => {
  it("renders standard group empty state and start-round controls", () => {
    const html = renderToStaticMarkup(<ChatGroupCenterSurface {...baseProps()} />);
    expect(html).toContain("研究组");
    expect(html).toContain("群聊已创建，输入议题后开始第一轮讨论。");
    expect(html).toContain("启动一轮");
    expect(html).toContain("value=\"下一议题\"");
  });

  it("renders project-bus empty notice stream and broadcast composer", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          projectBusActive: true,
          standardGroupRoomActive: false,
          projectBusTimeline: { events: [], activeAgentCount: 3 } as never,
        })}
      />,
    );
    expect(html).toContain("助手通知流");
    expect(html).toContain("暂无通知。");
    expect(html).toContain("发送广播");
    expect(html).toContain("打断目标助手");
  });

  it("renders a completed group round topic and message bubble", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          activeGroupRoom: {
            roomId: "room-1",
            title: "研究组",
            mode: "round_robin",
            purpose: "discussion",
            status: "ready",
            participants: [
              {
                participantId: "p1",
                kind: "session_agent",
                agentId: "a1",
                agentCode: "A01",
                sessionId: "s1",
                title: "分析员",
                enabled: true,
                status: "ready",
              },
            ],
            rounds: [
              {
                roundId: "r1",
                status: "completed",
                mode: "round_robin",
                purpose: "discussion",
                topic: "请讨论拆分风险",
                startedAt: "2026-07-20T00:00:00Z",
                updatedAt: "2026-07-20T00:01:00Z",
                speakerOrder: ["p1"],
                messages: [
                  {
                    messageId: "msg-1",
                    participantId: "p1",
                    agentId: "a1",
                    speakerCode: "A01",
                    speakerTitle: "分析员",
                    status: "completed",
                    content: "风险可控",
                    timestamp: "2026-07-20T00:00:30Z",
                  },
                ],
                summary: "结论：可控",
              },
            ],
          } as never,
          activeGroupParticipantById: new Map([
            [
              "p1",
              {
                participantId: "p1",
                kind: "session_agent",
                agentId: "a1",
                agentCode: "A01",
                sessionId: "s1",
                title: "分析员",
                enabled: true,
                status: "ready",
              } as never,
            ],
          ]),
        })}
      />,
    );
    expect(html).toContain("第 1 轮");
    expect(html).toContain("请讨论拆分风险");
    expect(html).toContain("风险可控");
    expect(html).toContain("结论：可控");
  });

  it("shows stop control while a group round is active", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          groupRoundActive: true,
          groupRoundStopping: false,
          groupStopDisabled: false,
        })}
      />,
    );
    expect(html).toContain("讨论中");
    expect(html).toContain("停止");
  });
});
