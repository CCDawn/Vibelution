import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatGroupCenterSurface, type ChatGroupCenterSurfaceProps } from "./ChatGroupCenterSurface";

function baseProps(patch: Partial<ChatGroupCenterSurfaceProps> = {}): ChatGroupCenterSurfaceProps {
  return {
    lang: "zh",
    projectBusActive: false,
    standardGroupRoomActive: true,
    groupRoomInitialLoading: false,
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
  it("renders a real loading state before the first group detail arrives", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          activeGroupRoom: undefined,
          availableGroupParticipantCount: 0,
          groupRoomInitialLoading: true,
        })}
      />,
    );

    expect(html).toContain("正在加载群聊详情");
    expect(html).not.toContain("0 位可用助手");
    expect(html).not.toContain("round_robin");
    expect(html).not.toContain("discussion");
    expect(html).not.toContain("群聊已创建，输入议题后开始第一轮讨论。");
  });

  it("keeps loaded group detail visible during a background refresh", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface {...baseProps({ groupRoomRefreshing: true })} />,
    );

    expect(html).toContain("研究组");
    expect(html).toContain("群聊已创建，输入议题后开始第一轮讨论。");
    expect(html).not.toContain("正在加载群聊详情");
  });

  it("renders standard group empty state and start-round controls", () => {
    const html = renderToStaticMarkup(<ChatGroupCenterSurface {...baseProps()} />);
    expect(html).toContain("研究组");
    expect(html).toContain("群聊已创建，输入议题后开始第一轮讨论。");
    expect(html).toContain("启动一轮");
    expect(html).toContain("value=\"下一议题\"");
  });

  it("does not claim a room exists after a settled empty response", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({ activeGroupRoom: undefined, activeGroupRoomId: "" })}
      />,
    );

    expect(html).toContain("暂无群聊");
    expect(html).toContain("当前没有可用群聊，请先创建或关联群聊。");
    expect(html).not.toContain("群聊加载中");
    expect(html).not.toContain("群聊已创建，输入议题后开始第一轮讨论。");
  });

  it("distinguishes a room load failure from both loading and an empty room", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          activeGroupRoom: undefined,
          activeGroupRoomId: "room-1",
          groupRoomRefreshError: "加载失败：网络不可用",
        })}
      />,
    );

    expect(html).toContain("群聊加载失败");
    expect(html).toContain("群聊详情读取失败，请点击刷新重试。");
    expect(html).not.toContain("群聊加载中");
    expect(html).not.toContain("群聊已创建，输入议题后开始第一轮讨论。");
  });

  it("renders the route-owned leading control in the standard group composer", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({ composerLeadingControl: <button type="button">更多操作</button> })}
      />,
    );
    expect(html).toContain("更多操作");
    expect(html.indexOf("更多操作")).toBeLessThan(html.indexOf("value=\"下一议题\""));
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

  it("shows the notice-stream skeleton during the initial project-bus load", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          projectBusActive: true,
          standardGroupRoomActive: false,
          projectBusTimeline: undefined,
          projectBusRefreshing: true,
        })}
      />,
    );

    expect(html).toContain("正在加载助手通知流");
    expect(html).toContain('data-testid="progressive-region-skeleton"');
    expect(html).not.toContain("暂无通知。");
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
    expect(html).toContain("本轮纪要");
    expect(html).toContain("group-stream-identity");
    expect(html).toContain("group-stream-topic-identity");
    expect(html).not.toContain("!bg-vui-surface-row");
  });

  it("shows one identity row for consecutive messages from the same speaker", () => {
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
                topic: "连续发言",
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
                    content: "第一条",
                    timestamp: "2026-07-20T00:00:30Z",
                  },
                  {
                    messageId: "msg-2",
                    participantId: "p1",
                    agentId: "a1",
                    speakerCode: "A01",
                    speakerTitle: "分析员",
                    status: "completed",
                    content: "第二条",
                    timestamp: "2026-07-20T00:00:40Z",
                  },
                ],
                summary: "",
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
    expect(html).toContain("第一条");
    expect(html).toContain("第二条");
    expect(html.split("group-stream-identity").length - 1).toBe(1);
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

  it("shows an explicit stopping state and removes the locked stop control", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          groupRoundActive: true,
          groupRoundStopping: true,
          groupStopDisabled: true,
        })}
      />,
    );

    expect(html).toContain("正在停止，等待收尾");
    expect(html).toContain("请点击刷新");
    expect(html).toContain("等待收尾");
    expect(html).not.toContain("停止当前群聊轮次");
  });

  describe("stale typing fallback", () => {
    const pendingParticipant = {
      participantId: "p1",
      kind: "session_agent",
      agentId: "a1",
      agentCode: "A01",
      sessionId: "s1",
      title: "分析员",
      enabled: true,
      status: "ready",
    };

    function runningRoomProps(updatedAt: string): Partial<ChatGroupCenterSurfaceProps> {
      return {
        activeGroupRoom: {
          roomId: "room-1",
          title: "研究组",
          mode: "round_robin",
          purpose: "discussion",
          status: "running",
          participants: [pendingParticipant],
          rounds: [
            {
              roundId: "r1",
              status: "running",
              mode: "round_robin",
              purpose: "discussion",
              topic: "陈旧兜底",
              startedAt: updatedAt,
              updatedAt,
              speakerOrder: ["p1"],
              messages: [],
              summary: "",
            },
          ],
        } as never,
        activeGroupParticipantById: new Map([["p1", pendingParticipant as never]]),
      };
    }

    it("shows the typing animation while the round snapshot is fresh", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps(runningRoomProps(new Date(Date.now() - 5_000).toISOString()))}
        />,
      );
      expect(html).toContain("正在输入");
      expect(html).toContain("groupTypingDots");
      expect(html).not.toContain("该发言已等待较久");
    });

    it("replaces the typing animation with a neutral status line once the round is stale", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps(runningRoomProps(new Date(Date.now() - 10 * 60_000).toISOString()))}
        />,
      );
      expect(html).not.toContain("groupTypingDots");
      expect(html).not.toContain("正在输入");
      expect(html).toContain("该发言已等待较久，仍在等待后端响应…");
      expect(html).toContain("等待中");
    });

    it("points at the broken live connection while stale and disconnected", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({
            ...runningRoomProps(new Date(Date.now() - 10 * 60_000).toISOString()),
            groupStreamConnected: false,
          })}
        />,
      );
      expect(html).toContain("实时连接已断开，正在重连");
      expect(html).not.toContain("groupTypingDots");
    });

    it("keeps the neutral backend-waiting copy when stale and connected", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({
            ...runningRoomProps(new Date(Date.now() - 10 * 60_000).toISOString()),
            groupStreamConnected: true,
          })}
        />,
      );
      expect(html).toContain("该发言已等待较久，仍在等待后端响应…");
      expect(html).not.toContain("实时连接已断开");
    });
  });
});
