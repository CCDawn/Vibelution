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
};

export const ActiveTurnStreamStateContext = createContext<ActiveTurnStreamState>({});

export function useActiveTurnStreamState(): ActiveTurnStreamState {
  return useContext(ActiveTurnStreamStateContext);
}
