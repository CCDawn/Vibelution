export type DesktopPetDragPoint = {
  screenX: number;
  screenY: number;
};

export type DesktopPetDragState = {
  pointerId: number;
  start: DesktopPetDragPoint;
  last: DesktopPetDragPoint;
  moved: boolean;
};

export type DesktopPetDragUpdate = {
  state: DesktopPetDragState;
  delta: DesktopPetDragPoint | null;
};

export const DESKTOP_PET_DRAG_THRESHOLD_PX = 4;

export function beginDesktopPetDrag(pointerId: number, point: DesktopPetDragPoint): DesktopPetDragState {
  return {
    pointerId,
    start: point,
    last: point,
    moved: false,
  };
}

export function updateDesktopPetDrag(
  state: DesktopPetDragState,
  pointerId: number,
  point: DesktopPetDragPoint,
): DesktopPetDragUpdate | null {
  if (pointerId !== state.pointerId) {
    return null;
  }

  const crossedThreshold = state.moved || Math.hypot(
    point.screenX - state.start.screenX,
    point.screenY - state.start.screenY,
  ) >= DESKTOP_PET_DRAG_THRESHOLD_PX;
  if (!crossedThreshold) {
    return { state, delta: null };
  }

  const delta = {
    screenX: point.screenX - state.last.screenX,
    screenY: point.screenY - state.last.screenY,
  };
  return {
    state: {
      ...state,
      last: point,
      moved: true,
    },
    delta: delta.screenX === 0 && delta.screenY === 0 ? null : delta,
  };
}
