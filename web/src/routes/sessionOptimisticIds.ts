/**
 * Client-only session identities used for optimistic create (ChatGPT-style).
 * Server never mints these; they are rebased to real ids on create success.
 */

const TEMP_SESSION_PREFIX = "temp-session-";

export function createTempSessionId(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) {
    return `${TEMP_SESSION_PREFIX}${randomUuid}`;
  }
  return `${TEMP_SESSION_PREFIX}${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function isTempSessionId(sessionId: string | null | undefined): boolean {
  return String(sessionId || "").trim().startsWith(TEMP_SESSION_PREFIX);
}
