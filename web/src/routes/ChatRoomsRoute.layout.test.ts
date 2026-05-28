import { describe, expect, it } from "vitest";

import routeSource from "./ChatRoomsRoute.tsx?raw";
import routeStyles from "./ChatRoomsRoute.module.css";

describe("ChatRoomsRoute layout contract", () => {
  it("shows selectable participants as Agent names with colored functional labels", () => {
    expect(routeSource).toContain("fetchJson<AgentInstance[]>(\"/api/agents\")");
    expect(routeSource).toContain("sessionAgentDisplayInfo(session");
    expect(routeSource).toContain("styles.agentRoleTag");
    expect(routeSource).toContain("display.functionLabel");
    expect(routeSource).not.toContain("<small>{session.currentPhase || session.status}</small>");

    expect(routeStyles.agentRoleTag).toBeTypeOf("string");
    expect(routeStyles.agentRoleTag_chat).toBeTypeOf("string");
    expect(routeStyles.agentRoleTag_research).toBeTypeOf("string");
    expect(routeStyles.agentRoleTag_self).toBeTypeOf("string");
    expect(routeStyles.agentRoleTag_supervised).toBeTypeOf("string");
  });

  it("keeps scheduler mode separate from conversation purpose", () => {
    expect(routeSource).toContain("fetchJson<ChatRoomPurpose[]>(\"/api/chat-rooms/purposes\")");
    expect(routeSource).toContain("queryKeys.chatRoomPurposes()");
    expect(routeSource).toContain("purpose: runnablePurposeId");
    expect(routeSource).toContain("runnableModeId !== (activeRoom.mode || \"round_robin\")");
    expect(routeSource).toContain("runnablePurposeId !== (activeRoom.purpose || \"discussion\")");
    expect(routeSource).toContain("purposeLabel(purpose, lang)");
    expect(routeSource).toContain("对话目的");
  });
});
