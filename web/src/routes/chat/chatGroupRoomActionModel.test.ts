import { describe, expect, it } from "vitest";

import type { ChatRoomDetail } from "../../api/types";
import {
  buildChatGroupManageChanged,
  buildChatGroupRoomActionDisabledFlags,
  deriveChatGroupRoundState,
} from "./chatGroupRoomActionModel";

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

describe("deriveChatGroupRoundState", () => {
  it("treats running and stopping as an active round", () => {
    expect(deriveChatGroupRoundState(makeRoom({ status: "Running" }))).toEqual({
      groupRoundRunning: true,
      groupRoundStopping: false,
      groupRoundActive: true,
    });
    expect(deriveChatGroupRoundState(makeRoom({ status: "stopping" }))).toEqual({
      groupRoundRunning: false,
      groupRoundStopping: true,
      groupRoundActive: true,
    });
    expect(deriveChatGroupRoundState(makeRoom({ status: "idle" })).groupRoundActive).toBe(false);
    expect(deriveChatGroupRoundState(null).groupRoundActive).toBe(false);
  });
});

describe("buildChatGroupManageChanged", () => {
  it("is false until a standard room exists", () => {
    expect(buildChatGroupManageChanged({
      standardGroupRoomActive: false,
      activeGroupRoom: makeRoom(),
      groupManageTitleDraft: "改名",
      groupManageModeDraft: "round_robin",
      groupManagePurposeDraft: "discussion",
      groupManageSessionIds: ["s1", "s2"],
      activeGroupParticipantSessionIds: new Set(["s1", "s2"]),
    })).toBe(false);
  });

  it("detects title, mode, purpose, and membership diffs", () => {
    const room = makeRoom({ title: "群聊", mode: "round_robin", purpose: "discussion" });
    const base = {
      standardGroupRoomActive: true,
      activeGroupRoom: room,
      groupManageTitleDraft: "群聊",
      groupManageModeDraft: "round_robin",
      groupManagePurposeDraft: "discussion",
      groupManageSessionIds: ["s1", "s2"],
      activeGroupParticipantSessionIds: new Set(["s1", "s2"]),
    };
    expect(buildChatGroupManageChanged(base)).toBe(false);
    expect(buildChatGroupManageChanged({ ...base, groupManageTitleDraft: " 新标题 " })).toBe(true);
    expect(buildChatGroupManageChanged({ ...base, groupManageModeDraft: "moderated" })).toBe(true);
    expect(buildChatGroupManageChanged({ ...base, groupManagePurposeDraft: "meeting" })).toBe(true);
    expect(buildChatGroupManageChanged({ ...base, groupManageSessionIds: ["s1"] })).toBe(true);
    expect(buildChatGroupManageChanged({
      ...base,
      groupManageSessionIds: ["s1", "s3"],
    })).toBe(true);
  });
});

describe("buildChatGroupRoomActionDisabledFlags", () => {
  const room = makeRoom({
    rounds: [{
      roundId: "r1",
      roomId: "room-1",
      topic: "t",
      mode: "round_robin",
      purpose: "discussion",
      config: {},
      status: "finished",
      speakerOrder: [],
      messages: [],
      summary: "",
      startedAt: "",
      updatedAt: "",
      finishedAt: "",
    }],
  });

  const ready = {
    standardGroupRoomActive: true,
    activeGroupRoom: room,
    activeGroupTeamOwned: false,
    groupRoundActive: false,
    groupRoundRunning: false,
    groupManageTitleDraft: "群聊",
    groupManageSessionIds: ["s1", "s2"],
    groupManageModeDraft: "round_robin",
    groupManagePurposeDraft: "discussion",
    updateGroupRoomPending: false,
    deleteGroupRoomPending: false,
    resetGroupRoomPending: false,
    stopGroupRoundPending: false,
  };

  it("enables manage/delete/reset on a ready standard room", () => {
    expect(buildChatGroupRoomActionDisabledFlags(ready)).toEqual({
      groupManageDisabled: false,
      groupDeleteDisabled: false,
      groupResetDisabled: false,
      groupStopDisabled: true,
    });
  });

  it("disables manage when title is blank or fewer than two sessions", () => {
    expect(buildChatGroupRoomActionDisabledFlags({
      ...ready,
      groupManageTitleDraft: "  ",
    }).groupManageDisabled).toBe(true);
    expect(buildChatGroupRoomActionDisabledFlags({
      ...ready,
      groupManageSessionIds: ["s1"],
    }).groupManageDisabled).toBe(true);
  });

  it("locks management while a team owns the room or a round is active", () => {
    expect(buildChatGroupRoomActionDisabledFlags({
      ...ready,
      activeGroupTeamOwned: true,
    })).toMatchObject({
      groupManageDisabled: true,
      groupDeleteDisabled: true,
    });
    expect(buildChatGroupRoomActionDisabledFlags({
      ...ready,
      groupRoundActive: true,
      groupRoundRunning: true,
    })).toMatchObject({
      groupManageDisabled: true,
      groupDeleteDisabled: true,
      groupResetDisabled: true,
      groupStopDisabled: false,
    });
  });

  it("disables reset when there are no rounds", () => {
    expect(buildChatGroupRoomActionDisabledFlags({
      ...ready,
      activeGroupRoom: makeRoom({ rounds: [] }),
    }).groupResetDisabled).toBe(true);
  });
});
