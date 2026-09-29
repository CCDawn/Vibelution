import { createContext, useContext } from "react";

/**
 * Transport-level state for the guarded direct-session stream, projected into
 * the active-turn status presentation. It is the SAME state owned by
 * `useSessionDetailStream` — this context is only the transport across the
 * ConversationView boundary, never a second derivation channel.
 *
 * tri-state: `true` healthy, `false` reconnect loop, `undefined` unknown
 * (surfaces without a guarded stream, e.g. supervised panels).
 */
export type ActiveTurnStreamState = {
  streamConnected?: boolean;
  /** Epoch ms when the current reconnect loop started (drives the duration counter). */
  streamDisconnectedSinceMs?: number | null;
  /** Epoch ms of the last applied assistant delta for the viewed session. */
  lastAssistantDeltaAtMs?: number | null;
  /**
   * Live epoch-ms read of the last applied stream event for the viewed session
   * (an applied delta frame or an applied detail reconcile — received is not
   * applied). A getter on purpose: the stamps advance on every applied frame
   * while this context object itself does not re-render, so the note's
   * per-second tick pulls the fresh value through the closure.
   */
  lastStreamActivityAtMs?: () => number | null;
  /**
   * Manual "reconnect now" action wired from `useSessionDetailStream` (the sole
   * stream owner). Absent on surfaces without a guarded stream; the disconnect
   * advisory only renders its reconnect button when this exists.
   */
  reconnectSessionStream?: () => void;
};

export const ActiveTurnStreamStateContext = createContext<ActiveTurnStreamState>({});

export function useActiveTurnStreamState(): ActiveTurnStreamState {
  return useContext(ActiveTurnStreamStateContext);
}
