import type { ComposerImageAttachment } from "../chat/chatComposerSubmitModel";
import type { SessionPendingQuestion, SessionReferenceAttachment } from "../../api/types";
import type { SessionContinuationExpectation } from "../../api/chat";
import { LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE, validLauncherAssistantControlContinuation } from "../../api/launcherAssistant";
import type { LauncherAssistantQuestionDraft, LauncherAssistantQueuedAcceptance, LauncherAssistantSubmission } from "./launcherAssistantModel";

/** Recoverable attachment metadata only: id plus the uploaded backend artifact.
 * The File/Blob body and its local blob: preview URL are not serializable, so
 * they are intentionally never persisted; a restored chip reuses its artifactId
 * (no re-upload) and fetches a fresh preview through the read IPC. Secret chips
 * persist the same reference-only shape (kind "secret", `sec_` artifactId) —
 * the plaintext value never enters storage in any field. */
export type PersistedLauncherComposerAttachment = {
  id: string;
  artifactId: string;
  filename: string;
  contentType: string;
  sizeBytes: number;
  kind: "image" | "document" | "secret";
};

export type PersistedLauncherComposer = {
  draft: string;
  outstanding: LauncherAssistantSubmission | null;
  acceptedTurnId: string;
  queuedAcceptance: LauncherAssistantQueuedAcceptance | null;
  attachments: PersistedLauncherComposerAttachment[];
  questionDraft?: LauncherAssistantQuestionDraft | null;
  references?: SessionReferenceAttachment[];
  continuation?: PersistedLauncherContinuation;
};

export type PersistedLauncherContinuation = { requestId: string; expected: SessionContinuationExpectation; accepted: boolean };

/** Write-side input: the Route's richer snapshot (full tray chips, continuation)
 * is accepted and reduced to recovery fields. Already-persisted metadata rows
 * are also accepted so recovery snapshots re-save without re-reduction. */
export type LauncherComposerPersistenceInput = {
  draft: string;
  outstanding: LauncherAssistantSubmission | null;
  acceptedTurnId: string;
  queuedAcceptance: LauncherAssistantQueuedAcceptance | null;
  attachments?: readonly (ComposerImageAttachment | PersistedLauncherComposerAttachment)[] | undefined;
  questionDraft?: LauncherAssistantQuestionDraft | null;
  references?: SessionReferenceAttachment[];
  continuation?: PersistedLauncherContinuation;
};

type ComposerSurface = "floating" | "embedded";
const VERSION = 1;
const MAX_TEXT_CHARS = 64_000;
// Four 64k text fields may each require six JSON characters per character;
// leave room for two bounded question records and uploaded attachment metadata.
const MAX_JSON_CHARS = 1_800_000;
const MAX_ATTACHMENT_IDS = 32;
const SNAPSHOT_FIELDS = ["draft", "outstanding", "acceptedTurnId", "queuedAcceptance"];
// `attachments` is optional so envelopes written before attachment persistence
// (same VERSION) still load; new writes always include the field.
// `questionDraft` is also optional in VERSION 1; null explicitly clears it.
const SNAPSHOT_ALLOWED = [...SNAPSHOT_FIELDS, "attachments", "questionDraft", "references", "continuation"];
const SUBMISSION_FIELDS = ["message", "requestId", "draftSnapshot", "attachmentIds", "attachmentSnapshotIds", "preserveDraft", "answerQuestion", "references", "controlContinuation"];
const ATTACHMENT_FIELDS = ["id", "artifactId", "filename", "contentType", "sizeBytes", "kind"];
const QUESTION_FIELDS = ["id", "questionText", "askedAt", "turnId"];
const MAX_FILENAME_CHARS = 255;

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

function artifactId(value: unknown): value is string {
  return typeof value === "string" && value.length <= 255 && /^[A-Za-z0-9_.-]+$/.test(value) && value !== "." && value !== "..";
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_TEXT_CHARS;
}

function ids(value: unknown, artifact: boolean): value is string[] {
  return Array.isArray(value) && value.length <= MAX_ATTACHMENT_IDS && Array.from(value).every(item =>
    id(item) && (!artifact || (/^[A-Za-z0-9_.-]+$/.test(item) && item !== "." && item !== "..")));
}

function pendingQuestion(value: unknown): SessionPendingQuestion | null {
  if (!record(value) || !fields(value, QUESTION_FIELDS) || !id(value.id)
    || typeof value.questionText !== "string" || value.questionText.length > 4_000
    || typeof value.askedAt !== "string" || value.askedAt.length > 64
    || (value.turnId !== "" && !id(value.turnId))) return null;
  return { id: value.id, questionText: value.questionText, askedAt: value.askedAt, turnId: value.turnId as string };
}

function pendingQuestionDraft(value: unknown): LauncherAssistantQuestionDraft | null {
  if (!record(value) || !fields(value, ["question", "value"]) || !text(value.value)) return null;
  const question = pendingQuestion(value.question);
  return question ? { question, value: value.value } : null;
}

/** Closed DTO metadata only. Native submit remains the reference/ACL authority;
 * recovery must not add paths, tokens, Blob bodies or unknown extension fields. */
function references(value: unknown): SessionReferenceAttachment[] | null {
  const identityFields = ["referenceId", "sessionId", "agentId", "knowledgeItemId", "knowledgeBaseId", "artifactId", "sourceSessionId", "sourceMessageId"];
  const displayFields = ["title", "agentCode", "agentDisplayName", "summary", "createdAt", "filename", "quote"];
  if (!Array.isArray(value) || value.length > 8) return null;
  const rows: SessionReferenceAttachment[] = [];
  for (const item of value) {
    if (!record(item) || !fields(item, ["kind"], ["kind", ...identityFields, ...displayFields])
      || typeof item.kind !== "string" || !/^[A-Za-z0-9_-]{1,40}$/.test(item.kind)
      || !["referenceId", "sessionId", "knowledgeItemId", "knowledgeBaseId", "artifactId", "sourceMessageId"].some(key => id(item[key]))
      || identityFields.some(key => item[key] !== undefined && !id(item[key]))
      || displayFields.some(key => item[key] !== undefined && !text(item[key]))) return null;
    const row = { ...item } as SessionReferenceAttachment;
    // Match the native bridge's per-reference envelope ceiling.
    if (JSON.stringify(row).length > 16_000) return null;
    rows.push(row);
  }
  return rows;
}

function continuation(value: unknown): PersistedLauncherContinuation | null {
  if (!record(value) || !fields(value, ["requestId", "expected", "accepted"]) || !id(value.requestId, 128)
    || typeof value.accepted !== "boolean" || !record(value.expected)
    || !fields(value.expected, ["turnId", "headId", "ledgerSeq", "agentId"])
    || !id(value.expected.turnId) || !id(value.expected.headId) || !id(value.expected.agentId)
    || !Number.isSafeInteger(value.expected.ledgerSeq) || (value.expected.ledgerSeq as number) < 1) return null;
  return { requestId: value.requestId, expected: { turnId: value.expected.turnId, headId: value.expected.headId,
    ledgerSeq: value.expected.ledgerSeq as number, agentId: value.expected.agentId }, accepted: value.accepted };
}

function submission(value: unknown): LauncherAssistantSubmission | null {
  const savedReferences = record(value) && value.references !== undefined ? references(value.references) : undefined;
  if (!record(value) || !fields(value, ["message", "requestId"], SUBMISSION_FIELDS)
    || !text(value.message) || !id(value.requestId, 128)
    || (value.draftSnapshot !== undefined && !text(value.draftSnapshot))
    || (value.attachmentIds !== undefined && !ids(value.attachmentIds, true))
    || (value.attachmentSnapshotIds !== undefined && !ids(value.attachmentSnapshotIds, false))
    || (value.preserveDraft !== undefined && value.preserveDraft !== true)
    || savedReferences === null
    || (!value.message.trim() && !(value.attachmentIds as string[] | undefined)?.length && !savedReferences?.length)) return null;
  const answerQuestion = value.answerQuestion === undefined ? null : pendingQuestion(value.answerQuestion);
  if (value.answerQuestion !== undefined && (!answerQuestion || value.preserveDraft !== true)) return null;
  if (value.controlContinuation !== undefined && (!validLauncherAssistantControlContinuation(value.controlContinuation)
    || value.message !== LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE || value.preserveDraft !== true
    || value.attachmentIds !== undefined || value.references !== undefined || value.answerQuestion !== undefined)) return null;
  return {
    message: value.message, requestId: value.requestId,
    ...(value.draftSnapshot !== undefined ? { draftSnapshot: value.draftSnapshot as string } : {}),
    ...(value.attachmentIds !== undefined ? { attachmentIds: [...value.attachmentIds as string[]] } : {}),
    ...(value.attachmentSnapshotIds !== undefined ? { attachmentSnapshotIds: [...value.attachmentSnapshotIds as string[]] } : {}),
    ...(value.preserveDraft === true ? { preserveDraft: true } : {}),
    ...(answerQuestion ? { answerQuestion } : {}),
    ...(savedReferences ? { references: savedReferences } : {}),
    ...(validLauncherAssistantControlContinuation(value.controlContinuation) ? { controlContinuation: { ...value.controlContinuation } } : {}),
  };
}

function contentTypeValid(value: unknown): value is string {
  return typeof value === "string" && value.length <= 127
    && /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/.test(value);
}

function persistedAttachment(value: unknown): PersistedLauncherComposerAttachment | null {
  if (!record(value) || !fields(value, ATTACHMENT_FIELDS) || !id(value.id, 128) || !artifactId(value.artifactId)
    || typeof value.filename !== "string" || Array.from(value.filename).length > MAX_FILENAME_CHARS
    || /[\u0000-\u001f\u007f]/.test(value.filename)
    || !contentTypeValid(value.contentType) || !Number.isSafeInteger(value.sizeBytes) || (value.sizeBytes as number) < 0
    || !["image", "document", "secret"].includes(String(value.kind))) return null;
  return { id: value.id, artifactId: value.artifactId, filename: value.filename,
    contentType: value.contentType, sizeBytes: value.sizeBytes as number, kind: value.kind as "image" | "document" };
}

function attachmentRows(value: unknown): PersistedLauncherComposerAttachment[] | null {
  if (!Array.isArray(value) || value.length > MAX_ATTACHMENT_IDS) return null;
  const rows: PersistedLauncherComposerAttachment[] = [];
  for (const item of value) {
    const row = persistedAttachment(item);
    if (!row) return null;
    rows.push(row);
  }
  return rows;
}

/** Only already-uploaded chips are recoverable: pending/failed ones still hold
 * their unreadable File body, so persisting them would promise a restore the
 * tray cannot honour. Metadata rows without an upload lifecycle pass through. */
function persistedAttachments(
  value: readonly (ComposerImageAttachment | PersistedLauncherComposerAttachment)[] | null | undefined,
): PersistedLauncherComposerAttachment[] {
  if (!value) return [];
  const rows: PersistedLauncherComposerAttachment[] = [];
  for (const item of value.slice(0, MAX_ATTACHMENT_IDS)) {
    const source = item as Partial<ComposerImageAttachment & PersistedLauncherComposerAttachment>;
    if (source.uploadStatus !== undefined && source.uploadStatus !== "uploaded") continue;
    const row = persistedAttachment({ id: source.id, artifactId: source.artifactId,
      filename: Array.from(source.filename || "").slice(0, MAX_FILENAME_CHARS).join("").replace(/[\u0000-\u001f\u007f]/g, ""),
      contentType: source.contentType, sizeBytes: source.sizeBytes, kind: source.kind });
    if (row) rows.push(row);
  }
  return rows;
}

function snapshot(value: unknown): PersistedLauncherComposer | null {
  if (!record(value) || !fields(value, SNAPSHOT_FIELDS, SNAPSHOT_ALLOWED) || !text(value.draft)
    || (value.acceptedTurnId !== "" && !id(value.acceptedTurnId))) return null;
  const attachments = value.attachments === undefined ? [] : attachmentRows(value.attachments);
  if (!attachments) return null;
  const outstanding = submission(value.outstanding);
  if (value.outstanding !== null && !outstanding) return null;
  const questionDraft = value.questionDraft == null ? null : pendingQuestionDraft(value.questionDraft);
  if (value.questionDraft !== undefined && value.questionDraft !== null && !questionDraft) return null;
  const savedReferences = value.references === undefined ? undefined : references(value.references);
  const savedContinuation = value.continuation === undefined ? undefined : continuation(value.continuation);
  if (savedReferences === null || savedContinuation === null) return null;
  let queuedAcceptance: LauncherAssistantQueuedAcceptance | null = null;
  if (value.queuedAcceptance !== null) {
    const receipt = value.queuedAcceptance;
    if (!record(receipt) || !fields(receipt, ["id", "clientSubmissionId", "observed"])
      || !id(receipt.id) || !id(receipt.clientSubmissionId, 128) || typeof receipt.observed !== "boolean") return null;
    queuedAcceptance = { id: receipt.id, clientSubmissionId: receipt.clientSubmissionId, observed: receipt.observed };
  }
  return { draft: value.draft, outstanding, acceptedTurnId: value.acceptedTurnId as string, queuedAcceptance, attachments,
    ...(value.questionDraft !== undefined ? { questionDraft } : {}),
    ...(savedReferences ? { references: savedReferences } : {}),
    ...(savedContinuation ? { continuation: savedContinuation } : {}) };
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

/** Pick only validated recovery fields; File/Blob bodies, blob: previews and
 * other Route state never enter storage. Uploaded attachment metadata is kept so
 * a reload can rebuild the tray without re-uploading. */
export function saveLauncherComposer(
  sessionId: string, surface: ComposerSurface, value: LauncherComposerPersistenceInput, storage?: Pick<Storage, "setItem">,
): boolean {
  try {
    const storageKey = key(sessionId, surface);
    if (!storageKey || !record(value)) return false;
    const saved = snapshot({ draft: value.draft, outstanding: value.outstanding,
      acceptedTurnId: value.acceptedTurnId, queuedAcceptance: value.queuedAcceptance,
      attachments: persistedAttachments(value.attachments), questionDraft: value.questionDraft,
      references: value.references, continuation: value.continuation });
    if (!saved) return false;
    const raw = JSON.stringify({ version: VERSION, sessionId, surface, snapshot: saved });
    if (raw.length > MAX_JSON_CHARS) return false;
    (storage ?? localStorage).setItem(storageKey, raw);
    return true;
  } catch {
    return false;
  }
}

/** Rebuild tray chips from persisted rows. The original File body and blob:
 * preview are unrecoverable, so a restored chip carries an empty placeholder
 * File (never re-uploaded: submit reuses the stored artifactId) with an empty
 * preview that the Route fills asynchronously through the attachment read IPC. */
export function restoreLauncherComposerAttachments(rows: readonly PersistedLauncherComposerAttachment[]): ComposerImageAttachment[] {
  return rows.map(row => ({
    id: row.id,
    file: new File([], row.filename, { type: row.contentType }),
    filename: row.filename,
    previewUrl: "",
    sizeBytes: row.sizeBytes,
    contentType: row.contentType,
    kind: row.kind,
    uploadStatus: "uploaded",
    artifactId: row.artifactId,
  }));
}
