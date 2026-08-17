export type RuntimeSceneEventFocusFilter = "all" | "user_action";

export function isUserActionRuntimeSceneEvent(event: {
  eventCode?: string;
  phase?: string;
}): boolean {
  const eventCode = String(event.eventCode ?? "").trim();
  if (eventCode.startsWith("browser.user_action.")) {
    return true;
  }
  return String(event.phase ?? "").trim() === "user_action";
}

export function matchesRuntimeSceneEventFocusFilter(
  event: { eventCode?: string; phase?: string },
  filter: RuntimeSceneEventFocusFilter,
): boolean {
  if (filter === "all") {
    return true;
  }
  return isUserActionRuntimeSceneEvent(event);
}

export function isUserActionStructuredLogRecord(record: Record<string, unknown>): boolean {
  const eventCode = String(record.eventCode ?? record.event_code ?? "").trim();
  if (eventCode.startsWith("browser.user_action.")) {
    return true;
  }
  return String(record.phase ?? "").trim() === "user_action";
}
