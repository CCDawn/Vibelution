import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";

/**
 * Pure client boundary for a server-authored active discussion anchor.
 *
 * The server decides which scoped room is current.  This module only checks
 * the returned identity and turns a ready anchor into the Chat route's room
 * query.  It never combines rounds from sibling rooms and it never chooses a
 * fallback room when the anchor is degraded.
 */

export const SCOPED_DISCUSSION_READY = "ready" as const;
export const SCOPED_DISCUSSION_DEGRADED = "degraded" as const;

export type ScopedDiscussionKind =
  | "question_generation"
  | "candidate_review"
  | "preformal_candidate_review";

export type FormalScopedDiscussionScope = {
  version: 1;
  kind: "question_generation" | "candidate_review";
  teamId: string;
  researchProjectId: string;
  workflowRunId: string;
  workflowNodeId: string;
  questionId: string;
  selectionId?: string;
  candidateId?: string;
};

export type PreformalScopedDiscussionScope = {
  version: 1;
  kind: "preformal_candidate_review";
  teamId: string;
  questionId: string;
  selectionId: string;
  candidateId: string;
  meetingRoundId: string;
  roomId: string;
};

export type ScopedDiscussionScope =
  | FormalScopedDiscussionScope
  | PreformalScopedDiscussionScope;

export type ActiveDiscussionAnchor = {
  scope: ScopedDiscussionScope | null;
  scopeHash: string;
  roomId: string;
  meetingRoundId: string;
  questionId: string;
  selectionId: string;
  candidateId: string;
  deepLink: string;
  returnTo?: string;
  returnLabel?: string;
  status: string;
  degradedReason: string;
};

export type ScopedDiscussionQuery = {
  kind: "room";
  room: string;
};

export type ScopedDiscussionRound = {
  roundId: string;
  status?: string;
  meetingRoundId?: string;
  config?: Record<string, unknown> | null;
};

export type ScopedDiscussionRoom = {
  roomId: string;
  status?: string;
  readable?: boolean;
  isReadable?: boolean;
  canRead?: boolean;
  scope?: Partial<ScopedDiscussionScope> | null;
  discussionScope?: Partial<ScopedDiscussionScope> | null;
  scopeHash?: string;
  discussionScopeHash?: string;
  config?: {
    scope?: Partial<ScopedDiscussionScope> | null;
    discussionScope?: Partial<ScopedDiscussionScope> | null;
    scopeHash?: string;
    discussionScopeHash?: string;
  } | null;
  rounds?: readonly ScopedDiscussionRound[] | null;
};

export type ScopedDiscussionModel = {
  status: typeof SCOPED_DISCUSSION_READY | typeof SCOPED_DISCUSSION_DEGRADED;
  degradedReason: string;
  scope: ScopedDiscussionScope | null;
  scopeHash: string;
  roomId: string;
  meetingRoundId: string;
  questionId: string;
  selectionId: string;
  candidateId: string;
  query: ScopedDiscussionQuery | null;
  search: string;
  deepLink: string;
  /** The canonical workflow route to return to after opening the room. */
  returnTo?: string;
  /** The server-authored (or stable fallback) label for the return action. */
  returnLabel?: string;
  /** The one room round that belongs to the anchor; sibling rounds are omitted. */
  selectedRoundId: string;
};

export type ScopedDiscussionModelInput = {
  anchor?: unknown;
  room?: unknown;
};

export const SCOPED_DISCUSSION_REASONS = {
  noAnchor: "no_active_discussion_anchor",
  invalidAnchor: "active_discussion_anchor_invalid",
  anchorDegraded: "active_discussion_anchor_degraded",
  roomMismatch: "active_discussion_room_mismatch",
  roomMissing: "active_discussion_room_missing",
  roomClosed: "active_discussion_room_closed",
  roomUnreadable: "active_discussion_room_unreadable",
  roundMissing: "active_discussion_round_missing",
  roundAmbiguous: "active_discussion_round_ambiguous",
} as const;

function text(value: unknown): string {
  return String(value ?? "").trim();
}

const SCOPED_DISCUSSION_RETURN_ORIGIN = "http://vibelution.local";
const SCOPED_DISCUSSION_RETURN_LABEL = "返回科研流程";

/**
 * The workflow route is intentionally derived from the validated discussion
 * scope.  The server's first implementation emitted only the four fields it
 * needed to reopen the canvas; the route adapter fills the remaining fields
 * required to restore the current node panel deterministically.
 */
export function buildScopedDiscussionReturnTo(scope: ScopedDiscussionScope): string {
  const params = new URLSearchParams();
  params.set("teamId", scope.teamId);
  params.set("researchView", "workflow");
  params.set("workflowId", CHALLENGE_CUP_WORKFLOW_ID);
  params.set("questionId", scope.questionId);
  if (scope.kind === "preformal_candidate_review") {
    params.set("node", "hf_review");
  } else {
    params.set("runId", scope.workflowRunId);
    params.set("node", scope.workflowNodeId);
  }
  params.set("panel", "node");
  return `/teams?${params.toString()}`;
}

type NormalizedReturnTo = { ok: true; value: string } | { ok: false };

/**
 * Accept only an internal /teams route whose supplied scope fields agree with
 * the active discussion.  Missing fields are deliberately filled from the
 * canonical scope so older server anchors remain navigable; a supplied wrong
 * field is never silently repaired.
 */
function normalizeScopedDiscussionReturnTo(
  value: unknown,
  scope: ScopedDiscussionScope,
): NormalizedReturnTo {
  const raw = text(value);
  const canonical = buildScopedDiscussionReturnTo(scope);
  if (!raw) return { ok: true, value: canonical };
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) {
    return { ok: false };
  }

  let parsed: URL;
  try {
    parsed = new URL(raw, SCOPED_DISCUSSION_RETURN_ORIGIN);
  } catch {
    return { ok: false };
  }
  if (
    parsed.origin !== SCOPED_DISCUSSION_RETURN_ORIGIN
    || parsed.pathname !== "/teams"
    || parsed.pathname.includes("\\")
    || parsed.hash
  ) {
    return { ok: false };
  }

  const expected: Record<string, string> = {
    teamId: scope.teamId,
    researchView: "workflow",
    workflowId: CHALLENGE_CUP_WORKFLOW_ID,
    questionId: scope.questionId,
    node: scope.kind === "preformal_candidate_review" ? "hf_review" : scope.workflowNodeId,
    panel: "node",
  };
  if (scope.kind !== "preformal_candidate_review") {
    expected.runId = scope.workflowRunId;
  } else if (parsed.searchParams.has("runId")) {
    return { ok: false };
  }
  for (const [key, expectedValue] of Object.entries(expected)) {
    const values = parsed.searchParams.getAll(key);
    if (values.length > 1 || (values.length === 1 && values[0] !== expectedValue)) {
      return { ok: false };
    }
  }
  return { ok: true, value: canonical };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asScope(value: unknown): ScopedDiscussionScope | null {
  if (!isRecord(value)) return null;
  const kind = text(value.kind);
  if (kind === "preformal_candidate_review") {
    const scope: PreformalScopedDiscussionScope = {
      version: Number(value.version) === 1 ? 1 : (value.version as 1),
      kind: "preformal_candidate_review",
      teamId: text(value.teamId),
      questionId: text(value.questionId),
      selectionId: text(value.selectionId),
      candidateId: text(value.candidateId),
      meetingRoundId: text(value.meetingRoundId),
      roomId: text(value.roomId),
    };
    if (
      scope.version !== 1
      || !scope.teamId
      || !scope.questionId
      || !scope.selectionId
      || !scope.candidateId
      || !scope.meetingRoundId
      || !scope.roomId
    ) {
      return null;
    }
    return scope;
  }
  const scope: ScopedDiscussionScope = {
    version: Number(value.version) === 1 ? 1 : (value.version as 1),
    kind: kind as "question_generation" | "candidate_review",
    teamId: text(value.teamId),
    researchProjectId: text(value.researchProjectId),
    workflowRunId: text(value.workflowRunId),
    workflowNodeId: text(value.workflowNodeId),
    questionId: text(value.questionId),
    ...(text(value.selectionId) ? { selectionId: text(value.selectionId) } : {}),
    ...(text(value.candidateId) ? { candidateId: text(value.candidateId) } : {}),
  };
  if (
    scope.version !== 1
    || (scope.kind !== "question_generation" && scope.kind !== "candidate_review")
    || !scope.teamId
    || !scope.researchProjectId
    || !scope.workflowRunId
    || !scope.workflowNodeId
    || !scope.questionId
  ) {
    return null;
  }
  const hasSelection = Boolean(scope.selectionId);
  const hasCandidate = Boolean(scope.candidateId);
  if (scope.kind === "question_generation" && (hasSelection || hasCandidate)) return null;
  if (scope.kind === "candidate_review" && (!hasSelection || !hasCandidate)) return null;
  return scope;
}

function anchorBase(reason: string, anchor?: Partial<ActiveDiscussionAnchor> | null): ScopedDiscussionModel {
  const scope = asScope(anchor?.scope);
  return {
    status: SCOPED_DISCUSSION_DEGRADED,
    degradedReason: reason,
    scope,
    scopeHash: text(anchor?.scopeHash),
    roomId: text(anchor?.roomId),
    meetingRoundId: text(anchor?.meetingRoundId),
    questionId: text(anchor?.questionId),
    selectionId: text(anchor?.selectionId),
    candidateId: text(anchor?.candidateId),
    query: null,
    search: "",
    deepLink: "",
    returnTo: "",
    returnLabel: "",
    selectedRoundId: "",
  };
}

function parseAnchor(value: unknown):
  | { ok: true; anchor: ActiveDiscussionAnchor; scope: ScopedDiscussionScope }
  | { ok: false; model: ScopedDiscussionModel } {
  if (!isRecord(value)) return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.noAnchor) };
  const scope = asScope(value.scope);
  if (!scope) return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.invalidAnchor, value) };
  const status = text(value.status).toLowerCase();
  const anchor: ActiveDiscussionAnchor = {
    scope,
    scopeHash: text(value.scopeHash),
    roomId: text(value.roomId),
    meetingRoundId: text(value.meetingRoundId),
    questionId: text(value.questionId),
    selectionId: text(value.selectionId),
    candidateId: text(value.candidateId),
    deepLink: text(value.deepLink),
    returnTo: text(value.returnTo),
    returnLabel: text(value.returnLabel),
    status,
    degradedReason: text(value.degradedReason),
  };
  if (status !== SCOPED_DISCUSSION_READY) {
    return { ok: false, model: anchorBase(anchor.degradedReason || SCOPED_DISCUSSION_REASONS.anchorDegraded, anchor) };
  }
  if (
    !anchor.scopeHash
    || !anchor.roomId
    || !anchor.meetingRoundId
    || anchor.questionId !== scope.questionId
    || anchor.selectionId !== text(scope.selectionId)
    || anchor.candidateId !== text(scope.candidateId)
    || (
      scope.kind === "preformal_candidate_review"
      && (
        anchor.meetingRoundId !== scope.meetingRoundId
        || anchor.roomId !== scope.roomId
      )
    )
  ) {
    return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.invalidAnchor, anchor) };
  }
  const providedScopeHash = text((value.scope as Record<string, unknown> | null)?.scopeHash);
  if (providedScopeHash && providedScopeHash !== anchor.scopeHash) {
    return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.invalidAnchor, anchor) };
  }
  if (!anchor.deepLink) {
    return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.invalidAnchor, anchor) };
  }
  let parsedLink: URL;
  try {
    parsedLink = new URL(anchor.deepLink, "http://vibelution.local");
  } catch {
    return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.invalidAnchor, anchor) };
  }
  if (
    !anchor.deepLink.startsWith("/")
    || anchor.deepLink.startsWith("//")
    || anchor.deepLink.startsWith("/\\")
    || parsedLink.origin !== SCOPED_DISCUSSION_RETURN_ORIGIN
    || parsedLink.pathname !== "/chat"
    || parsedLink.pathname.includes("\\")
    || parsedLink.hash
    || parsedLink.searchParams.getAll("room").length !== 1
    || parsedLink.searchParams.get("room") !== anchor.roomId
  ) {
    return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.invalidAnchor, anchor) };
  }

  const anchorReturnTo = normalizeScopedDiscussionReturnTo(anchor.returnTo, scope);
  const linkReturnTo = normalizeScopedDiscussionReturnTo(
    parsedLink.searchParams.get("returnTo"),
    scope,
  );
  if (!anchorReturnTo.ok || !linkReturnTo.ok || anchorReturnTo.value !== linkReturnTo.value) {
    return { ok: false, model: anchorBase(SCOPED_DISCUSSION_REASONS.invalidAnchor, anchor) };
  }
  const returnLabel = anchor.returnLabel
    || text(parsedLink.searchParams.get("returnLabel"))
    || SCOPED_DISCUSSION_RETURN_LABEL;
  return {
    ok: true,
    anchor: {
      ...anchor,
      returnTo: anchorReturnTo.value,
      returnLabel,
      deepLink: parsedLink.toString(),
    },
    scope,
  };
}

function roomScope(room: ScopedDiscussionRoom): { scope: ScopedDiscussionScope | null; scopeHash: string } {
  const config = isRecord(room.config) ? room.config : null;
  const raw = room.discussionScope ?? room.scope ?? config?.discussionScope ?? config?.scope;
  return {
    scope: asScope(raw),
    scopeHash: text(room.discussionScopeHash ?? room.scopeHash ?? config?.discussionScopeHash ?? config?.scopeHash),
  };
}

function roomIsReadable(room: ScopedDiscussionRoom): string | null {
  const status = text(room.status).toLowerCase();
  if (["closed", "archived", "deleted", "cancelled", "canceled"].includes(status)) {
    return SCOPED_DISCUSSION_REASONS.roomClosed;
  }
  if (room.readable === false || room.isReadable === false || room.canRead === false) {
    return SCOPED_DISCUSSION_REASONS.roomUnreadable;
  }
  return null;
}

function roundMatches(round: ScopedDiscussionRound, meetingRoundId: string): boolean {
  if (text(round.meetingRoundId) === meetingRoundId) return true;
  if (isRecord(round.config) && text(round.config.meetingRoundId) === meetingRoundId) return true;
  return false;
}

function inputParts(input: unknown): { anchor: unknown; room: unknown } {
  if (isRecord(input) && ("anchor" in input || "room" in input)) {
    return { anchor: input.anchor, room: input.room };
  }
  return { anchor: input, room: undefined };
}

/**
 * Validate the server anchor and create a route-safe room query state.
 * ``room`` is optional so callers can use this before loading room detail;
 * when supplied, its scope/readability is checked and only its bound round is
 * selected.
 */
export function buildScopedDiscussionModel(input: unknown): ScopedDiscussionModel {
  const { anchor: rawAnchor, room: rawRoom } = inputParts(input);
  const parsed = parseAnchor(rawAnchor);
  if ("model" in parsed) return parsed.model;
  const { anchor, scope } = parsed;
  const query: ScopedDiscussionQuery = { kind: "room", room: anchor.roomId };
  const search = `?room=${encodeURIComponent(anchor.roomId)}`;
  const parsedDeepLink = new URL(anchor.deepLink, SCOPED_DISCUSSION_RETURN_ORIGIN);
  parsedDeepLink.searchParams.delete("returnTo");
  parsedDeepLink.searchParams.delete("returnLabel");
  parsedDeepLink.searchParams.set("returnTo", anchor.returnTo || buildScopedDiscussionReturnTo(scope));
  parsedDeepLink.searchParams.set("returnLabel", anchor.returnLabel || SCOPED_DISCUSSION_RETURN_LABEL);
  const deepLink = `${parsedDeepLink.pathname}?${parsedDeepLink.searchParams.toString()}`;
  const model: ScopedDiscussionModel = {
    status: SCOPED_DISCUSSION_READY,
    degradedReason: "",
    scope,
    scopeHash: anchor.scopeHash,
    roomId: anchor.roomId,
    meetingRoundId: anchor.meetingRoundId,
    questionId: anchor.questionId,
    selectionId: anchor.selectionId,
    candidateId: anchor.candidateId,
    query,
    search,
    deepLink,
    returnTo: anchor.returnTo || buildScopedDiscussionReturnTo(scope),
    returnLabel: anchor.returnLabel || SCOPED_DISCUSSION_RETURN_LABEL,
    selectedRoundId: "",
  };
  if (rawRoom === undefined || rawRoom === null) return model;
  if (!isRecord(rawRoom)) return anchorBase(SCOPED_DISCUSSION_REASONS.roomMissing, anchor);
  const room = rawRoom as unknown as ScopedDiscussionRoom;
  if (text(room.roomId) !== anchor.roomId) return anchorBase(SCOPED_DISCUSSION_REASONS.roomMismatch, anchor);
  const readabilityReason = roomIsReadable(room);
  if (readabilityReason) return anchorBase(readabilityReason, anchor);
  const roomIdentity = roomScope(room);
  if (!roomIdentity.scope) return anchorBase(SCOPED_DISCUSSION_REASONS.roomMismatch, anchor);
  if (roomIdentity.scopeHash && roomIdentity.scopeHash !== anchor.scopeHash) {
    return anchorBase(SCOPED_DISCUSSION_REASONS.roomMismatch, anchor);
  }
  if (JSON.stringify(roomIdentity.scope) !== JSON.stringify(scope)) {
    return anchorBase(SCOPED_DISCUSSION_REASONS.roomMismatch, anchor);
  }
  const rounds = Array.isArray(room.rounds) ? room.rounds : [];
  if (rounds.length) {
    const boundRounds = rounds.filter((round) => roundMatches(round, anchor.meetingRoundId));
    if (boundRounds.length !== 1) {
      return anchorBase(
        boundRounds.length === 0
          ? SCOPED_DISCUSSION_REASONS.roundMissing
          : SCOPED_DISCUSSION_REASONS.roundAmbiguous,
        anchor,
      );
    }
    model.selectedRoundId = text(boundRounds[0].roundId);
  }
  return model;
}

/** Validate only, for adapters that do not yet have room detail. */
export function validateScopedDiscussionAnchor(value: unknown): ScopedDiscussionModel {
  return buildScopedDiscussionModel(value);
}

/** Explicit name for route adapters that consume the query/search pair. */
export const projectScopedDiscussionQuery = buildScopedDiscussionModel;
export const buildScopedDiscussionQueryState = buildScopedDiscussionModel;
