/**
 * Live composer draft text, readable synchronously outside React state.
 *
 * Why this exists: the workbench mirrored every keystroke into its own
 * `sessionDrafts` state, so one character re-rendered the whole chat route
 * (~90 ms per keystroke measured on a loaded session). The draft now lands here
 * on every keystroke — synchronously, no React work — and is mirrored into the
 * workbench state on a short debounce. Submit and edit paths read straight from
 * here, so they always see the exact text the user typed even when the mirror
 * has not caught up yet.
 *
 * The debounce is deliberately one-way: keystrokes never wait for React, and the
 * mirror only catches up once the user pauses. Consumers that must react on
 * every character (the composer island itself) read the per-composer store
 * instead; this module only serves the workbench-level mirrors.
 */
const liveDrafts = new Map<string, string>();
const mirrorTimers = new Map<string, ReturnType<typeof setTimeout>>();

/** Long enough that a normal typing burst never reaches the React mirror. */
const MIRROR_DELAY_MS = 400;

function normalizeSessionId(sessionId: string | null | undefined): string {
  return String(sessionId || "").trim();
}

/** Remember the newest draft text for a session. */
export function writeLiveComposerDraft(
  sessionId: string | null | undefined,
  value: string,
): void {
  const id = normalizeSessionId(sessionId);
  if (!id) {
    return;
  }
  liveDrafts.set(id, typeof value === "string" ? value : "");
}

/**
 * Newest draft text for a session.
 *
 * Returns `null` rather than `""` when nothing was typed yet, so a caller can
 * fall back to the React mirror instead of clobbering an edit-mode prefill.
 */
export function readLiveComposerDraft(sessionId: string | null | undefined): string | null {
  const id = normalizeSessionId(sessionId);
  if (!id) {
    return null;
  }
  return liveDrafts.has(id) ? (liveDrafts.get(id) as string) : null;
}

/** Draft for paths that need a string even before the first keystroke. */
export function liveComposerDraftOr(
  sessionId: string | null | undefined,
  fallback: string,
): string {
  const live = readLiveComposerDraft(sessionId);
  return live === null ? fallback : live;
}

/**
 * Mirror the live draft into workbench state after the typing pause.
 *
 * `apply` is the setter itself; it is called with the newest text, so a stale
 * timer can never overwrite a newer draft (the timer is re-armed per keystroke
 * and only the last one runs).
 */
export function scheduleLiveDraftMirror(
  sessionId: string | null | undefined,
  value: string,
  apply: (sessionId: string, value: string) => void,
): void {
  const id = normalizeSessionId(sessionId);
  if (!id) {
    return;
  }
  const pending = mirrorTimers.get(id);
  if (pending) {
    clearTimeout(pending);
  }
  mirrorTimers.set(
    id,
    setTimeout(() => {
      mirrorTimers.delete(id);
      apply(id, value);
    }, MIRROR_DELAY_MS),
  );
}

/** Flush a pending mirror right now (submit, blur, session switch). */
export function flushLiveDraftMirror(
  sessionId: string | null | undefined,
  apply: (sessionId: string, value: string) => void,
): void {
  const id = normalizeSessionId(sessionId);
  if (!id) {
    return;
  }
  const pending = mirrorTimers.get(id);
  if (!pending) {
    return;
  }
  clearTimeout(pending);
  mirrorTimers.delete(id);
  apply(id, liveDrafts.get(id) ?? "");
}

/** Keep a session's draft when its id is rekeyed (create → real session). */
export function moveLiveComposerDraft(
  fromSessionId: string | null | undefined,
  toSessionId: string | null | undefined,
): void {
  const from = normalizeSessionId(fromSessionId);
  const to = normalizeSessionId(toSessionId);
  if (!from || !to || from === to || !liveDrafts.has(from)) {
    return;
  }
  liveDrafts.set(to, liveDrafts.get(from) as string);
  liveDrafts.delete(from);
}

/** Drop a session's draft (a submit consumed it, or the session is gone). */
/**
 * Drop the live draft only when it still holds what was submitted. Text typed
 * while the request was in flight is newer and must survive.
 */
export function clearLiveComposerDraftIfEquals(sessionId: string, expected: string) {
  const live = readLiveComposerDraft(sessionId);
  if (live !== null && live.trim() === String(expected || "").trim()) {
    clearLiveComposerDraft(sessionId);
  }
}

export function clearLiveComposerDraft(sessionId: string | null | undefined): void {
  const id = normalizeSessionId(sessionId);
  if (!id) {
    return;
  }
  liveDrafts.delete(id);
  const pending = mirrorTimers.get(id);
  if (pending) {
    clearTimeout(pending);
    mirrorTimers.delete(id);
  }
}

/** Test seam: timers and registry are module state. */
export function resetLiveComposerDraftsForTests(): void {
  for (const timer of mirrorTimers.values()) {
    clearTimeout(timer);
  }
  mirrorTimers.clear();
  liveDrafts.clear();
}
