import type { LauncherAssistantQueuedAcceptance, LauncherAssistantSubmission } from "./launcherAssistantModel";

export type PersistedLauncherComposer = {
  draft: string;
  outstanding: LauncherAssistantSubmission | null;
  acceptedTurnId: string;
  queuedAcceptance: LauncherAssistantQueuedAcceptance | null;
};

type ComposerSurface = "floating" | "embedded";
const VERSION = 1;
const MAX_TEXT_CHARS = 64_000;
// Three bounded text fields may each require six JSON characters per character.
const MAX_JSON_CHARS = 1_200_000;
const MAX_ATTACHMENT_IDS = 32;
const SNAPSHOT_FIELDS = ["draft", "outstanding", "acceptedTurnId", "queuedAcceptance"];
const SUBMISSION_FIELDS = ["message", "requestId", "draftSnapshot", "attachmentIds", "attachmentSnapshotIds", "preserveDraft"];

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function fields(value: Record<string, unknown>, required: string[], allowed = required): boolean {
  return required.every(key => Object.prototype.hasOwnProperty.call(value, key))
    && Object.keys(value).every(key => allowed.includes(key));
}

function id(value: unknown, max = 255): value is string {
  return typeof value === "string" && value.length <= max && /^[A-Za-z0-9_.:-]+$/.test(value);
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_TEXT_CHARS;
}

function ids(value: unknown, artifact: boolean): value is string[] {
  return Array.isArray(value) && value.length <= MAX_ATTACHMENT_IDS && Array.from(value).every(item =>
    id(item) && (!artifact || (/^[A-Za-z0-9_.-]+$/.test(item) && item !== "." && item !== "..")));
}

function submission(value: unknown): LauncherAssistantSubmission | null {
  if (!record(value) || !fields(value, ["message", "requestId"], SUBMISSION_FIELDS)
    || !text(value.message) || !id(value.requestId, 128)
    || (value.draftSnapshot !== undefined && !text(value.draftSnapshot))
    || (value.attachmentIds !== undefined && !ids(value.attachmentIds, true))
    || (value.attachmentSnapshotIds !== undefined && !ids(value.attachmentSnapshotIds, false))
    || (value.preserveDraft !== undefined && value.preserveDraft !== true)
    || (!value.message.trim() && !(value.attachmentIds as string[] | undefined)?.length)) return null;
  return {
    message: value.message, requestId: value.requestId,
    ...(value.draftSnapshot !== undefined ? { draftSnapshot: value.draftSnapshot as string } : {}),
    ...(value.attachmentIds !== undefined ? { attachmentIds: [...value.attachmentIds as string[]] } : {}),
    ...(value.attachmentSnapshotIds !== undefined ? { attachmentSnapshotIds: [...value.attachmentSnapshotIds as string[]] } : {}),
    ...(value.preserveDraft === true ? { preserveDraft: true } : {}),
  };
}

function snapshot(value: unknown): PersistedLauncherComposer | null {
  if (!record(value) || !fields(value, SNAPSHOT_FIELDS) || !text(value.draft)
    || (value.acceptedTurnId !== "" && !id(value.acceptedTurnId))) return null;
  const outstanding = submission(value.outstanding);
  if (value.outstanding !== null && !outstanding) return null;
  let queuedAcceptance: LauncherAssistantQueuedAcceptance | null = null;
  if (value.queuedAcceptance !== null) {
    const receipt = value.queuedAcceptance;
    if (!record(receipt) || !fields(receipt, ["id", "clientSubmissionId", "observed"])
      || !id(receipt.id) || !id(receipt.clientSubmissionId, 128) || typeof receipt.observed !== "boolean") return null;
    queuedAcceptance = { id: receipt.id, clientSubmissionId: receipt.clientSubmissionId, observed: receipt.observed };
  }
  return { draft: value.draft, outstanding, acceptedTurnId: value.acceptedTurnId as string, queuedAcceptance };
}

function key(sessionId: string, surface: ComposerSurface): string | null {
  return id(sessionId) && (surface === "floating" || surface === "embedded")
    ? `vibelution.launcher-assistant.composer.v${VERSION}:${surface}:${encodeURIComponent(sessionId)}` : null;
}

/** Recovery data only: the Route owns native readback and retry of the original request. */
export function loadLauncherComposer(
  sessionId: string, surface: ComposerSurface, storage?: Pick<Storage, "getItem">,
): PersistedLauncherComposer | null {
  try {
    const storageKey = key(sessionId, surface);
    if (!storageKey) return null;
    const raw = (storage ?? localStorage).getItem(storageKey);
    if (!raw || raw.length > MAX_JSON_CHARS) return null;
    const envelope: unknown = JSON.parse(raw);
    if (!record(envelope) || !fields(envelope, ["version", "sessionId", "surface", "snapshot"])
      || envelope.version !== VERSION || envelope.sessionId !== sessionId || envelope.surface !== surface) return null;
    return snapshot(envelope.snapshot);
  } catch {
    return null;
  }
}

/** Pick only recovery fields; File/Blob, continuation and other Route state never enter storage. */
export function saveLauncherComposer(
  sessionId: string, surface: ComposerSurface, value: PersistedLauncherComposer, storage?: Pick<Storage, "setItem">,
): boolean {
  try {
    const storageKey = key(sessionId, surface);
    if (!storageKey || !record(value)) return false;
    const saved = snapshot({ draft: value.draft, outstanding: value.outstanding,
      acceptedTurnId: value.acceptedTurnId, queuedAcceptance: value.queuedAcceptance });
    if (!saved) return false;
    const raw = JSON.stringify({ version: VERSION, sessionId, surface, snapshot: saved });
    if (raw.length > MAX_JSON_CHARS) return false;
    (storage ?? localStorage).setItem(storageKey, raw);
    return true;
  } catch {
    return false;
  }
}
