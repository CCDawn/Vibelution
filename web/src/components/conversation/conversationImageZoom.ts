/**
 * Pure math for the conversation image lightbox zoom/pan interactions.
 *
 * No React, no DOM: every function takes plain numbers/objects so the
 * transform model can be unit-tested in isolation. The preview dialog owns
 * state and event plumbing; this module owns the arithmetic:
 *
 * - Scale is a unitless multiplier on the image's laid-out (object-contain) size.
 * - Offset is a translate3d applied BEFORE scale (center origin), expressed in
 *   viewport pixels relative to the viewport center — matching CSS
 *   `transform: translate3d(x, y, 0) scale(s)` with the default 50% 50% origin.
 * - All inputs are sanitized: non-finite numbers degrade to safe defaults
 *   instead of poisoning the transform state.
 */

export type ImagePreviewOffset = { x: number; y: number };
export type ImagePreviewPoint = { x: number; y: number };
export type ImagePreviewSize = { width: number; height: number };

export const IMAGE_PREVIEW_MIN_SCALE = 0.25;
export const IMAGE_PREVIEW_MAX_SCALE = 8;
export const IMAGE_PREVIEW_DEFAULT_SCALE = 1;

/** Discrete zoom levels used by the toolbar buttons and keyboard steps. */
export const IMAGE_PREVIEW_SCALE_STEPS: readonly number[] = [
  0.25,
  0.5,
  1,
  2,
  4,
  8,
];

/** Scale jumped to by double-click when currently below it. */
export const IMAGE_PREVIEW_DOUBLE_CLICK_SCALE = 2;

/**
 * Exponential wheel response: one typical notch (deltaY ≈ ±100) multiplies the
 * scale by e^(±0.25) ≈ ×1.28, and trackpad granular deltas compose smoothly.
 */
export const IMAGE_PREVIEW_WHEEL_INTENSITY = 0.0025;

export const IMAGE_PREVIEW_DEFAULT_OFFSET: Readonly<ImagePreviewOffset> =
  Object.freeze({ x: 0, y: 0 });

function clampToRange(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Clamp any candidate scale into the 25%-800% lightbox range. */
export function clampImageScale(scale: number): number {
  if (Number.isNaN(scale)) {
    return IMAGE_PREVIEW_DEFAULT_SCALE;
  }
  return clampToRange(scale, IMAGE_PREVIEW_MIN_SCALE, IMAGE_PREVIEW_MAX_SCALE);
}

/**
 * Next/previous discrete zoom level relative to the current scale.
 * Continuous values between steps round outward (1.4 → 2 up, → 1 down);
 * at the range edges the step clamps to the boundary.
 */
export function nextImagePreviewStepScale(
  scale: number,
  direction: 1 | -1,
): number {
  const current = clampImageScale(scale);
  if (direction === 1) {
    const next = IMAGE_PREVIEW_SCALE_STEPS.find(
      (step) => step > current + Number.EPSILON,
    );
    return next ?? IMAGE_PREVIEW_MAX_SCALE;
  }
  const previous = [...IMAGE_PREVIEW_SCALE_STEPS]
    .reverse()
    .find((step) => step < current - Number.EPSILON);
  return previous ?? IMAGE_PREVIEW_MIN_SCALE;
}

/** Wheel zoom: exponential response from the wheel delta, clamped. */
export function wheelImagePreviewScale(scale: number, deltaY: number): number {
  const current = clampImageScale(scale);
  const delta = Number.isFinite(deltaY) ? deltaY : 0;
  if (delta === 0) return current;
  return clampImageScale(current * Math.exp(-delta * IMAGE_PREVIEW_WHEEL_INTENSITY));
}

/**
 * Pinch zoom: scale multiplied by the ratio of the current two-finger
 * distance to the distance when the pinch started, clamped.
 */
export function pinchImagePreviewScale(
  startScale: number,
  startDistance: number,
  currentDistance: number,
): number {
  const base = clampImageScale(startScale);
  if (
    !Number.isFinite(startDistance)
    || !Number.isFinite(currentDistance)
    || startDistance <= 0
    || currentDistance <= 0
  ) {
    return base;
  }
  return clampImageScale(base * (currentDistance / startDistance));
}

/**
 * Clamp a pan offset so the zoomed image cannot be dragged fully out of view.
 * Allowed range is ±(scaledImageSize - viewportSize) / 2 per axis; when the
 * scaled image is smaller than the viewport the offset is locked to centered.
 */
export function clampImagePreviewOffset(
  offset: ImagePreviewOffset,
  scale: number,
  imageSize: ImagePreviewSize,
  viewportSize: ImagePreviewSize,
): ImagePreviewOffset {
  const clampedScale = clampImageScale(scale);
  const imageWidth = Number.isFinite(imageSize.width) ? imageSize.width : 0;
  const imageHeight = Number.isFinite(imageSize.height) ? imageSize.height : 0;
  const viewportWidth = Number.isFinite(viewportSize.width)
    ? viewportSize.width
    : 0;
  const viewportHeight = Number.isFinite(viewportSize.height)
    ? viewportSize.height
    : 0;
  const maxX = Math.max(
    0,
    (imageWidth * clampedScale - viewportWidth) / 2,
  );
  const maxY = Math.max(
    0,
    (imageHeight * clampedScale - viewportHeight) / 2,
  );
  const rawX = Number.isFinite(offset.x) ? offset.x : 0;
  const rawY = Number.isFinite(offset.y) ? offset.y : 0;
  return {
    x: maxX === 0 ? 0 : clampToRange(rawX, -maxX, maxX),
    y: maxY === 0 ? 0 : clampToRange(rawY, -maxY, maxY),
  };
}

/**
 * Zoom keeping the image point under `anchor` (viewport-local pixels) fixed on
 * screen. With center-origin transform, the image coordinate under a
 * center-relative viewport point p is (p - offset) / scale; solving
 * offset' = p - u * nextScale keeps that point anchored while zooming.
 */
export function zoomImagePreviewAtAnchor(params: {
  offset: ImagePreviewOffset;
  scale: number;
  nextScale: number;
  /** Viewport-local anchor (top-left origin of the viewport box). */
  anchor: ImagePreviewPoint;
  viewportSize: ImagePreviewSize;
}): ImagePreviewOffset {
  const current = clampImageScale(params.scale);
  const next = clampImageScale(params.nextScale);
  const rawX = Number.isFinite(params.offset.x) ? params.offset.x : 0;
  const rawY = Number.isFinite(params.offset.y) ? params.offset.y : 0;
  if (next === current) {
    return { x: rawX, y: rawY };
  }
  const centerX = Number.isFinite(params.viewportSize.width)
    ? params.viewportSize.width / 2
    : 0;
  const centerY = Number.isFinite(params.viewportSize.height)
    ? params.viewportSize.height / 2
    : 0;
  const pointerX = Number.isFinite(params.anchor.x)
    ? params.anchor.x - centerX
    : 0;
  const pointerY = Number.isFinite(params.anchor.y)
    ? params.anchor.y - centerY
    : 0;
  const ratio = next / current;
  return {
    x: pointerX - (pointerX - rawX) * ratio,
    y: pointerY - (pointerY - rawY) * ratio,
  };
}

/** Pan delta from a drag gesture start, unclamped (clamp at the call site). */
export function panImagePreviewOffset(
  startOffset: ImagePreviewOffset,
  startPointer: ImagePreviewPoint,
  currentPointer: ImagePreviewPoint,
): ImagePreviewOffset {
  const baseX = Number.isFinite(startOffset.x) ? startOffset.x : 0;
  const baseY = Number.isFinite(startOffset.y) ? startOffset.y : 0;
  const startX = Number.isFinite(startPointer.x) ? startPointer.x : 0;
  const startY = Number.isFinite(startPointer.y) ? startPointer.y : 0;
  const endX = Number.isFinite(currentPointer.x) ? currentPointer.x : 0;
  const endY = Number.isFinite(currentPointer.y) ? currentPointer.y : 0;
  return {
    x: baseX + (endX - startX),
    y: baseY + (endY - startY),
  };
}

/**
 * Double-click toggle: below the double-click level zoom in to it (anchored at
 * the click point by the caller), otherwise fall back to 1x.
 */
export function toggleImagePreviewScale(scale: number): number {
  const current = clampImageScale(scale);
  return current >= IMAGE_PREVIEW_DOUBLE_CLICK_SCALE - Number.EPSILON
    ? IMAGE_PREVIEW_DEFAULT_SCALE
    : IMAGE_PREVIEW_DOUBLE_CLICK_SCALE;
}

/** Fresh transform state: fit scale (1x) and centered offset. */
export function resetImagePreviewTransform(): {
  scale: number;
  offset: ImagePreviewOffset;
} {
  return {
    scale: IMAGE_PREVIEW_DEFAULT_SCALE,
    offset: { ...IMAGE_PREVIEW_DEFAULT_OFFSET },
  };
}
