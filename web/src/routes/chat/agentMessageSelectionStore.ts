import { useSyncExternalStore } from "react";

// Presentation selection only. Message bodies and the current chat remain owned
// by their existing query cache and committed route respectively.
let selectedMessageId: string | null = null;
let historyLimit = 30;
const listeners = new Set<() => void>();
export function selectAgentMessage(id: string | null) {
  if (selectedMessageId === id) return;
  selectedMessageId = id;
  listeners.forEach((listener) => listener());
}
export function useAgentMessageSelection() {
  return useSyncExternalStore((listener) => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, () => selectedMessageId, () => null);
}
export function loadMoreAgentMessages() {
  historyLimit = Math.min(300, historyLimit + 30);
  listeners.forEach((listener) => listener());
}
export function useAgentMessageHistoryLimit() {
  return useSyncExternalStore((listener) => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, () => historyLimit, () => 30);
}
