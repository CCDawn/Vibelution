export type PetWindowBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type DisplayWorkArea = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export const PET_WINDOW_WIDTH = 320;
export const PET_WINDOW_HEIGHT = 410;
export const PET_WINDOW_MARGIN = 18;

export function defaultPetWindowBounds(workArea: DisplayWorkArea): PetWindowBounds {
  return {
    x: workArea.x + Math.max(0, workArea.width - PET_WINDOW_WIDTH - PET_WINDOW_MARGIN),
    y: workArea.y + Math.max(0, workArea.height - PET_WINDOW_HEIGHT - PET_WINDOW_MARGIN),
    width: PET_WINDOW_WIDTH,
    height: PET_WINDOW_HEIGHT,
  };
}

export function clampPetWindowBounds(
  candidate: Pick<PetWindowBounds, "x" | "y">,
  workArea: DisplayWorkArea,
): PetWindowBounds {
  const maxX = workArea.x + Math.max(0, workArea.width - PET_WINDOW_WIDTH);
  const maxY = workArea.y + Math.max(0, workArea.height - PET_WINDOW_HEIGHT);
  return {
    x: Math.min(maxX, Math.max(workArea.x, Math.round(candidate.x))),
    y: Math.min(maxY, Math.max(workArea.y, Math.round(candidate.y))),
    width: PET_WINDOW_WIDTH,
    height: PET_WINDOW_HEIGHT,
  };
}
