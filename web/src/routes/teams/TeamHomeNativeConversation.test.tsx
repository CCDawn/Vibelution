/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { TeamHomeSurfaceProps } from "./TeamHomeSurface";
import { TeamHomeSurface } from "./TeamHomeSurface";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("./TeamNativeConversation", () => ({ TeamNativeConversation: () => <div data-testid="native-chat-owner" /> }));
vi.mock("../chat/useGroupRoomTimeline", () => ({ useGroupRoomTimeline: () => ({ items: [], legacyFromDetail: true }) }));

const fixture = {
  lang: "zh", selectedTeam: { teamId: "t", name: "开发团队", members: [{ memberId: "m", agentId: "a", agentName: "林舟", role: "协调", agentStatus: "active" }] },
  linkedChatRoomId: "r", linkedRoomDetail: { roomId: "r", participants: [{ kind: "agent", agentId: "a", sessionId: "s" }], rounds: [] },
  linkedRoomBusy: false, linkedChatRoomPending: false, linkedChatRoomError: null, latestTeamRound: null,
  teamTaskTopic: "", onTeamTaskTopicChange: vi.fn(), canStartTeamRound: true, startRoundPending: false, startRoundError: null, onStartTeamRound: vi.fn(),
  stopRoundPending: false, stopRoundError: null, onStopTeamRound: vi.fn(), activeTeamMemberCount: 1, teamSyncPending: false, onSyncRoom: vi.fn(), onOpenOrganization: vi.fn(),
  conversationRequested: true, workspace: { navigation: <p>导航</p>, teamSwitcher: <span>开发团队</span>, toolbar: null, canvas: <div data-testid="real-team-canvas" />, inspector: <p>画布详情</p> },
} as unknown as TeamHomeSurfaceProps;
function LocationReadback() { return <output data-testid="route">{useLocation().search}</output>; }
function withSurface(search: string, check: (host: HTMLDivElement) => void) {
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });
  try { act(() => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/teams?teamConversationTeamId=t&" + search]}><TeamHomeSurface {...fixture} /><LocationReadback /></MemoryRouter></QueryClientProvider>)); check(host); }
  finally { act(() => root.unmount()); host.remove(); client.clear(); }
}
describe("team native conversation selection", () => {
  it("renders the native owner for the linked group and returns to the existing canvas", () => withSurface("teamConversation=group&room=r", (host) => {
    expect(host.querySelector('[data-testid="native-chat-owner"]')).not.toBeNull();
    act(() => Array.from(host.querySelectorAll<HTMLButtonElement>("button")).find((button) => button.textContent === "画布")!.click());
    expect(host.querySelector('[data-testid="real-team-canvas"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="route"]')?.textContent).not.toContain("room=");
  }));
  it("shows the selected member while keeping native session admission and composer ownership", () => withSurface("teamConversation=member&teamMember=m&session=s", (host) => {
    expect(host.querySelector('[data-testid="native-chat-owner"]')).not.toBeNull();
    expect(host.querySelector('[data-team-panel="content"] h2')?.textContent).toBe("林舟 · 对话");
  }));
  it("does not mount a session which is not the selected member's canonical participant session", () => withSurface("teamConversation=member&teamMember=m&session=another-session", (host) => {
    expect(host.querySelector('[data-testid="native-chat-owner"]')).toBeNull();
    expect(host.textContent).toContain("成员会话尚不可用");
  }));
});
