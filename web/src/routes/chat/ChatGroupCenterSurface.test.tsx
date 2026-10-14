/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ChatGroupCenterSurface, type ChatGroupCenterSurfaceProps } from "./ChatGroupCenterSurface";
const artifactRenderCalls = vi.hoisted(() => [] as Array<{ teamId: string; taskIds: string[] }>);
vi.mock("./ChatGroupArtifactDialog", () => ({
  ChatGroupArtifactDialog: (props: { teamId: string; taskIds: string[] }) => {
    artifactRenderCalls.push({ teamId: props.teamId, taskIds: props.taskIds });
    return null;
  },
}));

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
  it("drops artifact selection before rendering another room or team's dialog", async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    artifactRenderCalls.length = 0;
    const host = document.createElement("div"); document.body.append(host);
    const root = createRoot(host);
    const props = baseProps({ artifactTeamId: "team-a" });
    const timeline = { items: [{ kind: "artifact", row: {
      key: "delivery", seq: 1, createdAt: "", fileCount: 1,
      changedPaths: ["file.md"], changedPathsTruncated: false, taskIds: ["shared-task"],
    } }], hasMore: false, loading: false, loadingMore: false, legacyFromDetail: false, loadMore: () => {} } as never;
    try {
      await act(async () => root.render(<ChatGroupCenterSurface {...props} groupTimeline={timeline} />));
      const trigger = [...host.querySelectorAll("button")].find((button) => button.textContent === "查看改动")!;
      await act(async () => trigger.click());
      expect(artifactRenderCalls.at(-1)?.teamId).toBe("team-a");
      artifactRenderCalls.length = 0;
      await act(async () => root.render(<ChatGroupCenterSurface {...props} groupTimeline={timeline}
        artifactTeamId="team-b" activeGroupRoomId="room-b" />));
      expect(artifactRenderCalls).toEqual([]);
    } finally { await act(async () => root.unmount()); host.remove(); }
  });
  it("keeps following a large stream burst until the reader scrolls away", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.createElement("div"); document.body.append(host);
    const root = createRoot(host);
    const props = baseProps({ groupRoundActive: true });
    const streams = (content: string) => ({ round: { speaker: { content } } }) as never;
    try {
      await act(async () => root.render(<ChatGroupCenterSurface {...props} />));
      const timeline = host.querySelector<HTMLElement>('[role="log"]')!;
      let height = 1000;
      Object.defineProperty(timeline, "scrollHeight", { get: () => height });
      Object.defineProperty(timeline, "clientHeight", { get: () => 500 });
      timeline.scrollTop = 500;
      await act(async () => timeline.dispatchEvent(new Event("scroll", { bubbles: true })));
      height = 1500;
      await act(async () => root.render(<ChatGroupCenterSurface {...props} groupSpeakerStreams={streams("burst")} />));
      expect(timeline.scrollTop).toBe(1500);
      timeline.scrollTop = 200;
      await act(async () => timeline.dispatchEvent(new Event("scroll", { bubbles: true })));
      height = 2000;
      await act(async () => root.render(<ChatGroupCenterSurface {...props} groupSpeakerStreams={streams("next burst")} />));
      expect(timeline.scrollTop).toBe(200);
    } finally { await act(async () => root.unmount()); host.remove(); }
  });

  it("keeps delivery counters behind an explicit result disclosure", async () => {
    const props = baseProps();
    const summary = "本轮群聊完成：2/2 位参与者成功发言，0 位未成功（失败 0、受阻 0、停止 0、0 位部分完成）。";
    const room = { ...props.activeGroupRoom!, rounds: [{ roundId: "delivery", status: "completed", topic: "验收反馈", summary, messages: [] }] } as never;
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.createElement("div"); document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<ChatGroupCenterSurface {...props} activeGroupRoom={room} />));
      expect(host.textContent).not.toContain(summary);
      const result = [...host.querySelectorAll("button")].find((button) => button.textContent === "轮次结果")!;
      expect(result.getAttribute("aria-expanded")).toBe("false");
      await act(async () => result.click());
      expect(host.textContent).toContain(summary);
      expect(result.getAttribute("aria-expanded")).toBe("true");
      await act(async () => result.click());
      expect(host.textContent).not.toContain(summary);
    } finally { await act(async () => root.unmount()); host.remove(); }
  });

  it("uses Ctrl+Enter for a new round and preserves Enter, IME and active-round guards", async () => {
    const start = vi.fn();
    const props = baseProps({ onStartGroupRound: start });
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.createElement("div"); document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<ChatGroupCenterSurface {...props} />));
      const input = host.querySelector("textarea")!;
      const press = (options: KeyboardEventInit) => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, ...options }));
      await act(async () => { press({}); press({ ctrlKey: true, isComposing: true }); });
      expect(start).not.toHaveBeenCalled();
      await act(async () => { press({ ctrlKey: true }); });
      expect(start).toHaveBeenCalledTimes(1);
      await act(async () => root.render(<ChatGroupCenterSurface {...props} groupRoundActive />));
      await act(async () => { press({ ctrlKey: true }); });
      expect(start).toHaveBeenCalledTimes(1);
    } finally { await act(async () => root.unmount()); host.remove(); }
  });

  it("only stops an active round after confirmation and keeps cancellation reversible", async () => {
    const stop = vi.fn();
    const props = baseProps({ groupRoundActive: true, groupStopDisabled: false, onStopGroupRound: stop });
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.createElement("div"); document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<ChatGroupCenterSurface {...props} />));
      const trigger = [...host.querySelectorAll("button")].find((button) => button.textContent === "停止本轮")!;
      await act(async () => trigger.click());
      expect(stop).not.toHaveBeenCalled();
      const cancel = [...document.querySelectorAll('[role="dialog"] button')].find((button) => button.textContent === "继续讨论") as HTMLButtonElement;
      await act(async () => cancel.click());
      expect(stop).not.toHaveBeenCalled();
      await act(async () => trigger.click());
      const confirm = [...document.querySelectorAll('[role="dialog"] button')].find((button) => button.textContent === "停止本轮") as HTMLButtonElement;
      await act(async () => confirm.click());
      expect(stop).toHaveBeenCalledTimes(1);
    } finally { await act(async () => root.unmount()); host.remove(); }
  });

  it("keeps historical speech visible, puts conclusions after it, and locates failures without starting a round", async () => {
    const props = baseProps();
    const startRound = vi.fn();
    const room = { ...props.activeGroupRoom!, rounds: [
      { roundId: "past", status: "completed", topic: "旧议题", summary: "旧轮纪要", messages: [{ messageId: "bad", participantId: "p1", content: "无法解析的发言", status: "completed", messagePayload: { kind: "challenge_meeting_message", audit: { parseStatus: "invalid" } } }] },
      { roundId: "latest", status: "completed", topic: "新议题", summary: "可用纪要", messages: [] },
    ] } as never;
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1; });
    const scroll = vi.fn();
    vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(scroll);
    const host = document.createElement("div"); document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<ChatGroupCenterSurface {...props} activeGroupRoom={room} onStartGroupRound={startRound} />));
      const failedMessage = host.querySelector('[data-parse-invalid="true"]')!;
      expect(failedMessage.closest('[hidden]')).toBeNull();
      const latestRound = [...host.querySelectorAll("section")].find((section) => section.textContent?.includes("可用纪要"))!;
      expect(latestRound.innerHTML.indexOf("可用纪要")).toBeGreaterThan(latestRound.innerHTML.indexOf("新议题"));
      const jump = [...host.querySelectorAll("button")].find((button) => button.textContent === "定位解析失败发言")!;
      await act(async () => jump.click());
      expect(failedMessage.closest('[hidden]')).toBeNull();
      expect(scroll).toHaveBeenCalled();
      expect(startRound).not.toHaveBeenCalled();
    } finally {
      await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
    }
  });
  it("does not call a round successful when its research output failed parsing", () => {
    const props = baseProps();
    const room = { ...props.activeGroupRoom!, rounds: [{
      roundId: "round-invalid", status: "completed", topic: "题目", summary: "4/4 位参与者成功发言",
      messages: [{ messageId: "invalid", participantId: "p1", status: "completed", content: "invalid JSON",
        messagePayload: { kind: "challenge_meeting_message", audit: { parseStatus: "invalid" } } }],
    }] } as never;
    const html = renderToStaticMarkup(<ChatGroupCenterSurface {...props} activeGroupRoom={room} />);
    expect(html).toContain("1 条解析失败");
    expect(html).toContain("最近一轮有 1 条科研发言解析失败");
    expect(html).toContain("本轮结果待处理");
    expect(html).not.toContain("4/4 位参与者成功发言");
  });
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
    expect(html).toContain("下一议题</textarea>");
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
    expect(html).toContain("下一议题</textarea>");
    expect(html.indexOf("更多操作")).toBeLessThan(html.indexOf("启动一轮"));
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

  it("labels the project-bus view as a broadcast instead of borrowing room metadata", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          projectBusActive: true,
          standardGroupRoomActive: false,
          projectBusTimeline: { events: [], activeAgentCount: 3 } as never,
        })}
      />,
    );

    expect(html).toContain("全局广播");
    expect(html).toContain("3 位 active Agent");
    expect(html).not.toContain("round_robin");
    expect(html).not.toContain("discussion");
  });

  it("does not report group participants as the project-bus active agent count", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          projectBusActive: true,
          standardGroupRoomActive: false,
          projectBusTimeline: undefined,
          availableGroupParticipantCount: 7,
        })}
      />,
    );

    expect(html).toContain("正在统计 active Agent");
    expect(html).not.toContain("7 位 active Agent");
  });

  it("keeps group-room rounds out of an empty project-bus notice stream", () => {
    const baseRoom = baseProps().activeGroupRoom!;
    const room = {
      ...baseRoom,
      rounds: [{
        roundId: "r1",
        status: "completed",
        mode: "round_robin",
        purpose: "discussion",
        topic: "群聊议题不应出现在广播流",
        startedAt: "2026-07-20T00:00:00Z",
        updatedAt: "2026-07-20T00:01:00Z",
        speakerOrder: [],
        messages: [],
      }],
    } as never;
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          projectBusActive: true,
          standardGroupRoomActive: false,
          activeGroupRoom: room,
          projectBusTimeline: { events: [], activeAgentCount: 0 } as never,
        })}
      />,
    );

    expect(html).toContain("暂无通知。");
    expect(html).not.toContain("群聊议题不应出现在广播流");
    expect(html).not.toContain("第 1 轮");
  });

  it("keeps the group header quiet and exposes member details on demand", () => {
    const html = renderToStaticMarkup(<ChatGroupCenterSurface {...baseProps()} />);

    expect(html).toContain("团队讨论");
    expect(html).toContain("成员");
    expect(html).not.toContain("位可用助手");
    expect(html).not.toContain("轮询讨论");
    expect(html).not.toContain("全局广播");
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
    // Round summaries render through the markdown pipeline now, so the
    // lead-label rule bolds 结论 exactly like every other message body.
    expect(html).toMatch(/<strong[^>]*>结论<\/strong>：可控/);
    expect(html).toContain("本轮结论");
    expect(html).toContain("group-stream-identity");
    expect(html).toContain("group-stream-topic-identity");
    expect(html).not.toContain("!bg-vui-surface-row");
  });

  it("renders round summary markdown as a table instead of raw pipe text", () => {
    const html = renderToStaticMarkup(
      <ChatGroupCenterSurface
        {...baseProps({
          activeGroupRoom: {
            roomId: "room-1",
            title: "研究组",
            mode: "round_robin",
            purpose: "discussion",
            status: "ready",
            participants: [],
            rounds: [
              {
                roundId: "r1",
                status: "completed",
                mode: "round_robin",
                purpose: "discussion",
                topic: "请讨论拆分风险",
                startedAt: "2026-07-20T00:00:00Z",
                updatedAt: "2026-07-20T00:01:00Z",
                speakerOrder: [],
                messages: [],
                summary: "| 指标 | 数值 |\n| --- | --- |\n| 风险 | 可控 |",
              },
            ],
          } as never,
        })}
      />,
    );

    expect(html).toContain("markdownTableWrap");
    expect(html).toContain("<table");
    expect(html).toContain("风险");
    expect(html).not.toContain("| --- |");
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

    expect(html).toContain("正在停止，已有发言会保留。");
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

  describe("streaming speaker bubble", () => {
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

    function streamingRoomProps(overrides: {
      updatedAt?: string;
      streams?: ChatGroupCenterSurfaceProps["groupSpeakerStreams"];
      groupStreamConnected?: boolean;
    } = {}): Partial<ChatGroupCenterSurfaceProps> {
      const updatedAt = overrides.updatedAt ?? new Date(Date.now() - 5_000).toISOString();
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
              topic: "流式发言",
              startedAt: updatedAt,
              updatedAt,
              speakerOrder: ["p1"],
              messages: [],
              summary: "",
            },
          ],
        } as never,
        activeGroupParticipantById: new Map([["p1", pendingParticipant as never]]),
        groupSpeakerStreams: overrides.streams,
        groupStreamConnected: overrides.groupStreamConnected,
      };
    }

    function speakerStream(content: string, lastDeltaAtMs: number) {
      return {
        r1: {
          p1: {
            roundId: "r1",
            participantId: "p1",
            sessionId: "s1",
            turnId: "t1",
            seq: 3,
            content,
            lastDeltaAtMs,
          },
        },
      };
    }

    it("renders the accumulated speaker text inside the pending bubble while streaming", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps(streamingRoomProps({ streams: speakerStream("流式发言内容", Date.now()) }))}
        />,
      );
      expect(html).toContain("流式发言内容");
      expect(html).toContain("正在输入");
      expect(html).not.toContain("groupTypingDots");
      expect(html).not.toContain("该发言已等待较久");
    });

    it("does not mark an actively streaming speaker stale when round.updatedAt is frozen", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps(streamingRoomProps({
            updatedAt: new Date(Date.now() - 10 * 60_000).toISOString(),
            streams: speakerStream("持续产出中的文本", Date.now()),
          }))}
        />,
      );
      expect(html).toContain("持续产出中的文本");
      expect(html).toContain("正在输入");
      expect(html).not.toContain("等待中");
      expect(html).not.toContain("该发言已等待较久，仍在等待后端响应…");
    });

    it("keeps the frozen text and adds the stale note once deltas stall past the threshold", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps(streamingRoomProps({
            updatedAt: new Date(Date.now() - 10 * 60_000).toISOString(),
            streams: speakerStream("停滞的半截文本", Date.now() - 11 * 60_000),
          }))}
        />,
      );
      expect(html).toContain("停滞的半截文本");
      expect(html).toContain("等待中");
      expect(html).toContain("该发言已等待较久，仍在等待后端响应…");
      expect(html).not.toContain("groupTypingDots");
    });

    it("shows the frozen buffer with the disconnected copy while the stream is down and stale", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps(streamingRoomProps({
            updatedAt: new Date(Date.now() - 10 * 60_000).toISOString(),
            streams: speakerStream("断连前的文本", Date.now() - 11 * 60_000),
            groupStreamConnected: false,
          }))}
        />,
      );
      expect(html).toContain("断连前的文本");
      expect(html).toContain("实时连接已断开，正在重连");
      expect(html).not.toContain("groupTypingDots");
    });

    it("applies the same long-message collapse rule to streamed text", () => {
      const longContent = Array.from({ length: 20 }, (_, index) => `流式第${index}行`).join("\n");
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps(streamingRoomProps({ streams: speakerStream(longContent, Date.now()) }))}
        />,
      );
      expect(html).toContain("展开全文");
      expect(html).toContain("groupBubbleBodyCollapsed");
    });

    it("keeps the typing animation when no delta buffer exists for the speaker", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface {...baseProps(streamingRoomProps({ streams: {} }))} />,
      );
      expect(html).toContain("groupTypingDots");
      expect(html).toContain("正在输入");
      expect(html).not.toContain("该发言已等待较久");
    });
  });

  describe("parallel speaker progress", () => {
    const participants = [
      {
        participantId: "p1",
        kind: "session_agent",
        agentId: "a1",
        agentCode: "A01",
        sessionId: "s1",
        title: "先发言者",
        enabled: true,
        status: "ready",
      },
      {
        participantId: "p2",
        kind: "session_agent",
        agentId: "a2",
        agentCode: "A02",
        sessionId: "s2",
        title: "后发言者",
        enabled: true,
        status: "ready",
      },
    ];

    it("shows running and settled-waiting speakers independently without breaking speaker order", () => {
      const activeGroupRoom = {
        roomId: "room-1",
        title: "并行研究组",
        mode: "round_robin",
        purpose: "discussion",
        status: "running",
        participants,
        rounds: [
          {
            roundId: "r1",
            status: "running",
            mode: "round_robin",
            purpose: "discussion",
            topic: "并行状态",
            startedAt: "2026-09-04T09:00:00Z",
            updatedAt: "2026-09-04T09:00:00Z",
            speakerOrder: ["p1", "p2"],
            speakerProgress: [
              { participantId: "p1", sessionId: "s1", state: "running", status: "", updatedAt: new Date().toISOString() },
              { participantId: "p2", sessionId: "s2", state: "settled", status: "completed", updatedAt: new Date().toISOString() },
            ],
            messages: [],
            summary: "",
          },
        ],
      };
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({
            activeGroupRoom: activeGroupRoom as never,
            activeGroupParticipantById: new Map(participants.map((item) => [item.participantId, item as never])),
            groupParticipantIdentity: (participant) => ({
              name: participant?.title || "Agent",
              identityLabel: participant?.title || "Agent",
              fullIdentityLabel: participant?.title || "Agent",
            }),
          })}
          {...({
            groupSpeakerProgress: {
              r1: {
                p1: activeGroupRoom.rounds[0].speakerProgress[0],
                p2: activeGroupRoom.rounds[0].speakerProgress[1],
              },
            },
          } as never)}
        />,
      );

      expect(html).toContain("先发言者");
      expect(html).toContain("后发言者");
      expect(html.match(/<span>正在输入<\/span>/g)).toHaveLength(1);
      expect(html).toContain("已完成，等待前序发言");
    });
  });

  describe("timeline projection rendering", () => {
    const projectedRound = (roundId: string, topic: string) => ({
      roundId,
      roomId: "room-1",
      topic,
      mode: "round_robin",
      purpose: "discussion",
      config: {},
      status: "completed",
      speakerOrder: [],
      messages: [],
      summary: "",
      startedAt: "2026-09-04T09:00:00Z",
      updatedAt: "2026-09-04T09:01:00Z",
      finishedAt: "2026-09-04T09:01:00Z",
    });
    const projectionOf = (items: unknown, overrides: Record<string, unknown> = {}) => ({
      items,
      legacyFromDetail: false,
      loading: false,
      hasMore: false,
      loadingMore: false,
      loadMore: () => undefined,
      ...overrides,
    });

    it("renders member_change system rows between round sections without shifting round numbering", () => {
      const items = [
        { kind: "round", round: projectedRound("r1", "议题一") },
        {
          kind: "member_change",
          row: {
            key: "tle-3",
            seq: 3,
            createdAt: "2026-09-04T09:02:00Z",
            addedParticipantIds: ["p1"],
            removedParticipantIds: ["p2"],
            participantCount: 3,
          },
        },
        { kind: "round", round: projectedRound("r2", "议题二") },
      ];
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({ activeGroupRoom: undefined })}
          {...({ groupTimeline: projectionOf(items) } as never)}
        />,
      );
      expect(html).toContain("成员加入：Agent");
      expect(html).toContain("成员退出：Agent");
      expect(html).toContain("第 1 轮");
      expect(html).toContain("第 2 轮");
      expect(html).toContain("议题一");
      expect(html).toContain("议题二");
    });

    it("offers artifact actions only with a trusted team and task identity", () => {
      const items = [{ kind: "artifact", row: {
        key: "delivery", seq: 1, createdAt: "", fileCount: 1,
        changedPaths: ["untrusted/path.ts"], changedPathsTruncated: false, taskIds: ["task-1"],
      } }];
      const render = (artifactTeamId?: string) => renderToStaticMarkup(
        <ChatGroupCenterSurface {...baseProps({ artifactTeamId })}
          {...({ groupTimeline: projectionOf(items) } as never)} />,
      );
      expect(render()).not.toContain("查看改动");
      expect(render("team-1")).toContain("查看改动");
      expect(render("team-1")).not.toContain('href="untrusted/path.ts"');
    });

    it("renders dev-board artifact deliveries as system rows between round sections", () => {
      const items = [
        { kind: "round", round: projectedRound("r1", "议题一") },
        {
          kind: "artifact",
          row: {
            key: "tle-4",
            seq: 4,
            createdAt: "2026-09-04T09:03:00Z",
            fileCount: 3,
            changedPaths: ["web/src/a.ts", "web/src/b.ts"],
            changedPathsTruncated: true,
          },
        },
        { kind: "round", round: projectedRound("r2", "议题二") },
      ];
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({ activeGroupRoom: undefined })}
          {...({ groupTimeline: projectionOf(items) } as never)}
        />,
      );
      expect(html).toContain("交付了 3 个文件变更");
      expect(html).toContain("web/src/a.ts、web/src/b.ts…");
      expect(html).toContain("第 1 轮");
      expect(html).toContain("第 2 轮");
      expect(html).toContain("议题二");
    });

    it("offers the cursor load-more affordance only while the timeline has more pages", () => {
      const loadMore = vi.fn();
      const items = [{ kind: "round", round: projectedRound("r1", "议题") }];
      const withMore = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({ activeGroupRoom: undefined })}
          {...({ groupTimeline: projectionOf(items, { hasMore: true, loadMore }) } as never)}
        />,
      );
      expect(withMore).toContain("加载更多记录");
      const withoutMore = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({ activeGroupRoom: undefined })}
          {...({ groupTimeline: projectionOf(items, { loadMore }) } as never)}
        />,
      );
      expect(withoutMore).not.toContain("加载更多记录");
    });

    it("falls back to rendering detail rounds when no timeline projection is provided", () => {
      const html = renderToStaticMarkup(
        <ChatGroupCenterSurface
          {...baseProps({
            activeGroupRoom: {
              roomId: "room-1",
              title: "研究组",
              mode: "round_robin",
              purpose: "discussion",
              status: "ready",
              participants: [],
              rounds: [projectedRound("r1", "旧议题")] as never,
            } as never,
          })}
        />,
      );
      expect(html).toContain("第 1 轮");
      expect(html).toContain("旧议题");
    });
  });
});
