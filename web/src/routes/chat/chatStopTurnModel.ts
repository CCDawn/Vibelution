import type { SessionDetail } from "../../api/types";
import { latestUserTurnId } from "../chatActiveTurnLayer";

function clean(value: unknown) {
  return String(value ?? "").trim();
}

export function resolveSessionStopTurnId(
  detail: SessionDetail | undefined,
  activeLayerTurnId = "",
) {
  const activeTurnId = clean(activeLayerTurnId);
  if (activeTurnId) {
    return activeTurnId.startsWith("optimistic-") ? "" : activeTurnId;
  }
  return clean(detail?.activeTurnId) || latestUserTurnId(detail);
}

export function sessionStopRequestBody(turnId: string) {
  const normalizedTurnId = clean(turnId);
  if (!normalizedTurnId) {
    return undefined;
  }
  return JSON.stringify({ turnId: normalizedTurnId });
}
