/**
 * Draft text for one conversation composer, held outside React state.
 *
 * The draft changes on every keystroke, so keeping it in the session view's
 * props re-rendered the whole timeline (virtualizer, row projections, markdown)
 * for one character. A composer island subscribes to this store instead, which
 * keeps the keystroke cost inside the composer subtree.
 *
 * Kept deliberately tiny: `useSyncExternalStore` needs a cached snapshot that
 * is referentially stable between notifications, so the value is stored once
 * and only replaced on an actual change.
 */
export type ComposerDraftStore = {
  getSnapshot: () => string;
  subscribe: (listener: () => void) => () => void;
  /** Replace the draft. A no-op write does not notify subscribers. */
  set: (next: string) => void;
};

export function createComposerDraftStore(initial = ""): ComposerDraftStore {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    getSnapshot: () => value,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    set: (next) => {
      const normalized = typeof next === "string" ? next : "";
      if (normalized === value) {
        return;
      }
      value = normalized;
      for (const listener of [...listeners]) {
        listener();
      }
    },
  };
}

/**
 * Follow an upstream draft reset the store cannot observe on its own.
 *
 * The store owns the keystroke text so the timeline never re-renders per
 * character. That also means a submit which clears the upstream draft leaves
 * the sent text sitting in the composer, because the store is only rebuilt
 * when the session or the edit target changes. Only an empty upstream value
 * is a reset: every other upstream change is a keystroke echo the store
 * already holds.
 */
export function syncComposerDraftStoreFromUpstream(
  store: ComposerDraftStore,
  upstream: string,
): boolean {
  if (upstream !== "") {
    return false;
  }
  if (store.getSnapshot() === "") {
    return false;
  }
  store.set("");
  return true;
}
/**
 * Stores currently mounted, keyed by session.
 *
 * The upstream sync above can only observe a draft that was mirrored before
 * the submit. Typing reaches `sessionDrafts` after the typing pause, so a
 * submit inside that window clears an upstream value that was already empty:
 * no state change, no effect, and the sent text stays in the composer while
 * the turn is already running. Registration gives the submit path a way to
 * reach the mounted store directly instead of inferring it from a diff.
 */
const registeredStores = new Map<string, Set<ComposerDraftStore>>();

export function registerComposerDraftStore(
  sessionId: string,
  store: ComposerDraftStore,
): () => void {
  const key = String(sessionId || "").trim();
  if (!key) {
    return () => {};
  }
  const bucket = registeredStores.get(key) ?? new Set<ComposerDraftStore>();
  bucket.add(store);
  registeredStores.set(key, bucket);
  return () => {
    const current = registeredStores.get(key);
    if (!current) {
      return;
    }
    current.delete(store);
    if (!current.size) {
      registeredStores.delete(key);
    }
  };
}

/**
 * Drop a submitted draft from the mounted composer. Text typed after the
 * submit is newer and must survive, so the store is cleared only while it
 * still holds exactly what was sent.
 */
export function clearRegisteredComposerDraft(sessionId: string, submitted: string): boolean {
  const stores = registeredStores.get(String(sessionId || "").trim());
  if (!stores?.size) {
    return false;
  }
  const expected = String(submitted ?? "").trim();
  let cleared = false;
  for (const store of [...stores]) {
    if (store.getSnapshot().trim() !== expected) {
      continue;
    }
    store.set("");
    cleared = true;
  }
  return cleared;
}

/**
 * Put a failed submission back into a composer that is still empty. Anything
 * the user typed while the request was in flight is newer and wins.
 */
export function restoreRegisteredComposerDraft(sessionId: string, submitted: string): boolean {
  const stores = registeredStores.get(String(sessionId || "").trim());
  if (!stores?.size || !String(submitted ?? "")) {
    return false;
  }
  let restored = false;
  for (const store of [...stores]) {
    if (store.getSnapshot() !== "") {
      continue;
    }
    store.set(submitted);
    restored = true;
  }
  return restored;
}

/** Test seam: the registry is module state, like the live draft registry. */
export function resetRegisteredComposerDraftsForTests(): void {
  registeredStores.clear();
}
