export type DesktopPetDragPoint = {
  screenX: number;
  screenY: number;
};

export type DesktopPetDragBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type DesktopPetWindowDrag = {
  pointerStart: DesktopPetDragPoint;
  windowStart: DesktopPetDragBounds;
};

export function isDesktopPetDragPoint(value: unknown): value is DesktopPetDragPoint {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const point = value as Record<string, unknown>;
  return Number.isFinite(point.screenX) && Number.isFinite(point.screenY);
}

export function beginDesktopPetWindowDrag(
  pointerStart: DesktopPetDragPoint,
  windowStart: DesktopPetDragBounds,
): DesktopPetWindowDrag {
  return {
    pointerStart: { ...pointerStart },
    windowStart: { ...windowStart },
  };
}

export function desktopPetWindowBoundsAt(
  drag: DesktopPetWindowDrag,
  pointer: DesktopPetDragPoint,
): DesktopPetDragBounds {
  return {
    x: drag.windowStart.x + Math.round(pointer.screenX - drag.pointerStart.screenX),
    y: drag.windowStart.y + Math.round(pointer.screenY - drag.pointerStart.screenY),
    width: drag.windowStart.width,
    height: drag.windowStart.height,
  };
}
