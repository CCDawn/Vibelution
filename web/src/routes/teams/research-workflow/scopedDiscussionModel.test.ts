import { describe, expect, it } from "vitest";

import {
  buildScopedDiscussionModel,
  SCOPED_DISCUSSION_REASONS,
  type ActiveDiscussionAnchor,
  type ScopedDiscussionScope,
} from "./scopedDiscussionModel";

const scope: ScopedDiscussionScope = {
  version: 1,
  kind: "candidate_review",
  teamId: "research-team",
  researchProjectId: "challenge-sci-096",
  workflowRunId: "run-1",
  workflowNodeId: "hypothesis-review",
  questionId: "SCI-096",
  selectionId: "selection-1",
  candidateId: "h1",
};

function anchor(overrides: Partial<ActiveDiscussionAnchor> = {}): ActiveDiscussionAnchor {
  return {
    scope,
    scopeHash: "scope-hash",
    roomId: "room-h1",
    meetingRoundId: "meeting-h1",
    questionId: "SCI-096",
    selectionId: "selection-1",
    candidateId: "h1",
    deepLink: "/chat?room=room-h1",
    status: "ready",
    degradedReason: "",
    ...overrides,
  };
}

describe("scoped discussion model", () => {
  it("creates only the active room query and deep link", () => {
    const model = buildScopedDiscussionModel(anchor());

    expect(model.status).toBe("ready");
    expect(model.query).toEqual({ kind: "room", room: "room-h1" });
    expect(model.search).toBe("?room=room-h1");
    expect(model.deepLink).toBe("/chat?room=room-h1");
    expect(model.selectedRoundId).toBe("");
  });

  it("does not create a navigation target for a missing or degraded anchor", () => {
    expect(buildScopedDiscussionModel(null).degradedReason).toBe(
      SCOPED_DISCUSSION_REASONS.noAnchor,
    );
    const degraded = buildScopedDiscussionModel(
      anchor({ status: "degraded", degradedReason: "room_missing", deepLink: "" }),
    );
    expect(degraded.status).toBe("degraded");
    expect(degraded.query).toBeNull();
    expect(degraded.deepLink).toBe("");
  });

  it("rejects a room whose scope is for a sibling candidate", () => {
    const model = buildScopedDiscussionModel({
      anchor: anchor(),
      room: {
        roomId: "room-h1",
        status: "active",
        config: {
          discussionScope: { ...scope, candidateId: "h2" },
          scopeHash: "scope-hash",
        },
      },
    });

    expect(model.status).toBe("degraded");
    expect(model.degradedReason).toBe(SCOPED_DISCUSSION_REASONS.roomMismatch);
  });

  it("selects one bound room round and never merges siblings", () => {
    const model = buildScopedDiscussionModel({
      anchor: anchor(),
      room: {
        roomId: "room-h1",
        status: "active",
        config: { discussionScope: scope, scopeHash: "scope-hash" },
        rounds: [
          { roundId: "sibling-round", meetingRoundId: "meeting-h2" },
          { roundId: "active-round", meetingRoundId: "meeting-h1" },
        ],
      },
    });

    expect(model.status).toBe("ready");
    expect(model.selectedRoundId).toBe("active-round");
  });
});
