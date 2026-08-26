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
    expect(model.returnTo).toBe(
      "/teams?teamId=research-team&researchView=workflow&workflowId=challenge-cup-research&questionId=SCI-096&runId=run-1&node=hypothesis-review&panel=node",
    );
    expect(model.returnLabel).toBe("返回科研流程");
    expect(model.deepLink).toBe(
      "/chat?room=room-h1&returnTo=%2Fteams%3FteamId%3Dresearch-team%26researchView%3Dworkflow%26workflowId%3Dchallenge-cup-research%26questionId%3DSCI-096%26runId%3Drun-1%26node%3Dhypothesis-review%26panel%3Dnode&returnLabel=%E8%BF%94%E5%9B%9E%E7%A7%91%E7%A0%94%E6%B5%81%E7%A8%8B",
    );
    expect(model.selectedRoundId).toBe("");
  });

  it("rebuilds the canonical seven-field workflow return route from a legacy server route", () => {
    const model = buildScopedDiscussionModel({
      anchor: anchor({
        returnTo: "/teams?teamId=research-team&researchView=workflow&runId=run-1&node=hypothesis-review",
        deepLink: "/chat?room=room-h1&returnTo=%2Fteams%3FteamId%3Dresearch-team%26researchView%3Dworkflow%26runId%3Drun-1%26node%3Dhypothesis-review",
      }),
    });

    expect(model.status).toBe("ready");
    expect(new URLSearchParams(model.returnTo.split("?", 2)[1])).toEqual(
      new URLSearchParams({
        teamId: "research-team",
        researchView: "workflow",
        workflowId: "challenge-cup-research",
        questionId: "SCI-096",
        runId: "run-1",
        node: "hypothesis-review",
        panel: "node",
      }),
    );
    expect(new URL(model.deepLink, "http://vibelution.local").searchParams.get("returnTo"))
      .toBe(model.returnTo);
  });

  it("rejects an external deep link or return route", () => {
    const externalDeepLink = buildScopedDiscussionModel(
      anchor({ deepLink: "https://evil.example/chat?room=room-h1" }),
    );
    expect(externalDeepLink.status).toBe("degraded");
    expect(externalDeepLink.degradedReason).toBe(SCOPED_DISCUSSION_REASONS.invalidAnchor);

    const externalReturn = buildScopedDiscussionModel(
      anchor({ returnTo: "https://evil.example/steal" }),
    );
    expect(externalReturn.status).toBe("degraded");
    expect(externalReturn.degradedReason).toBe(SCOPED_DISCUSSION_REASONS.invalidAnchor);
  });

  it("rejects a return route bound to another workflow scope", () => {
    const model = buildScopedDiscussionModel({
      anchor: anchor({
        returnTo: "/teams?teamId=research-team&researchView=workflow&workflowId=challenge-cup-research&questionId=SCI-097&runId=run-1&node=hypothesis-review&panel=node",
      }),
    });

    expect(model.status).toBe("degraded");
    expect(model.degradedReason).toBe(SCOPED_DISCUSSION_REASONS.invalidAnchor);
    expect(model.deepLink).toBe("");
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

  it("accepts a preformal candidate review without inventing a run id", () => {
    const preformalScope = {
      version: 1 as const,
      kind: "preformal_candidate_review" as const,
      teamId: "research-team",
      questionId: "SCI-003",
      selectionId: "selection-1",
      candidateId: "h1",
      meetingRoundId: "meeting-h1",
      roomId: "room-h1",
    };
    const model = buildScopedDiscussionModel({
      anchor: {
        scope: preformalScope,
        scopeHash: "preformal-hash",
        roomId: "room-h1",
        meetingRoundId: "meeting-h1",
        questionId: "SCI-003",
        selectionId: "selection-1",
        candidateId: "h1",
        deepLink: "/chat?room=room-h1",
        status: "ready",
        degradedReason: "",
      },
    });

    expect(model.status).toBe("ready");
    expect(model.returnTo).toBe(
      "/teams?teamId=research-team&researchView=workflow&workflowId=challenge-cup-research&questionId=SCI-003&node=hf_review&panel=node",
    );
    expect(model.deepLink).toContain("returnTo=%2Fteams%3FteamId%3Dresearch-team");
    expect(model.deepLink).not.toContain("runId");
  });

  it("rejects a preformal return route that attempts to add a formal run", () => {
    const model = buildScopedDiscussionModel({
      anchor: {
        scope: {
          version: 1,
          kind: "preformal_candidate_review",
          teamId: "research-team",
          questionId: "SCI-003",
          selectionId: "selection-1",
          candidateId: "h1",
          meetingRoundId: "meeting-h1",
          roomId: "room-h1",
        },
        scopeHash: "preformal-hash",
        roomId: "room-h1",
        meetingRoundId: "meeting-h1",
        questionId: "SCI-003",
        selectionId: "selection-1",
        candidateId: "h1",
        deepLink: "/chat?room=room-h1",
        returnTo:
          "/teams?teamId=research-team&researchView=workflow&workflowId=challenge-cup-research&questionId=SCI-003&runId=fake&node=hf_review&panel=node",
        status: "ready",
        degradedReason: "",
      },
    });

    expect(model.status).toBe("degraded");
    expect(model.degradedReason).toBe(SCOPED_DISCUSSION_REASONS.invalidAnchor);
  });

  it("rejects a preformal anchor whose top-level room differs from its scope", () => {
    const model = buildScopedDiscussionModel({
      anchor: {
        scope: {
          version: 1,
          kind: "preformal_candidate_review",
          teamId: "research-team",
          questionId: "SCI-003",
          selectionId: "selection-1",
          candidateId: "h1",
          meetingRoundId: "meeting-h1",
          roomId: "room-h1",
        },
        scopeHash: "preformal-hash",
        roomId: "room-sibling",
        meetingRoundId: "meeting-h1",
        questionId: "SCI-003",
        selectionId: "selection-1",
        candidateId: "h1",
        deepLink: "/chat?room=room-sibling",
        status: "ready",
        degradedReason: "",
      },
    });

    expect(model.status).toBe("degraded");
    expect(model.degradedReason).toBe(SCOPED_DISCUSSION_REASONS.invalidAnchor);
  });
});
