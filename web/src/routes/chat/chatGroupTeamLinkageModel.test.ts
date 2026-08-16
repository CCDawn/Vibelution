import { describe, expect, it } from "vitest";

import type { ChatRoomDetail, Team } from "../../api/types";
import { buildLinkedTeamRoomIds, resolveActiveGroupTeam } from "./chatGroupTeamLinkageModel";

function makeTeam(overrides: Partial<Team> = {}): Team {
  return {
    teamId: "team-1",
    name: "Team",
    linkedChatRoomId: "",
    ...overrides,
  } as Team;
}

function makeRoom(overrides: Partial<ChatRoomDetail> = {}): ChatRoomDetail {
  return {
    roomId: "room-1",
    title: "群聊",
    mode: "round_robin",
    purpose: "discussion",
    config: {},
    participants: [],
    rounds: [],
    status: "idle",
    activeRoundId: "",
    createdAt: "",
    updatedAt: "",
    availableModes: [],
    availablePurposes: [],
    ...overrides,
  };
}

describe("chatGroupTeamLinkageModel", () => {
  it("buildLinkedTeamRoomIds prefers flat linkedChatRoomId and nested linkedChatRoom.roomId", () => {
    const ids = buildLinkedTeamRoomIds([
      makeTeam({ teamId: "t1", linkedChatRoomId: "room-a" }),
      makeTeam({ teamId: "t2", linkedChatRoom: { roomId: "room-b" } as Team["linkedChatRoom"] }),
      makeTeam({ teamId: "t3", linkedChatRoomId: "", linkedChatRoom: undefined }),
    ]);
    expect([...ids]).toEqual(["room-a", "room-b"]);
  });

  it("resolveActiveGroupTeam matches config.teamId before linked room id", () => {
    const teams = [
      makeTeam({ teamId: "team-owned", linkedChatRoomId: "room-other" }),
      makeTeam({ teamId: "team-linked", linkedChatRoomId: "room-1" }),
    ];
    expect(resolveActiveGroupTeam(
      teams,
      makeRoom({ roomId: "room-1", config: { teamId: "team-owned" } }),
      "room-1",
    )?.teamId).toBe("team-owned");
    expect(resolveActiveGroupTeam(
      teams,
      makeRoom({ roomId: "room-1", config: {} }),
      "room-1",
    )?.teamId).toBe("team-linked");
    expect(resolveActiveGroupTeam(teams, makeRoom({ roomId: "room-missing" }), "room-missing")).toBeNull();
  });
});
