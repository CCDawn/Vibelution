import type { PetAnimationState } from "../../api/types/petActivity";

export type DesktopPetCharacterId = "xiaoluo" | "dafeiyu";

export type WhaleRigState =
  | "idle"
  | "waiting"
  | "failed"
  | "thinking"
  | "reading"
  | "running"
  | "verifying"
  | "answering"
  | "jumping";

const WHALE_RIG_STATE_BY_ACTIVITY: Record<PetAnimationState, WhaleRigState> = {
  idle: "idle",
  waiting: "waiting",
  alert: "failed",
  thinking: "thinking",
  reading: "reading",
  tooling: "running",
  verifying: "verifying",
  answering: "answering",
  celebrating: "jumping",
};

export function nextDesktopPetCharacter(current: DesktopPetCharacterId): DesktopPetCharacterId {
  return current === "xiaoluo" ? "dafeiyu" : "xiaoluo";
}

export function whaleRigStateForPetAnimation(state: PetAnimationState): WhaleRigState {
  return WHALE_RIG_STATE_BY_ACTIVITY[state];
}
