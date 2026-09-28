import { describe, expect, it } from "vitest";

import type { ConversationSummary, SessionSummary } from "../api/types";
import {
  areConversationSummariesEquivalent,
  areIndexEntryValuesEquivalent,
  areSessionSummariesEquivalent,
  conversationSummaryIdentityKey,
  sessionSummaryIdentityKey,
  stabilizeConversationSummaries,
  stabilizeIndexEntries,
  stabilizeSessionSummaries,
} from "./sessionIndexReferenceStabilization";

function fullSession(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "用户会话",
    agentId: "agent-1",
    agentCode: "alpha",
    agentDisplayName: "Alpha",
    agentAvatarImagePath: "/avatars/alpha.png",
    agentAvatarImageUrl: "https://example.test/alpha.png",
    agentPrimaryMode: "chat",
    agentRoleKey: "engineer",
    agentPromptTemplateId: "tpl-1",
    agentPromptSnapshot: {
      schemaVersion: 1,
      promptTemplateId: "tpl-1",
      contentHash: "hash-1",
      corePrompts: [{ name: "COMMON", sourcePath: "core/COMMON.md", contentHash: "c1", contentLength: 10 }],
      promptAssembly: { schemaVersion: 1, segments: [{ key: "k", contentHash: "s1" }] },
    },
    lastPromptAssembly: { schemaVersion: 1, stablePrefixHash: "p1", segments: [{ key: "k", contentHash: "s1" }] },
    experimentBinding: null,
    dialogueModelId: "model-1",
    reasoningEffort: "medium",
    agentInboxPendingCount: 2,
    agentPrimaryDirectSessionId: "session-1",
    agentDirectSessionMismatch: false,
    workspacePath: "C:/ws",
    agentWorkspacePath: "C:/ws",
    agentMissingId: "",
    agentMissing: false,
    agentStatusCode: "idle",
    agentStatusMessage: "",
    status: "ready",
    taskSummary: "摘要",
    lastActive: "2026-06-09T08:00:00.000Z",
    updatedAt: "2026-06-09T08:00:00.000Z",
    createdAt: "2026-06-01T08:00:00.000Z",
    currentPhase: "ready",
    hiddenFromIndex: false,
    archiveState: { status: "", source: "", agentId: "", archivedAt: "" },
    readOnly: false,
    lastTurnStatus: "success",
    lastTurnTerminalTurnId: "turn-1",
    terminalReason: "",
    sessionKind: "main",
    sessionRole: "primary",
    parentSessionId: "",
    rootSessionId: "session-1",
    childSessionIds: ["session-2"],
    activeChildSessionId: "",
    childStatus: "",
    taskTitle: "任务",
    resultCard: { status: "ok", title: "结果", summary: "结果摘要", updatedAt: "2026-06-09T07:00:00.000Z" },
    sourceRef: {
      kind: "session",
      id: "session-1",
      owner: "user",
      factAuthority: true,
      canonicalEditRoute: "session",
      canonicalMutationApi: "session.update",
      projectionCanWrite: false,
      allowedProjectionActions: [],
      sourceAuthorityVersion: 1,
    },
    projectionEdit: {
      canWrite: true,
      mode: "direct",
      reason: "",
      sourceOwner: "user",
      canonicalEditRoute: "session",
      canonicalMutationApi: "session.update",
      sourceAuthorityVersion: 1,
    },
    agentSourceRef: null,
    conversationIndexVisibility: "user_visible",
    conversationIndexKind: "user_chat",
    conversationIndexErrors: [],
    teamId: "",
    teamName: "",
    ...overrides,
  };
}

function fullConversation(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    teamId: "",
    teamName: "",
    conversationId: "session-1",
    type: "direct_agent",
    title: "用户会话",
    agentId: "agent-1",
    agentCode: "alpha",
    agentDisplayName: "Alpha",
    agentAvatarImagePath: "/avatars/alpha.png",
    agentAvatarImageUrl: "https://example.test/alpha.png",
    directSessionId: "session-1",
    roomId: "",
    status: "ready",
    summary: "摘要",
    updatedAt: "2026-06-09T08:00:00.000Z",
    workspacePath: "C:/ws",
    participantCount: 1,
    mode: "chat",
    agentPrimaryMode: "chat",
    agentRoleKey: "engineer",
    agentPromptTemplateId: "tpl-1",
    dialogueModelId: "model-1",
    agentInboxPendingCount: 2,
    conversationIndexVisibility: "user_visible",
    conversationIndexKind: "user_chat",
    conversationIndexErrors: [],
    agentMissing: false,
    agentStatusCode: "idle",
    agentStatusMessage: "",
    sourceRef: {
      kind: "session",
      id: "session-1",
      owner: "user",
      factAuthority: true,
      canonicalEditRoute: "session",
      canonicalMutationApi: "session.update",
      projectionCanWrite: false,
      allowedProjectionActions: [],
      sourceAuthorityVersion: 1,
    },
    projectionEdit: {
      canWrite: true,
      mode: "direct",
      reason: "",
      sourceOwner: "user",
      canonicalEditRoute: "session",
      canonicalMutationApi: "session.update",
      sourceAuthorityVersion: 1,
    },
    agentSourceRef: null,
    ...overrides,
  };
}

describe("areIndexEntryValuesEquivalent", () => {
  it("treats content-equal objects as equivalent regardless of key order", () => {
    expect(areIndexEntryValuesEquivalent({ a: 1, b: { c: 2, d: 3 } }, { b: { d: 3, c: 2 }, a: 1 })).toBe(true);
  });

  it("treats undefined-valued keys as absent on both sides", () => {
    expect(areIndexEntryValuesEquivalent({ a: 1, b: undefined }, { a: 1 })).toBe(true);
  });

  it("never equates null with undefined or a missing key", () => {
    expect(areIndexEntryValuesEquivalent({ a: null }, { a: undefined })).toBe(false);
    expect(areIndexEntryValuesEquivalent({ a: null }, {})).toBe(false);
  });

  it("detects nested key, array element, and length differences", () => {
    expect(areIndexEntryValuesEquivalent({ a: { b: 1 } }, { a: { b: 2 } })).toBe(false);
    expect(areIndexEntryValuesEquivalent({ a: [1, 2] }, { a: [1, 3] })).toBe(false);
    expect(areIndexEntryValuesEquivalent({ a: [1] }, { a: [1, 2] })).toBe(false);
    expect(areIndexEntryValuesEquivalent({ a: 1 }, { a: 1, extra: 2 })).toBe(false);
  });
});

describe("areSessionSummariesEquivalent field coverage", () => {
  it("accepts an identical copy", () => {
    expect(areSessionSummariesEquivalent(fullSession(), fullSession())).toBe(true);
  });

  it("rejects a change in any compared shallow field", () => {
    // Full shallow field set of SessionSummary (identity/display/status/phase/
    // hierarchy/index-classification counters and timestamps).
    const shallowFields: Array<keyof SessionSummary> = [
      "id",
      "title",
      "agentId",
      "agentCode",
      "agentDisplayName",
      "agentAvatarImagePath",
      "agentAvatarImageUrl",
      "agentPrimaryMode",
      "agentRoleKey",
      "agentPromptTemplateId",
      "dialogueModelId",
      "reasoningEffort",
      "agentInboxPendingCount",
      "agentPrimaryDirectSessionId",
      "agentDirectSessionMismatch",
      "workspacePath",
      "agentWorkspacePath",
      "agentMissingId",
      "agentMissing",
      "agentStatusCode",
      "agentStatusMessage",
      "status",
      "taskSummary",
      "lastActive",
      "updatedAt",
      "createdAt",
      "currentPhase",
      "hiddenFromIndex",
      "readOnly",
      "lastTurnStatus",
      "lastTurnTerminalTurnId",
      "terminalReason",
      "sessionKind",
      "sessionRole",
      "parentSessionId",
      "rootSessionId",
      "activeChildSessionId",
      "childStatus",
      "taskTitle",
      "conversationIndexVisibility",
      "conversationIndexKind",
      "teamId",
      "teamName",
    ];
    for (const field of shallowFields) {
      const changed = fullSession({ [field]: "changed-value" } as Partial<SessionSummary>);
      expect(areSessionSummariesEquivalent(fullSession(), changed), `field: ${String(field)}`).toBe(false);
    }
  });

  it("rejects changes nested inside composed objects", () => {
    const cases: Array<[string, SessionSummary]> = [
      ["childSessionIds element", fullSession({ childSessionIds: ["session-3"] })],
      ["conversationIndexErrors element", fullSession({ conversationIndexErrors: ["missing_kind"] })],
      ["archiveState.status", fullSession({ archiveState: { status: "archived" } })],
      ["archiveState.archivedAt", fullSession({ archiveState: { archivedAt: "2026-06-10T00:00:00.000Z" } })],
      ["resultCard.summary", fullSession({ resultCard: { summary: "新结果" } })],
      ["resultCard.status", fullSession({ resultCard: { status: "failed" } })],
      ["agentPromptSnapshot.contentHash", fullSession({ agentPromptSnapshot: { contentHash: "hash-2" } })],
      [
        "agentPromptSnapshot.corePrompts element",
        fullSession({ agentPromptSnapshot: { corePrompts: [{ contentHash: "c2" }] } }),
      ],
      ["lastPromptAssembly.segments element", fullSession({ lastPromptAssembly: { segments: [{ contentHash: "s2" }] } })],
      ["sourceRef.id", fullSession({ sourceRef: { kind: "session", id: "other", owner: "user", factAuthority: true, canonicalEditRoute: "", canonicalMutationApi: "", projectionCanWrite: false, allowedProjectionActions: [], sourceAuthorityVersion: 1 } })],
      ["projectionEdit.canWrite", fullSession({ projectionEdit: { canWrite: false, mode: "direct", reason: "", sourceOwner: "user", canonicalEditRoute: "", canonicalMutationApi: "", sourceAuthorityVersion: 1 } })],
      ["experimentBinding teamId", fullSession({ experimentBinding: { teamId: "t1", researchProjectId: "p", experimentName: "e", agentId: "a", roleKey: "r", roleLabel: "l", attempt: 1, retryOfSessionId: "", createdFromTaskId: "", createdAt: "" } })],
    ];
    for (const [label, changed] of cases) {
      expect(areSessionSummariesEquivalent(fullSession(), changed), label).toBe(false);
    }
  });

  it("rotates on activity timestamps even though rows rarely render them", () => {
    // lastActive / updatedAt tick on every stream apply; they are compared so
    // the row reference rotates (conservative). This asserts the conservative
    // behavior stays intentional instead of accidentally reusing stale rows.
    expect(areSessionSummariesEquivalent(fullSession(), fullSession({ lastActive: "2026-06-09T08:00:01.000Z" }))).toBe(false);
    expect(areSessionSummariesEquivalent(fullSession(), fullSession({ updatedAt: "2026-06-09T08:00:01.000Z" }))).toBe(false);
  });
});

describe("areConversationSummariesEquivalent field coverage", () => {
  it("accepts an identical copy and rejects shallow or nested changes", () => {
    expect(areConversationSummariesEquivalent(fullConversation(), fullConversation())).toBe(true);
    const shallowFields: Array<keyof ConversationSummary> = [
      "teamId",
      "teamName",
      "conversationId",
      "type",
      "title",
      "agentId",
      "agentCode",
      "agentDisplayName",
      "agentAvatarImagePath",
      "agentAvatarImageUrl",
      "directSessionId",
      "roomId",
      "status",
      "summary",
      "updatedAt",
      "workspacePath",
      "participantCount",
      "mode",
      "agentPrimaryMode",
      "agentRoleKey",
      "agentPromptTemplateId",
      "dialogueModelId",
      "agentInboxPendingCount",
      "conversationIndexVisibility",
      "conversationIndexKind",
      "agentMissing",
      "agentStatusCode",
      "agentStatusMessage",
    ];
    for (const field of shallowFields) {
      const changed = fullConversation({ [field]: "changed-value" } as Partial<ConversationSummary>);
      expect(areConversationSummariesEquivalent(fullConversation(), changed), `field: ${String(field)}`).toBe(false);
    }
    expect(
      areConversationSummariesEquivalent(
        fullConversation(),
        fullConversation({ conversationIndexErrors: ["missing_kind"] }),
      ),
    ).toBe(false);
    expect(
      areConversationSummariesEquivalent(
        fullConversation(),
        fullConversation({ sourceRef: { kind: "session", id: "other", owner: "user", factAuthority: true, canonicalEditRoute: "", canonicalMutationApi: "", projectionCanWrite: false, allowedProjectionActions: [], sourceAuthorityVersion: 1 } }),
      ),
    ).toBe(false);
    expect(
      areConversationSummariesEquivalent(
        fullConversation(),
        fullConversation({ projectionEdit: { canWrite: false, mode: "direct", reason: "", sourceOwner: "user", canonicalEditRoute: "", canonicalMutationApi: "", sourceAuthorityVersion: 1 } }),
      ),
    ).toBe(false);
  });
});

describe("stabilizeSessionSummaries", () => {
  it("returns the next array as-is when there is nothing to compare against", () => {
    const next = [fullSession()];
    expect(stabilizeSessionSummaries(undefined, next)).toBe(next);
    expect(stabilizeSessionSummaries([], next)).toBe(next);
  });

  it("reuses the previous array reference when content and order are identical", () => {
    const previous = [fullSession({ id: "a" }), fullSession({ id: "b" })];
    const next = [fullSession({ id: "a" }), fullSession({ id: "b" })];
    const stabilized = stabilizeSessionSummaries(previous, next);
    expect(stabilized).toBe(previous);
  });

  it("reuses previous entry references for equivalent content in a new array", () => {
    const previous = [fullSession({ id: "a" }), fullSession({ id: "b" })];
    const next = [fullSession({ id: "a" }), fullSession({ id: "b" })];
    const stabilized = stabilizeSessionSummaries(previous, next);
    expect(stabilized).not.toBe(next);
    expect(stabilized[0]).toBe(previous[0]);
    expect(stabilized[1]).toBe(previous[1]);
  });

  it("rotates only the changed entry and keeps sibling references", () => {
    const previous = [fullSession({ id: "a" }), fullSession({ id: "b" }), fullSession({ id: "c" })];
    const changed = fullSession({ id: "b", title: "改名" });
    const stabilized = stabilizeSessionSummaries(previous, [previous[0], changed, previous[2]]);
    expect(stabilized).not.toBe(previous);
    expect(stabilized[0]).toBe(previous[0]);
    expect(stabilized[1]).toBe(changed);
    expect(stabilized[2]).toBe(previous[2]);
  });

  it("propagates nested field changes into a new entry reference", () => {
    const previous = [fullSession({ id: "a" })];
    const changed = fullSession({ id: "a", resultCard: { summary: "新结果" } });
    const stabilized = stabilizeSessionSummaries(previous, [changed]);
    expect(stabilized[0]).toBe(changed);
    expect(stabilized[0]).not.toBe(previous[0]);
  });

  it("detects changes in key-order-shuffled equivalents", () => {
    const previous = [fullSession({ id: "a" })];
    const { id, title, ...rest } = fullSession({ id: "a" });
    const shuffled = { title, id, ...rest } as SessionSummary;
    expect(stabilizeSessionSummaries(previous, [shuffled])[0]).toBe(previous[0]);
  });

  it("keeps identity across reordering but returns a new array", () => {
    const a = fullSession({ id: "a" });
    const b = fullSession({ id: "b" });
    const stabilized = stabilizeSessionSummaries([a, b], [b, a]);
    expect(stabilized).not.toBe([a, b]);
    expect(stabilized[0]).toBe(b);
    expect(stabilized[1]).toBe(a);
  });

  it("appends and removes entries with a new array while reusing survivors", () => {
    const a = fullSession({ id: "a" });
    const b = fullSession({ id: "b" });
    const appended = stabilizeSessionSummaries([a], [a, b]);
    expect(appended).not.toBe([a]);
    expect(appended[0]).toBe(a);
    expect(appended[1]).toBe(b);
    const removed = stabilizeSessionSummaries([a, b], [b]);
    expect(removed[0]).toBe(b);
    expect(removed).toHaveLength(1);
  });

  it("leaves entries without an identity key as new references", () => {
    const previous = [fullSession({ id: "a" })];
    const noId = fullSession({ id: "" });
    const stabilized = stabilizeSessionSummaries(previous, [noId]);
    expect(stabilized[0]).toBe(noId);
  });

  it("maps ids through sessionSummaryIdentityKey trimming", () => {
    expect(sessionSummaryIdentityKey({ id: " session-1 " })).toBe("session-1");
  });
});

describe("stabilizeConversationSummaries", () => {
  it("reuses equivalent entries and rotates the changed one", () => {
    const previous = [fullConversation({ conversationId: "c1" }), fullConversation({ conversationId: "c2" })];
    const next = [fullConversation({ conversationId: "c1" }), fullConversation({ conversationId: "c2", summary: "更新" })];
    const stabilized = stabilizeConversationSummaries(previous, next);
    expect(stabilized[0]).toBe(previous[0]);
    expect(stabilized[1]).toBe(next[1]);
    expect(stabilized[1]).not.toBe(previous[1]);
  });

  it("falls back through directSessionId when conversationId is empty", () => {
    expect(conversationSummaryIdentityKey(fullConversation({ conversationId: "", directSessionId: "s1" }))).toBe("s1");
    const previous = [fullConversation({ conversationId: "" , directSessionId: "s1" })];
    const next = [fullConversation({ conversationId: "", directSessionId: "s1" })];
    expect(stabilizeConversationSummaries(previous, next)[0]).toBe(previous[0]);
  });
});

describe("stabilizeIndexEntries", () => {
  it("supports custom entry types and equivalence rules", () => {
    type Row = { key: string; tags: string[] };
    const previous: Row[] = [{ key: "r1", tags: ["a"] }];
    const next: Row[] = [{ key: "r1", tags: ["a"] }];
    const stabilized = stabilizeIndexEntries(
      previous,
      next,
      (row) => row.key,
      (left, right) => areIndexEntryValuesEquivalent(left, right),
    );
    expect(stabilized).toBe(previous);
    const changed = [{ key: "r1", tags: ["b"] }];
    expect(stabilizeIndexEntries(previous, changed, (row) => row.key, areIndexEntryValuesEquivalent)[0]).toBe(changed[0]);
  });
});
