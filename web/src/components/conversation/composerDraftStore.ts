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
