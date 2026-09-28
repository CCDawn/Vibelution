import {
  createContext,
  useContext,
  useSyncExternalStore,
  type Dispatch,
  type MutableRefObject,
  type ReactNode,
  type SetStateAction,
} from "react";

import type { ActiveTurnLayerState } from "../chatActiveTurnLayer";

/**
 * External store that owns the per-session active-turn layers.
 *
 * Assistant delta frames commit multiple times per second while a turn streams.
 * Keeping that state in `ChatCodingRouteWorkbench`'s own `useState` re-rendered
 * the entire workbench (rails, tabs, queries, composer) on every committed
 * frame. This store moves the ownership out of React state so only components
 * that actually subscribe re-render:
 *
 * - Writers keep the exact `Dispatch<SetStateAction<...>>` contract they had
 *   with `useState` (the SSE stream and composer mutations are untouched).
 * - `ChatConversationComposerBridge` subscribes per session id and projects the
 *   streaming message, so the per-frame render scope ends at ConversationView.
 * - The workbench subscribes only to primitive signals (settle flag, terminal
 *   refresh key, running-session key) that change rarely.
 * - `activeTurnLayersBySessionRef` stays available for code that reads the
 *   latest committed layers outside render (frame-paint telemetry). The store
 *   updates it synchronously with every commit, which is strictly fresher than
 *   the previous render-time ref sync.
 *
 * One store instance lives for the lifetime of a mounted workbench (route
 * remount resets layers, matching the previous `useState({})` semantics); it is
 * shared with descendants through `ActiveTurnLayersStoreProvider`.
 */
export type ActiveTurnLayersState = Record<string, ActiveTurnLayerState>;

export type ActiveTurnLayersStore = {
  getSnapshot: () => ActiveTurnLayersState;
  subscribe: (listener: () => void) => () => void;
  setActiveTurnLayersBySession: Dispatch<SetStateAction<ActiveTurnLayersState>>;
  /** Latest committed state, updated synchronously on every commit. */
  activeTurnLayersBySessionRef: MutableRefObject<ActiveTurnLayersState>;
};

const NOOP_SUBSCRIBE = () => () => {};
const readNoLayer = () => undefined;
const readNoSignal = () => "";
const readNoFlag = () => false;

export function createActiveTurnLayersStore(): ActiveTurnLayersStore {
  let state: ActiveTurnLayersState = {};
  const listeners = new Set<() => void>();
  const ref: MutableRefObject<ActiveTurnLayersState> = { current: state };
  const store: ActiveTurnLayersStore = {
    getSnapshot: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setActiveTurnLayersBySession(action) {
      const next = typeof action === "function" ? action(state) : action;
      // Reference-equal results (updater returned the same state) must not
      // notify: every `setActiveTurnLayerForSession` no-op stays a no-op.
      if (next === state) {
        return;
      }
      state = next;
      ref.current = next;
      const notified = Array.from(listeners);
      for (const listener of notified) {
        listener();
      }
    },
    activeTurnLayersBySessionRef: ref,
  };
  return store;
}

const ActiveTurnLayersStoreContext = createContext<ActiveTurnLayersStore | null>(null);

export function ActiveTurnLayersStoreProvider({
  store,
  children,
}: {
  store: ActiveTurnLayersStore;
  children: ReactNode;
}) {
  return (
    <ActiveTurnLayersStoreContext.Provider value={store}>
      {children}
    </ActiveTurnLayersStoreContext.Provider>
  );
}

/** Returns null outside a provider (surfaces that pass layers by props only). */
export function useActiveTurnLayersStore(): ActiveTurnLayersStore | null {
  return useContext(ActiveTurnLayersStoreContext);
}

/**
 * Subscribes to the layer of exactly one session. The layer object identity is
 * stable unless that session's layer is replaced, so unrelated sessions'
 * streaming frames never re-render the subscriber.
 */
export function useActiveTurnLayerForSession(
  sessionId: string | null | undefined,
): ActiveTurnLayerState | undefined {
  const store = useContext(ActiveTurnLayersStoreContext);
  const sessionKey = String(sessionId || "");
  return useSyncExternalStore(
    store?.subscribe ?? NOOP_SUBSCRIBE,
    store ? () => store.getSnapshot()[sessionKey] : readNoLayer,
  );
}

/**
 * Primitive-valued selector subscription for the workbench. `select` must be
 * referentially stable (wrap in `useCallback`) and return a string; the caller
 * only re-renders when the selected primitive actually changes.
 */
export function useActiveTurnLayersSignal(
  select: (state: ActiveTurnLayersState) => string,
): string {
  const store = useContext(ActiveTurnLayersStoreContext);
  const getSnapshot = store ? () => select(store.getSnapshot()) : readNoSignal;
  return useSyncExternalStore(store?.subscribe ?? NOOP_SUBSCRIBE, getSnapshot);
}

/**
 * Boolean variant of {@link useActiveTurnLayersSignal} for settle flags.
 * `select` must be referentially stable (wrap in `useCallback`).
 */
export function useActiveTurnLayersSignalFlag(
  select: (state: ActiveTurnLayersState) => boolean,
): boolean {
  const store = useContext(ActiveTurnLayersStoreContext);
  const getSnapshot = store ? () => select(store.getSnapshot()) : readNoFlag;
  return useSyncExternalStore(store?.subscribe ?? NOOP_SUBSCRIBE, getSnapshot);
}
