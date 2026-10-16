/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { ChatRoomDetail, Team } from "../../api/types";
import { TeamConversationRail } from "./TeamConversationRail";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("keeps team and canonical members in one actionable list, disabling unlinked members", () => {
  const team = { name: "开发团队", members: [
    { memberId: "one", agentId: "a", agentName: "林舟", role: "协调", agentStatus: "active" },
    { memberId: "two", agentId: "b", agentName: "顾言", role: "实现", agentStatus: "active" },
  ] } as Team;
  const room = { participants: [{ kind: "agent", agentId: "a", sessionId: "native-a" }] } as ChatRoomDetail;
  const group = vi.fn(), member = vi.fn();
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  try {
    act(() => root.render(<TeamConversationRail team={team} room={room} lang="zh" selectedMemberId="one" groupSelected={false} onOpenGroup={group} onOpenMember={member} />));
    const entries = host.querySelectorAll<HTMLButtonElement>("nav button");
    expect(entries).toHaveLength(3); expect(entries[0].textContent).toContain("开发团队");
    expect(entries[1].getAttribute("aria-pressed")).toBe("true"); expect(entries[2].disabled).toBe(true);
    act(() => { entries[0].click(); entries[1].click(); entries[2].click(); });
    expect(group).toHaveBeenCalledOnce(); expect(member).toHaveBeenCalledExactlyOnceWith(team.members[0], "native-a");
  } finally { act(() => root.unmount()); host.remove(); }
});

it("routes missing sessions to sync and stale members to their configuration, retaining the busy and error state", () => {
  const team = { name: "开发团队", members: [
    { memberId: "missing", agentId: "a", agentName: "林舟", role: "协调", agentStatus: "active" },
    { memberId: "stale", agentId: "b", agentName: "顾言", role: "实现", agentStatus: "stale" },
  ] } as Team;
  const room = { participants: [{ kind: "agent", agentId: "b", sessionId: "stale-native" }] } as ChatRoomDetail;
  const sync = vi.fn(), configure = vi.fn(), member = vi.fn();
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const render = (pending = false) => act(() => root.render(<TeamConversationRail team={team} room={room} lang="zh"
    selectedMemberId="" groupSelected={false} onOpenGroup={vi.fn()} onOpenMember={member}
    onSyncRoom={sync} onConfigureMember={configure} syncPending={pending} syncError="同步失败，请重试" />));
  try {
    render();
    const syncButton = host.querySelector<HTMLButtonElement>('[aria-label="林舟 · 同步会话"]')!;
    const configureButton = host.querySelector<HTMLButtonElement>('[aria-label="顾言 · 配置成员"]')!;
    expect(host.textContent).toContain("会话尚未同步");
    expect(host.textContent).toContain("成员配置不可用");
    act(() => { syncButton.click(); configureButton.click(); });
    expect(sync).toHaveBeenCalledOnce();
    expect(configure).toHaveBeenCalledExactlyOnceWith("stale");
    expect(member).not.toHaveBeenCalled();
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("同步失败，请重试");
    render(true);
    expect(syncButton.disabled).toBe(true);
    expect(configureButton.disabled).toBe(false);
    act(() => syncButton.click());
    expect(sync).toHaveBeenCalledOnce();
  } finally { act(() => root.unmount()); host.remove(); }
});
