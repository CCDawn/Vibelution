/**
 * In-memory create attempt for the current document.
 *
 * The recovery record only stores identity. Send needs to know whether that
 * shell is still waiting on the server or has already failed, and a reload
 * starts with no module state until the shell is restored.
 */

export type SessionCreateAttemptState = "pending" | "failed";

const attempts = new Map<string, SessionCreateAttemptState>();

export function markSessionCreateAttempt(sessionId: string, state: SessionCreateAttemptState): void {
  const id = String(sessionId || "").trim();
  if (!id) {
    return;
  }
  attempts.set(id, state);
}

export function clearSessionCreateAttempt(sessionId: string): void {
  const id = String(sessionId || "").trim();
  if (!id) {
    return;
  }
  attempts.delete(id);
}

export function sessionCreateAttemptState(sessionId: string): SessionCreateAttemptState | undefined {
  const id = String(sessionId || "").trim();
  return id ? attempts.get(id) : undefined;
}

export function resetSessionCreateAttemptsForTests(): void {
  attempts.clear();
}

export function tempSessionSendBlockedMessage(state: SessionCreateAttemptState | undefined, lang: string): string {
  if (state === "failed") {
    return lang === "zh"
      ? "会话还没创建成功。请再点一次新建会话，这段草稿会保留。"
      : "The session was not created. Start a new session again; this draft stays.";
  }
  return lang === "zh"
    ? "新会话正在创建，请稍候再发送。"
    : "The new session is still being created. Please wait a moment before sending.";
}
