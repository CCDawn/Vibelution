/** @vitest-environment happy-dom */
import { describe, expect, it } from "vitest";

import type {
  CandidateEvidenceEntry,
  MeetingSourceMessage,
} from "../../../api/types/hypothesisFirst";
import {
  collectMeetingRoundIds,
  parseLeaderboardEvidenceRef,
  sourceMessageForRef,
  sourceMessageSpeaker,
  trailEntryForRef,
} from "./leaderboardEvidenceRef";

describe("parseLeaderboardEvidenceRef", () => {
  it("parses the three-segment source-message backlink format", () => {
    expect(parseLeaderboardEvidenceRef("room-1/round-11/msg-101")).toEqual({
      kind: "source_message",
      roomId: "room-1",
      roundId: "round-11",
      messageId: "msg-101",
    });
  });

  it("trims surrounding whitespace but keeps interior segments verbatim", () => {
    expect(parseLeaderboardEvidenceRef("  room-1/round-11/msg-101  ")).toEqual({
      kind: "source_message",
      roomId: "room-1",
      roundId: "round-11",
      messageId: "msg-101",
    });
  });

  it("fails closed to text for lineage labels and other shapes", () => {
    expect(parseLeaderboardEvidenceRef("round:cand-7")).toEqual({
      kind: "text",
      text: "round:cand-7",
    });
    expect(parseLeaderboardEvidenceRef("baseline-3")).toEqual({
      kind: "text",
      text: "baseline-3",
    });
  });

  it("fails closed for wrong segment counts and empty segments", () => {
    expect(parseLeaderboardEvidenceRef("room-1/round-11")).toEqual({
      kind: "text",
      text: "room-1/round-11",
    });
    expect(parseLeaderboardEvidenceRef("room-1/round-11/msg-101/extra")).toEqual({
      kind: "text",
      text: "room-1/round-11/msg-101/extra",
    });
    expect(parseLeaderboardEvidenceRef("room-1//msg-101")).toEqual({
      kind: "text",
      text: "room-1//msg-101",
    });
    expect(parseLeaderboardEvidenceRef(" / / ")).toEqual({ kind: "text", text: "/ /" });
  });

  it("never throws for empty or non-string input", () => {
    expect(parseLeaderboardEvidenceRef("")).toEqual({ kind: "text", text: "" });
    expect(parseLeaderboardEvidenceRef(undefined as unknown as string)).toEqual({
      kind: "text",
      text: "",
    });
  });
});

describe("trailEntryForRef", () => {
  const entry: CandidateEvidenceEntry = {
    meetingRoundId: "meeting-1",
    meetingLabel: "证据评审会 1",
    messageId: "msg-101",
    speaker: "A014 · 科研协调",
    excerpt: "……摘录……",
    createdAt: "2026-08-03T01:00:00.000Z",
  };

  it("matches a source-message ref by messageId", () => {
    const ref = parseLeaderboardEvidenceRef("room-1/round-11/msg-101");
    expect(trailEntryForRef([entry], ref)).toBe(entry);
  });

  it("returns null on miss and for text refs", () => {
    const ref = parseLeaderboardEvidenceRef("room-1/round-11/msg-other");
    expect(trailEntryForRef([entry], ref)).toBeNull();
    expect(trailEntryForRef([], parseLeaderboardEvidenceRef("room-1/round-11/msg-101"))).toBeNull();
    expect(trailEntryForRef([entry], parseLeaderboardEvidenceRef("round:cand-7"))).toBeNull();
  });
});

describe("sourceMessageForRef", () => {
  const message: MeetingSourceMessage = {
    messageId: "msg-101",
    roomId: "room-1",
    roundId: "round-11",
    speakerTitle: "A014 · 科研协调",
    content: "梯度稀疏约束更稳。",
    createdAt: "2026-08-03T01:00:00.000Z",
  };

  it("matches on messageId when room/round agree or are absent", () => {
    const ref = parseLeaderboardEvidenceRef("room-1/round-11/msg-101");
    expect(sourceMessageForRef([message], ref)).toBe(message);
    const bare = { ...message, roomId: undefined, roundId: undefined };
    expect(sourceMessageForRef([bare], ref)).toBe(bare);
  });

  it("rejects messages whose roomId/roundId disagree with the ref", () => {
    const ref = parseLeaderboardEvidenceRef("room-1/round-11/msg-101");
    expect(
      sourceMessageForRef([{ ...message, roomId: "room-2" }], ref),
    ).toBeNull();
    expect(
      sourceMessageForRef([{ ...message, roundId: "round-12" }], ref),
    ).toBeNull();
  });

  it("returns null on miss, junk rows and text refs", () => {
    const ref = parseLeaderboardEvidenceRef("room-1/round-11/msg-other");
    expect(sourceMessageForRef([message], ref)).toBeNull();
    expect(sourceMessageForRef([null as unknown as MeetingSourceMessage], ref)).toBeNull();
    expect(sourceMessageForRef([message], parseLeaderboardEvidenceRef("round:cand-7"))).toBeNull();
  });
});

describe("sourceMessageSpeaker", () => {
  it("prefers speakerTitle then agentId then role", () => {
    expect(sourceMessageSpeaker({ speakerTitle: "A014 · 科研协调" })).toBe("A014 · 科研协调");
    expect(sourceMessageSpeaker({ agentId: "agent-a" })).toBe("agent-a");
    expect(sourceMessageSpeaker({ role: "reviewer" })).toBe("reviewer");
    expect(sourceMessageSpeaker({})).toBe("");
  });
});

describe("collectMeetingRoundIds", () => {
  it("keeps only meeting_round refs with non-empty ids", () => {
    expect(
      collectMeetingRoundIds([
        { kind: "meeting_round", id: "meeting-1" },
        { kind: "meeting_digest", id: "digest-1" },
        { kind: "meeting_round", id: "  " },
        { kind: "meeting_round" },
        "junk",
        null,
      ]),
    ).toEqual(["meeting-1"]);
  });

  it("fails closed for non-array input", () => {
    expect(collectMeetingRoundIds(undefined)).toEqual([]);
    expect(collectMeetingRoundIds("meeting-1")).toEqual([]);
  });
});
