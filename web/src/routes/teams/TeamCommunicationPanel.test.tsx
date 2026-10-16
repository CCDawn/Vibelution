/** @vitest-environment happy-dom */

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatRoomDetail, Team } from "../../api/types";
import { TeamCommunicationPanel, type TeamCommunicationPanelProps } from "./TeamCommunicationPanel";
import { TeamInspectorTabs } from "./TeamInspectorTabs";

vi.mock("../../api/teamMemberMessages", () => ({
  listTeamMemberMessages: vi.fn().mockResolvedValue({ messages: [] }),
  teamMemberMessageSessionHref: vi.fn().mockReturnValue("/chat"),
}));

vi.mock("../../api/devTeamTasks", () => ({
  listDevTeamTasks: vi.fn().mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" }),
  listDevTeamTaskChanges: vi.fn(),
  createDevTeamTask: vi.fn(),
  mutateDevTeamTask: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const selectedTeam = {
  teamId: "team-1",
  name: "科研团队",
  linkedChatRoomId: "room-1",
  linkedChatRoom: { mode: "round_robin", purpose: "discussion" },
} as unknown as Team;

const linkedRoomDetail = {
  roomId: "room-1",
  status: "running",
  mode: "round_robin",
  purpose: "discussion",
} as unknown as ChatRoomDetail;

const baseProps: TeamCommunicationPanelProps = {
  lang: "zh",
  selectedTeam,
  linkedChatRoomId: "room-1",
  linkedRoomDetail,
  linkedRoomBusy: true,
  linkedChatRoomPending: false,
  linkedChatRoomError: null,
  latestTeamRound: null,
  teamTaskTopic: "下一轮研究议题",
  onTeamTaskTopicChange: vi.fn(),
  canStartTeamRound: true,
  startRoundPending: false,
  startRoundResult: undefined,
  startRoundError: null,
  onStartTeamRound: vi.fn(),
  stopRoundPending: false,
  stopRoundError: null,
  onStopTeamRound: vi.fn(),
  teamMessage: "",
  onTeamMessageChange: vi.fn(),
  teamInterrupt: false,
  onTeamInterruptChange: vi.fn(),
  activeTeamMemberCount: 2,
  messagePending: false,
  messageResult: undefined,
  messageError: null,
  onSendTeamMessage: vi.fn(),
  teamBusEvents: [],
  projectBusPending: false,
  revokePendingEventId: null,
  revokeError: null,
  onRevokeTeamMessage: vi.fn(),
};

function renderPanel(overrides: Partial<TeamCommunicationPanelProps> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TeamCommunicationPanel {...baseProps} {...overrides} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TeamCommunicationPanel round controls", () => {
  it("places task actions and history in separate slots without duplicating the task board", () => {
    const team = { ...selectedTeam, teamTemplateId: "dev-team", members: [] } as Team;
    const tasks = renderPanel({ selectedTeam: team, section: "tasks" });
    const records = renderPanel({ selectedTeam: team, section: "records" });
    expect(tasks).toContain("共享任务板");
    expect(tasks).toContain("团队广播");
    expect(tasks).not.toContain("最近团队广播");
    expect(tasks).not.toContain("成员通信");
    expect(records).toContain("最近团队广播");
    expect(records).toContain("成员通信");
    expect(records).not.toContain("共享任务板");
    expect(records).not.toContain("<form");
  });

  it("tells a development team how the planned round closes", () => {
    const html = renderPanel({
      selectedTeam: {
        ...selectedTeam,
        teamTemplateId: "dev-team",
        name: "开发团队",
      } as Team,
      linkedRoomBusy: false,
    });
    expect(html).toContain("启动开发轮次");
    expect(html).toContain("@评审员");
    expect(html).not.toContain("启动团队讨论");
  });

  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    host = null;
    root = null;
  });

  it("retains task and broadcast drafts across inspector sections and dispatches the native payloads", async () => {
    const onStartTeamRound = vi.fn();
    const onSendTeamMessage = vi.fn();
    const props = {
      ...baseProps,
      linkedRoomBusy: false,
      onStartTeamRound,
      onSendTeamMessage,
    };
    function DraftInspector() {
      const [topic, setTopic] = React.useState("");
      const [message, setMessage] = React.useState("");
      const draftProps = { ...props, teamTaskTopic: topic, onTeamTaskTopicChange: setTopic, teamMessage: message, onTeamMessageChange: setMessage };
      return <TeamInspectorTabs lang="zh" selectedNodeId="node-a" members={<p>成员</p>}
        tasks={<TeamCommunicationPanel {...draftProps} section="tasks" />}
        records={<TeamCommunicationPanel {...draftProps} section="records" />} />;
    }
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => root?.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <DraftInspector />
        </MemoryRouter>
      </QueryClientProvider>,
    ));
    const taskInput = host.querySelector<HTMLTextAreaElement>('form[aria-label="团队任务"] textarea')!;
    const broadcastInput = host.querySelector<HTMLTextAreaElement>('form[aria-label="团队广播"] textarea')!;
    await act(async () => {
      for (const [input, value] of [[taskInput, "检查现有任务链路"], [broadcastInput, "保留广播草稿"]] as const) {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    for (const label of ["任务", "记录", "成员", "任务"]) {
      const tab = Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
        .find((element) => element.textContent === label);
      await act(async () => tab?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    }
    expect(host.querySelector('form[aria-label="团队任务"] textarea')).toBe(taskInput);
    expect(host.querySelector('form[aria-label="团队广播"] textarea')).toBe(broadcastInput);
    expect(taskInput.value).toBe("检查现有任务链路");
    expect(broadcastInput.value).toBe("保留广播草稿");
    expect(host.querySelectorAll('form[aria-label="团队任务"]')).toHaveLength(1);
    for (const label of ["团队任务", "团队广播"]) {
      await act(async () => host?.querySelector(`form[aria-label="${label}"]`)
        ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    }
    expect(onStartTeamRound).toHaveBeenCalledWith({
      roomId: "room-1", teamId: "team-1", topic: "检查现有任务链路", mode: "round_robin", purpose: "discussion",
    });
    expect(onSendTeamMessage).toHaveBeenCalledWith({ teamId: "team-1", content: "保留广播草稿", interruptMode: "none" });
  });

  it("shows the shared task board only on a development team", () => {
    expect(renderPanel()).not.toContain("共享任务板");
    const html = renderPanel({
      selectedTeam: {
        ...selectedTeam,
        teamTemplateId: "dev-team",
        members: [
          { memberId: "m-plan", role: "规划师", agentName: "规划师", agentId: "a1", agentCode: "plan", agentStatus: "active", purpose: "" },
        ],
      } as Team,
    });
    expect(html).toContain("共享任务板");
  });

  it("shows the speaking role on the task board instead of a manual identity", () => {
    const html = renderPanel({
      selectedTeam: {
        ...selectedTeam,
        teamTemplateId: "dev-team",
        name: "开发团队",
        members: [
          { memberId: "m-plan", role: "规划师", agentName: "规划师", agentId: "a-plan", agentCode: "plan", agentStatus: "active", purpose: "" },
          { memberId: "m-a", role: "开发工程师 A", agentName: "工程师A", agentId: "a-eng", agentCode: "dev-a", agentStatus: "active", purpose: "" },
        ],
      } as Team,
      linkedRoomDetail: {
        ...linkedRoomDetail,
        participants: [
          { participantId: "p-a", agentId: "a-eng", teamRole: "开发工程师 A" },
        ],
        activeRoundId: "round-1",
        rounds: [
          {
            roundId: "round-1",
            status: "running",
            speakerProgress: [{ participantId: "p-a", state: "running", updatedAt: "2026-10-08T00:00:00Z" }],
          },
        ],
      } as ChatRoomDetail,
    });
    expect(html).toContain('aria-label="当前身份"');
    expect(html).toContain("开发工程师 A");
    expect(html).not.toContain("新建任务");
    expect(html).not.toMatch(/<select[^>]*aria-label="当前身份"/);
    expect(html).toContain("工程师A · 开发工程师 A");
  });

  it("keeps the last speaker when the round is open again and nobody is speaking", () => {
    const html = renderPanel({
      selectedTeam: {
        ...selectedTeam,
        teamTemplateId: "dev-team",
        name: "开发团队",
        members: [
          { memberId: "m-plan", role: "规划师", agentName: "规划师", agentId: "a-plan", agentCode: "plan", agentStatus: "active", purpose: "" },
          { memberId: "m-rev", role: "评审员", agentName: "评审员", agentId: "a-rev", agentCode: "rev", agentStatus: "active", purpose: "" },
        ],
      } as Team,
      linkedRoomBusy: false,
      linkedRoomDetail: {
        ...linkedRoomDetail,
        status: "ready",
        participants: [
          { participantId: "p-plan", agentId: "a-plan", teamRole: "规划师" },
          { participantId: "p-rev", agentId: "a-rev", teamRole: "评审员" },
        ],
        activeRoundId: "",
        rounds: [
          {
            roundId: "round-done",
            status: "completed",
            messages: [
              { participantId: "p-plan", timestamp: "2026-10-08T00:00:01Z" },
              { participantId: "p-rev", timestamp: "2026-10-08T00:00:02Z" },
            ],
            speakerProgress: [
              { participantId: "p-rev", state: "settled", status: "completed", updatedAt: "2026-10-08T00:00:02Z" },
            ],
          },
        ],
      } as ChatRoomDetail,
    });
    expect(html).toContain('aria-label="当前身份">评审员');
    expect(html).not.toContain("新建任务");
  });

  it("shows an in-place stop action while the linked room is busy", () => {
    const html = renderPanel();

    expect(html).toContain("停止当前讨论");
    expect(html).toContain('aria-label="停止当前团队讨论"');
  });

  it("dispatches the stop mutation for the selected room and team", async () => {
    const onStopTeamRound = vi.fn();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);

    await act(async () => {
      root?.render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <TeamCommunicationPanel {...baseProps} onStopTeamRound={onStopTeamRound} />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });

    const button = host.querySelector<HTMLButtonElement>('button[aria-label="停止当前团队讨论"]');
    expect(button).toBeTruthy();
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onStopTeamRound).toHaveBeenCalledWith({ roomId: "room-1", teamId: "team-1" });
  });

  it("keeps the stop error visible as an actionable alert", () => {
    const html = renderPanel({ stopRoundError: new Error("停止团队讨论失败，请稍后重试") });

    expect(html).toContain('role="alert"');
    expect(html).toContain("停止团队讨论失败，请稍后重试");
  });

  it("disables the control and explains that the round is stopping", () => {
    const html = renderPanel({
      stopRoundPending: true,
      linkedRoomDetail: { ...linkedRoomDetail, status: "stopping" } as ChatRoomDetail,
    });

    expect(html).toContain("停止中");
    expect(html).toMatch(/aria-label="停止当前团队讨论"[^>]*disabled/);
  });
});
