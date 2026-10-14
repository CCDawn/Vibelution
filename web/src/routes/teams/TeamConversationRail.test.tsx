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
