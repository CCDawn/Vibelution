import type { SessionDetail } from "../../api/types";
import { latestUserTurnId } from "../chatActiveTurnLayer";

function clean(value: unknown) {
  return String(value ?? "").trim();
}

export function resolveSessionStopTurnId(detail: SessionDetail | undefined) {
  return clean(detail?.activeTurnId) || latestUserTurnId(detail);
}

export function sessionStopRequestBody(turnId: string) {
  const normalizedTurnId = clean(turnId);
  if (!normalizedTurnId) {
    return undefined;
  }
  return JSON.stringify({ turnId: normalizedTurnId });
}
