import { describe, expect, it } from "vitest";

import type { ChatRoomDetail, ChatRoomParticipant, ChatRoomRound } from "../../api/types";
import {
  deriveAvailableGroupParticipants,
  latestFormalChatRoomRound,
} from "./useChatGroupRoomChromeModel";

function participant(
  participantId: string,
  overrides: Partial<ChatRoomParticipant> = {},
): ChatRoomParticipant {
  return {
    participantId,
    kind: "session_agent",
    agentId: `agent-${participantId}`,
    sessionId: `session-${participantId}`,
    title: participantId,
    enabled: true,
    status: "ready",
    ...overrides,
  };
}

function round(overrides: Partial<ChatRoomRound> = {}): ChatRoomRound {
  return {
    roundId: "round-1",
    roomId: "room-1",
    topic: "议题",
    mode: "round_robin",
    purpose: "discussion",
    config: {},
    status: "completed",
    speakerOrder: [],
    messages: [],
    summary: "",
    startedAt: "",
    updatedAt: "",
    finishedAt: "",
    ...overrides,
  };
}

function roomWithRounds(rounds: ChatRoomRound[]): ChatRoomDetail {
  return { rounds } as unknown as ChatRoomDetail;
}

describe("deriveAvailableGroupParticipants", () => {
  it("derives the visible roster from the latest formal round speaker order", () => {
    const roster = [
      participant("p1"),
      participant("p2"),
      participant("p3"),
      participant("p4", { agentMissing: true }),
      participant("p5", { enabled: false }),
    ];

    const visible = deriveAvailableGroupParticipants(roster, [
      "p3",
      "unknown",
      "p3",
      "p1",
      "p4",
      "p5",
    ]);

    expect(visible.map((item) => item.participantId)).toEqual(["p3", "p1"]);
  });

  it("keeps the complete available roster when no formal round speaker order exists", () => {
    const roster = [
      participant("p1"),
      participant("p2"),
      participant("p3", { agentMissing: true }),
    ];

    const ordinaryRound = round({ speakerOrder: ["p2"] });
    const latestFormalRound = latestFormalChatRoomRound(roomWithRounds([ordinaryRound]));

    expect(latestFormalRound).toBeNull();
    expect(deriveAvailableGroupParticipants(roster, latestFormalRound?.speakerOrder)).toEqual([
      roster[0],
      roster[1],
    ]);
  });

  it("restores the complete roster when a newer ordinary round replaces a formal round", () => {
    const roster = [participant("p1"), participant("p2"), participant("p3")];
    const formalRound = round({
      speakerOrder: ["p3", "p1"],
      config: {
        meetingRoundId: "meeting-1",
        meetingType: "hypothesis_review",
      },
    });
    const ordinaryRound = round({
      roundId: "round-2",
      speakerOrder: ["p2"],
    });

    const latestFormalRound = latestFormalChatRoomRound(
      roomWithRounds([formalRound, ordinaryRound]),
    );

    expect(latestFormalRound).toBeNull();
    expect(deriveAvailableGroupParticipants(roster, latestFormalRound?.speakerOrder).map(
      (item) => item.participantId,
    )).toEqual(["p1", "p2", "p3"]);
  });
});
