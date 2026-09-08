import type { PetAnimationState } from "../../api/types/petActivity";
export type Live2dStatus = "loading" | "ready" | "error";
export interface Live2dController {
  setState(state: PetAnimationState): void;
  dispose(): void;
}
export interface Live2dModule {
  createLive2dController(canvas: HTMLCanvasElement, state: PetAnimationState, report: (status: Live2dStatus) => void): Live2dController;
}
