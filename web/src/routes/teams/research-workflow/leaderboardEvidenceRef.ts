/**
 * Evidence-ref parsing for the challenge-cup hypothesis leaderboard.
 *
 * Seven-dimension review rows carry `evidence_refs` as opaque strings. Two
 * families exist on the wire:
 * - digest source-message backlinks `roomId/roundId/messageId` (see the
 *   backend `message_source_ref` helper) — these are drillable down to the
 *   source discussion message;
 * - everything else (candidate lineage labels like `round:...` / baseline
 *   tags / free text) — rendered as plain text.
 *
 * Parsing is fail-closed: anything that is not exactly three non-empty
 * slash-separated segments stays plain text, never throws, so a malformed
 * reference degrades to its raw string instead of breaking the panel.
 */

import type {
  CandidateEvidenceEntry,
  MeetingSourceMessage,
} from "../../../api/types/hypothesisFirst";

export type ParsedLeaderboardEvidenceRef =
  | { kind: "source_message"; roomId: string; roundId: string; messageId: string }
  | { kind: "text"; text: string };

/** Three non-empty `/`-separated segments → source-message backlink; else text. */
export function parseLeaderboardEvidenceRef(rawRef: string): ParsedLeaderboardEvidenceRef {
  const trimmed = typeof rawRef === "string" ? rawRef.trim() : "";
  if (!trimmed) return { kind: "text", text: "" };
  const segments = trimmed.split("/").map((segment) => segment.trim());
  if (segments.length === 3 && segments.every((segment) => segment.length > 0)) {
    return {
      kind: "source_message",
      roomId: segments[0],
      roundId: segments[1],
      messageId: segments[2],
    };
  }
  return { kind: "text", text: trimmed };
}

/** Trail entry whose `messageId` matches a source-message backlink, if any. */
export function trailEntryForRef(
  entries: CandidateEvidenceEntry[],
  ref: ParsedLeaderboardEvidenceRef,
): CandidateEvidenceEntry | null {
  if (ref.kind !== "source_message") return null;
  for (const entry of entries) {
    if (typeof entry?.messageId === "string" && entry.messageId.trim() === ref.messageId) {
      return entry;
    }
  }
  return null;
}

/**
 * Source message matching a backlink. `messageId` is the join key; when the
 * wire message also carries `roomId`/`roundId` they must agree with the ref
 * (stricter match), while messages missing them still match on id alone.
 */
export function sourceMessageForRef(
  messages: MeetingSourceMessage[],
  ref: ParsedLeaderboardEvidenceRef,
): MeetingSourceMessage | null {
  if (ref.kind !== "source_message") return null;
  for (const message of messages) {
    if (!message || typeof message !== "object") continue;
    const messageId = String(message.messageId ?? "").trim();
    if (messageId !== ref.messageId) continue;
    const roomId = String(message.roomId ?? "").trim();
    const roundId = String(message.roundId ?? "").trim();
    if (roomId && roundId && (roomId !== ref.roomId || roundId !== ref.roundId)) continue;
    return message;
  }
  return null;
}

/**
 * Fail-closed `meetingRoundIds` extraction from a hypothesis round's
 * `meetingRefs` (`{kind:"meeting_round", id}` rows only; junk dropped).
 */
export function collectMeetingRoundIds(meetingRefs: unknown): string[] {
  if (!Array.isArray(meetingRefs)) return [];
  const ids: string[] = [];
  for (const raw of meetingRefs) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const record = raw as Record<string, unknown>;
    if (record.kind !== "meeting_round") continue;
    const id = typeof record.id === "string" ? record.id.trim() : "";
    if (id) ids.push(id);
  }
  return ids;
}

/** Speaker line for a source message: human title first, then agent id/role. */
export function sourceMessageSpeaker(message: MeetingSourceMessage): string {
  const title = String(message.speakerTitle ?? "").trim();
  if (title) return title;
  const agentId = String(message.agentId ?? "").trim();
  if (agentId) return agentId;
  return String(message.role ?? "").trim();
}
