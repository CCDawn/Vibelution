/** @vitest-environment happy-dom */

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { ChatRoomDetail, ChatRoomRound, Team } from "../../api/types";
import { TeamHomeSurface, type TeamHomeSurfaceProps } from "./TeamHomeSurface";

const timelineProjection = vi.hoisted(() => ({ items: null as never[] | null }));
vi.mock("./TeamNativeConversation", () => ({ TeamNativeConversation: () => <div data-testid="native-team-chat">原生群聊<textarea aria-label="会话草稿" defaultValue="" /></div> }));

function LocationProbe() { return <output data-testid="location">{useLocation().search}</output>; }

vi.mock("../chat/useGroupRoomTimeline", () => ({
  useGroupRoomTimeline: ({ detail }: { detail: { rounds?: unknown[] } | null }) => ({
    items: timelineProjection.items ?? (detail?.rounds ?? []).map((round) => ({ kind: "round" as const, round })),
    legacyFromDetail: timelineProjection.items === null,
    loading: false,
    hasMore: false,
    loadingMore: false,
    loadMore: vi.fn(),
  }),
}));

vi.mock("../../api/devTeamTasks", () => ({
  listDevTeamTasks: vi.fn().mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" }),
  listDevTeamTaskChanges: vi.fn().mockResolvedValue({ schemaVersion: 1, teamId: "team-1", changes: [] }),
  createDevTeamTask: vi.fn(),
  mutateDevTeamTask: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const team = {
  teamId: "team-1",
  name: "产品团队",
  linkedChatRoom: { mode: "round_robin", purpose: "discussion" },
  members: [
    { memberId: "member-1", agentId: "agent-1", agentCode: "A100", agentName: "顾言初", role: "规划师", purpose: "规划" },
  ],
} as unknown as Team;

const round = {
  roundId: "round-1",
  roomId: "room-1",
  topic: "完成首页设计",
  mode: "round_robin",
  purpose: "discussion",
  status: "completed",
  messages: [
    {
      messageId: "visible-1",
      participantId: "participant-1",
      agentId: "agent-1",
      speakerTitle: "A100",
      summary: "整理了首页信息层级。",
      content: "完整发言",
      timestamp: "2026-10-10T08:00:00.000Z",
      audience: "user",
      visibility: "default",
    },
    {
      messageId: "internal-1",
      speakerTitle: "内部计划",
      summary: "内部调度细节不应展示。",
      content: "隐藏内容",
      timestamp: "2026-10-10T08:01:00.000Z",
      audience: "internal",
      visibility: "default",
    },
    {
      messageId: "collapsed-1",
      speakerTitle: "执行日志",
      summary: "默认折叠的日志不应展示。",
      content: "隐藏日志",
      timestamp: "2026-10-10T08:02:00.000Z",
      audience: "user",
      visibility: "collapsed_by_default",
    },
  ],
  summary: "汇总结果只展示一次。",
  startedAt: "2026-10-10T07:55:00.000Z",
  updatedAt: "2026-10-10T08:02:00.000Z",
} as unknown as ChatRoomRound;

const baseProps: TeamHomeSurfaceProps = {
  lang: "zh",
  selectedTeam: team,
  linkedChatRoomId: "room-1",
  linkedRoomDetail: {
    roomId: "room-1",
    mode: "round_robin",
    purpose: "discussion",
    rounds: [round],
    participants: [{ participantId: "participant-1", agentId: "agent-1", title: "A100", sessionId: "session-1", enabled: true, status: "ready" }],
  } as ChatRoomDetail,
  linkedRoomBusy: false,
  linkedChatRoomPending: false,
  linkedChatRoomError: null,
  latestTeamRound: round,
  teamTaskTopic: "下一轮任务",
  onTeamTaskTopicChange: vi.fn(),
  canStartTeamRound: true,
  startRoundPending: false,
  startRoundError: null,
  onStartTeamRound: vi.fn(),
  stopRoundPending: false,
  stopRoundError: null,
  onStopTeamRound: vi.fn(),
  activeTeamMemberCount: 2,
  teamSyncPending: false,
  onSyncRoom: vi.fn(),
  onOpenOrganization: vi.fn(),
};

function renderSurface(overrides: Partial<TeamHomeSurfaceProps> = {}) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <TeamHomeSurface {...baseProps} {...overrides} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TeamHomeSurface", () => {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) act(() => root?.unmount());
    host?.remove();
    host = null;
    root = null;
    timelineProjection.items = null;
  });

  it("opens an explicit team canvas from native chat and returns to the same room", async () => {
    host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
    await act(async () => {
      root?.render(<QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/teams?teamId=team-1&teamConversationTeamId=team-1&teamConversation=group&room=room-1"]}>
          <TeamHomeSurface {...baseProps} conversationRequested workspace={{
            navigation: <div>成员列表</div>, teamSwitcher: <div>产品团队</div>, toolbar: null,
            canvas: <div data-testid="organization-canvas">组织画布</div>, inspector: <div>节点详情</div>,
            resize: { sidebar: { id: "rail", defaultWidth: 220, minWidth: 200, maxWidth: 280 }, aside: { id: "inspector", defaultWidth: 312, minWidth: 280, maxWidth: 380 } },
          }} />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>);
    });
    expect(host.querySelector('[data-testid="native-team-chat"]')).toBeTruthy();
    const click = async (label: string) => {
      const button = [...host!.querySelectorAll("button")].find((item) => item.textContent?.trim() === label);
      expect(button).toBeTruthy();
      await act(async () => { button?.dispatchEvent(new MouseEvent(button?.getAttribute("role") === "tab" ? "mousedown" : "click", { bubbles: true, button: 0 })); });
    };
    const draft = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="会话草稿"]')!;
    draft.value = "尚未发送的讨论";
    await click("任务");
    expect(host.querySelector('[role="tabpanel"][data-state="active"]')?.textContent).toContain("完成首页设计");
    await click("画布");
    expect(host.querySelector('[data-testid="organization-canvas"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="native-team-chat"]')?.closest('[role="tabpanel"]')?.getAttribute("data-state")).toBe("inactive");
    expect(host.querySelector("output")?.textContent).toContain("teamView=canvas");
    expect(host.querySelector("output")?.textContent).toContain("room=room-1");
    await click("讨论");
    expect(host.querySelector('[data-testid="native-team-chat"]')).toBeTruthy();
    expect(host.querySelector("output")?.textContent).toContain("room=room-1");
    expect(host.querySelector('textarea[aria-label="会话草稿"]')).toBe(draft);
    expect(draft.value).toBe("尚未发送的讨论");
  });

  it("shows recent round messages through the shared group renderer and links to the room", () => {
    const html = renderSurface();

    expect(html).toContain('data-vui-region="team-home-surface"');
    expect(html).toContain("vui-workbench-toolbar");
    expect(html).toContain('data-team-panel="inspector"');
    expect(html).toContain("完整发言");
    expect(html).toContain("顾言初");
    expect(html).toContain("打开群聊");
    expect(html).toContain('href="/chat?room=room-1');
    expect(html.match(/汇总结果只展示一次。/g)).toHaveLength(1);
  });

  it("keeps delivery counters inside a collapsed round-result disclosure", () => {
    const html = renderSurface({
      latestTeamRound: {
        ...round,
        summary: "本轮群聊完成：2/2 位参与者成功发言；1 项投递已记录。",
      } as ChatRoomRound,
    });

    expect(html).toContain("<details");
    expect(html).toContain("轮次结果");
    expect(html).not.toContain("本轮结论");
  });

  it("uses structured message display fields instead of rendering raw protocol JSON", () => {
    const html = renderSurface({
      latestTeamRound: {
        ...round,
        messages: [
          {
            ...round.messages[0],
            content: '{"schemaVersion":1,"display":{"conclusion":"raw json"},"protocol":{}}',
            messagePayload: {
              schemaVersion: 1,
              kind: "challenge_meeting_message",
              display: { conclusion: "结构化结论先展示。", sections: [{ title: "依据", bullets: ["关键证据"] }] },
              protocol: { agreements: [], disagreements: [], risks: [], actionItems: [], knowledgeCandidates: [], proposedCandidates: [], evidenceRequests: [] },
              audit: { parseStatus: "structured", rawModelOutput: '{"protocol":"hidden raw output"}' },
            },
          },
        ],
      } as ChatRoomRound,
    });

    expect(html).toContain("结构化结论先展示。");
    expect(html).toContain("关键证据");
    expect(html).not.toContain("&quot;schemaVersion&quot;");
    expect(html).not.toContain("hidden raw output");
  });

  it("renders the timeline projection instead of the detail snapshot's raw transcript", () => {
    const projectedRound = {
      ...round,
      topic: "timeline 中的任务标题",
      summary: "timeline 中的结论",
      messages: [{
        ...round.messages[0],
        messageId: "timeline-message",
        summary: "timeline 中的真实发言",
        content: "timeline 中的真实发言",
      }],
    } as ChatRoomRound;
    timelineProjection.items = [{ kind: "round", round: projectedRound } as never];

    const html = renderSurface({
      latestTeamRound: {
        ...round,
        topic: "当前任务标题",
        summary: '{"schemaVersion":1,"display":{"conclusion":"原始 JSON"}}',
        messages: [{
          ...round.messages[0],
          messageId: "detail-message",
          content: '{"schemaVersion":1,"display":{"conclusion":"详情原始 JSON"}}',
        }],
      } as ChatRoomRound,
    });

    expect(html).toContain("当前任务标题");
    expect(html).toContain("timeline 中的结论");
    expect(html).toContain("timeline 中的真实发言");
    expect(html).not.toContain("详情原始 JSON");
    expect(html).not.toContain("\"conclusion\":\"原始 JSON\"");
  });

  it("does not attach an older timeline round to the current task while the timeline catches up", () => {
    timelineProjection.items = [{
      kind: "round",
      round: { ...round, summary: "上一轮结论", messages: [{ ...round.messages[0], content: "上一轮发言" }] },
    } as never];

    const html = renderSurface({
      linkedRoomBusy: true,
      latestTeamRound: {
        ...round,
        roundId: "round-current",
        topic: "当前执行任务",
        status: "running",
        summary: "",
        messages: [],
        updatedAt: "2026-10-10T08:05:00.000Z",
      } as ChatRoomRound,
    });

    expect(html).toContain("当前执行任务");
    expect(html).toContain("进行中");
    expect(html).toContain("正在同步本轮发言…");
    expect(html).not.toContain("上一轮结论");
    expect(html).not.toContain("上一轮发言");
  });

  it("invalidates the timeline when the room detail advances after its initial snapshot", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);

    const render = (props: TeamHomeSurfaceProps) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><TeamHomeSurface {...props} /></MemoryRouter>
      </QueryClientProvider>
    );

    await act(async () => {
      root?.render(render(baseProps));
    });
    expect(invalidate).not.toHaveBeenCalled();

    await act(async () => {
      root?.render(render({
        ...baseProps,
        linkedRoomDetail: { ...baseProps.linkedRoomDetail, updatedAt: "2026-10-10T08:10:00.000Z" } as ChatRoomDetail,
        latestTeamRound: { ...round, updatedAt: "2026-10-10T08:10:00.000Z" } as ChatRoomRound,
      }));
    });

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.chatRoomTimeline("room-1") });
  });

  it("reuses the shared task board for development teams", () => {
    const html = renderSurface({ selectedTeam: { ...team, teamTemplateId: "dev-team" } as Team });

    expect(html).toContain("共享任务板");
    expect(html).toContain("当前身份");
  });

  it("dispatches start and stop actions for the selected team and linked room", async () => {
    const onStartTeamRound = vi.fn();
    const onStopTeamRound = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);

    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <TeamHomeSurface {...baseProps} onStartTeamRound={onStartTeamRound} onStopTeamRound={onStopTeamRound} />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });

    const form = host.querySelector<HTMLFormElement>("form");
    expect(form).toBeTruthy();
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(onStartTeamRound).toHaveBeenCalledWith({
      roomId: "room-1",
      teamId: "team-1",
      topic: "下一轮任务",
      mode: "round_robin",
      purpose: "discussion",
    });

    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <TeamHomeSurface {...baseProps} linkedRoomBusy onStartTeamRound={onStartTeamRound} onStopTeamRound={onStopTeamRound} />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
    const stopButton = Array.from(host.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button.textContent?.includes("停止本轮"));
    expect(stopButton).toBeTruthy();
    await act(async () => {
      stopButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onStopTeamRound).not.toHaveBeenCalled();
    const confirmButton = Array.from(document.body.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button !== stopButton && button.textContent?.trim() === "停止本轮");
    expect(confirmButton).toBeTruthy();
    await act(async () => {
      confirmButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onStopTeamRound).toHaveBeenCalledWith({ roomId: "room-1", teamId: "team-1" });
  });
});
