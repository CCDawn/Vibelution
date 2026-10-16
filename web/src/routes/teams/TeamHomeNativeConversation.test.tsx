/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { TeamHomeSurfaceProps } from "./TeamHomeSurface";
import { TeamHomeSurface } from "./TeamHomeSurface";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const shortcut = vi.hoisted(() => vi.fn());
vi.mock("./TeamNativeConversation", () => ({ TeamNativeConversation: () => {
  React.useEffect(() => {
    window.addEventListener("native-shortcut-probe", shortcut);
    return () => window.removeEventListener("native-shortcut-probe", shortcut);
  }, []);
  return <div data-testid="native-chat-owner" />;
} }));
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
function withSurface(search: string, check: (host: HTMLDivElement) => void, overrides: Partial<TeamHomeSurfaceProps> = {}) {
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });
  try { act(() => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/teams?teamConversationTeamId=t&" + search]}><TeamHomeSurface {...fixture} {...overrides} /><LocationReadback /></MemoryRouter></QueryClientProvider>)); check(host); }
  finally { act(() => root.unmount()); host.remove(); client.clear(); }
}
describe("team native conversation selection", () => {
  it("renders the native owner for the linked group and returns to the existing canvas", () => withSurface("teamConversation=group&room=r", (host) => {
    expect(host.querySelector('[data-testid="native-chat-owner"]')).not.toBeNull();
    act(() => Array.from(host.querySelectorAll<HTMLButtonElement>("button")).find((button) => button.textContent === "画布")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(host.querySelector('[data-testid="real-team-canvas"]')?.closest('[role="tabpanel"]')?.getAttribute("data-state")).toBe("active");
    expect(host.querySelector('[data-testid="route"]')?.textContent).toContain("room=r");
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

function selectView(host: HTMLElement, label: string) {
  act(() => Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((tab) => tab.textContent === label)!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
}
function clickAction(host: ParentNode, label: string) {
  act(() => Array.from(host.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === label)!.click());
}
describe("approved team workspace", () => {
  it("defaults to discussion with no inspector and canonicalizes the linked group", () => withSurface("", (host) => {
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("讨论");
    expect(host.querySelector('[data-team-panel="inspector"]')).toBeNull();
    expect(host.querySelector('[data-testid="native-chat-owner"]')).not.toBeNull();
    expect(host.querySelector('output')?.textContent).toContain("room=r");
  }, { conversationRequested: false }));
  it("keeps tasks in the main pane while showing and closing member details", () => withSurface("teamView=tasks&teamConversation=group&room=r", (host) => {
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("任务");
    clickAction(host, "详情");
    expect(document.body.querySelector('[data-team-panel="inspector"]')?.textContent).toContain("画布详情");
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("任务");
    act(() => document.body.querySelector<HTMLButtonElement>('button[aria-label="关闭详情"]')!.click());
    expect(host.querySelector('[data-team-panel="inspector"]')).toBeNull();
  }));
  it("starts the selected team's real round from the canvas without changing the selected view", () => {
    const start = vi.fn();
    withSurface("teamView=canvas&teamConversation=group&room=r", (host) => {
      clickAction(host, "开始新一轮");
      act(() => document.body.querySelector('form')!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
      expect(start).toHaveBeenCalledWith({ roomId: "r", teamId: "t", topic: "交付登录页", mode: "round_robin", purpose: "discussion" });
      expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("画布");
    }, { teamTaskTopic: "交付登录页", onStartTeamRound: start });
  });
  it("keeps stop confirmation and shows the room's running status even before the latest round catches up", () => {
    const stop = vi.fn();
    withSurface("teamConversation=group&room=r", (host) => {
      expect(host.querySelector('[aria-label="当前轮次"]')?.textContent).toContain("进行中");
      selectView(host, "任务");
      clickAction(host, "停止本轮");
      expect(stop).not.toHaveBeenCalled();
      clickAction(document.body.querySelector('[role="dialog"]')!, "停止本轮");
      expect(stop).toHaveBeenCalledWith({ roomId: "r", teamId: "t" });
    }, { linkedRoomBusy: true, onStopTeamRound: stop, latestTeamRound: { status: "completed", topic: "旧目标" } as TeamHomeSurfaceProps["latestTeamRound"] });
  });
  it("preserves a selected member session across tasks and canvas", () => withSurface("teamConversation=member&teamMember=m&session=s", (host) => {
    const native = host.querySelector('[data-testid="native-chat-owner"]');
    selectView(host, "任务"); selectView(host, "画布"); selectView(host, "讨论");
    expect(host.querySelector('[data-testid="native-chat-owner"]')).toBe(native);
    expect(host.querySelector('output')?.textContent).toContain("session=s");
    expect(host.querySelector('output')?.textContent).not.toContain("room=");
  }));
});

describe("team route and hidden conversation isolation", () => {
  it("does not canonicalize a target team URL while the selected team is still catching up", () => {
    for (const target of ["member&teamMember=other&session=other-session", "canvas&teamView=canvas"]) {
      withSurface(`teamId=other-team&teamConversation=${target}`, (host) => {
        const route = host.querySelector('output')?.textContent;
        expect(route).toContain("teamId=other-team");
        expect(route).toContain(`teamConversation=${target}`);
        expect(route).not.toContain("room=r");
      });
    }
  });
  it("deactivates native effects on hidden views and restores them on return without dropping the component", () => withSurface("teamConversation=group&room=r", (host) => {
    shortcut.mockClear();
    window.dispatchEvent(new Event("native-shortcut-probe"));
    expect(shortcut).toHaveBeenCalledTimes(1);
    const native = host.querySelector('[data-testid="native-chat-owner"]');
    selectView(host, "任务");
    window.dispatchEvent(new Event("native-shortcut-probe"));
    expect(shortcut).toHaveBeenCalledTimes(1);
    selectView(host, "画布");
    window.dispatchEvent(new Event("native-shortcut-probe"));
    expect(shortcut).toHaveBeenCalledTimes(1);
    selectView(host, "讨论");
    window.dispatchEvent(new Event("native-shortcut-probe"));
    expect(shortcut).toHaveBeenCalledTimes(2);
    expect(host.querySelector('[data-testid="native-chat-owner"]')).toBe(native);
  }));
});

it("closes narrow navigation after choosing a member conversation", () => {
  const previousWidth = window.innerWidth;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
  try {
    withSurface("teamConversation=group&room=r", (host) => {
      clickAction(host, "打开团队导航");
      act(() => document.body.querySelector<HTMLAnchorElement>('a[data-testid="member-link"]')!.click());
      expect(document.body.querySelector('[role="dialog"]')).toBeNull();
      expect(host.querySelector('output')?.textContent).toContain("session=s");
      expect(host.querySelector('[data-team-panel="content"] h2')?.textContent).toBe("林舟 · 对话");
    }, { workspace: { ...fixture.workspace!, navigation: <Link data-testid="member-link" to="?teamConversationTeamId=t&teamConversation=member&teamMember=m&session=s&teamView=discussion">打开成员</Link> } });
  } finally { Object.defineProperty(window, "innerWidth", { configurable: true, value: previousWidth }); }
});
