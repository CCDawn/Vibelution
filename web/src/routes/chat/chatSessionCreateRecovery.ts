import type { SessionDetail } from "../../api/types";
import { isTempSessionId } from "../sessionOptimisticIds";

export const SESSION_CREATE_RECOVERY_KEY = "vibelution.chat.create-recovery.v1";
const MAX_INTENTS = 50;
const MAX_STORAGE_CHARS = 64 * 1024;
type RecoveryStorage = Pick<Storage, "getItem" | "setItem">;

/** Identity only. Drafts stay in the existing composer store; no transcript. */
export type SessionCreateRecovery = {
  tempSessionId: string;
  agentId: string;
  idempotencyKey: string;
  createdAt: string;
};

export function sessionCreateRecoveryStorage(): RecoveryStorage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.sessionStorage;
  } catch {
    return undefined;
  }
}

function readRecords(storage: RecoveryStorage | undefined): SessionCreateRecovery[] {
  try {
    const raw = storage?.getItem(SESSION_CREATE_RECOVERY_KEY);
    if (!raw || raw.length > MAX_STORAGE_CHARS) return [];
    const payload: unknown = JSON.parse(raw);
    if (!Array.isArray(payload)) return [];
    return payload.slice(-MAX_INTENTS).flatMap((entry: unknown) => {
      if (!entry || typeof entry !== "object") return [];
      const record = entry as Record<string, unknown>;
      const { tempSessionId, agentId, idempotencyKey, createdAt } = record;
      if (typeof tempSessionId !== "string" || !isTempSessionId(tempSessionId) || tempSessionId.length > 200
        || typeof agentId !== "string" || agentId.length > 200
        || typeof idempotencyKey !== "string" || !idempotencyKey.startsWith("session-create:") || idempotencyKey.length > 200
        || typeof createdAt !== "string" || createdAt.length > 40 || !Number.isFinite(Date.parse(createdAt))) return [];
      return [{ tempSessionId, agentId, idempotencyKey, createdAt }];
    });
  } catch {
    return [];
  }
}

function writeRecords(storage: RecoveryStorage | undefined, records: SessionCreateRecovery[]): void {
  try {
    storage?.setItem(SESSION_CREATE_RECOVERY_KEY, JSON.stringify(records.slice(-MAX_INTENTS)));
  } catch {
    // Storage restrictions must not block normal creation in this document.
  }
}

export function readSessionCreateRecovery(tempId: string, storage = sessionCreateRecoveryStorage()): SessionCreateRecovery | undefined {
  return readRecords(storage).find((entry) => entry.tempSessionId === tempId);
}

export function rememberSessionCreateRecovery(intent: SessionCreateRecovery, storage = sessionCreateRecoveryStorage()): void {
  // Allow-list on writes as well: callers may carry transient state or callbacks.
  const { tempSessionId, agentId, idempotencyKey, createdAt } = intent;
  writeRecords(storage, [...readRecords(storage).filter((entry) => entry.tempSessionId !== tempSessionId),
    { tempSessionId, agentId, idempotencyKey, createdAt }]);
}

export function forgetSessionCreateRecovery(tempId: string, expectedKey: string, storage = sessionCreateRecoveryStorage()): void {
  writeRecords(storage, readRecords(storage).filter((entry) => entry.tempSessionId !== tempId || entry.idempotencyKey !== expectedKey));
}

export function buildSessionCreateShell(intent: SessionCreateRecovery, title: string, agentDisplayName?: string): SessionDetail {
  return {
    id: intent.tempSessionId, title, agentId: intent.agentId, agentDisplayName,
    status: "idle", currentPhase: "ready", taskSummary: "",
    lastActive: intent.createdAt, updatedAt: intent.createdAt, createdAt: intent.createdAt,
    messages: [], defaultFileContext: "", previewTabs: [], activePreviewPath: "",
    changedFiles: [], readFiles: [], stopRequested: false, stopRequestedAt: "", stopReason: "",
    messageWindow: {
      mode: "window", totalMessages: 0, returnedMessages: 0, oldestMessageIndex: 0,
      newestMessageIndex: 0, hasEarlier: false, hasLater: false, transcriptScope: "window",
    },
  };
}
