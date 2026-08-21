/** @vitest-environment happy-dom */

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatRoomDetail, Team } from "../../api/types";
import { TeamCommunicationPanel, type TeamCommunicationPanelProps } from "./TeamCommunicationPanel";

vi.mock("../../api/teamMemberMessages", () => ({
  listTeamMemberMessages: vi.fn().mockResolvedValue({ messages: [] }),
  teamMemberMessageSessionHref: vi.fn().mockReturnValue("/chat"),
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
