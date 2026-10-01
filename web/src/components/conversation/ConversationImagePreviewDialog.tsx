import { Download, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { VDialog } from "../vui";
import {
  clampImagePreviewOffset,
  clampImageScale,
  IMAGE_PREVIEW_DEFAULT_OFFSET,
  IMAGE_PREVIEW_MAX_SCALE,
  IMAGE_PREVIEW_MIN_SCALE,
  nextImagePreviewStepScale,
  panImagePreviewOffset,
  pinchImagePreviewScale,
  resetImagePreviewTransform,
  toggleImagePreviewScale,
  wheelImagePreviewScale,
  zoomImagePreviewAtAnchor,
  type ImagePreviewOffset,
  type ImagePreviewPoint,
  type ImagePreviewSize,
} from "./conversationImageZoom";
import styles from "./ConversationImagePreviewDialog.styles";

export type ConversationImagePreviewRequest = {
  src: string;
  alt: string;
  downloadUrl: string;
  downloadName: string | true;
};

type ConversationImagePreviewDialogProps = {
  image: ConversationImagePreviewRequest;
  lang: "zh" | "en";
  onClose: () => void;
};

type PreviewMeasurements = {
  imageSize: ImagePreviewSize;
  viewportSize: ImagePreviewSize;
};

export function ConversationImagePreviewDialog({
  image,
  lang,
  onClose,
}: ConversationImagePreviewDialogProps) {
  const downloadBaseLabel = lang === "zh" ? "下载图片" : "Download image";
  const downloadLabel = `${downloadBaseLabel}${lang === "zh" ? "：" : ": "}${image.alt}`;
  const closeLabel = lang === "zh" ? "关闭预览" : "Close preview";
  const description = lang === "zh"
    ? `正在预览图片：${image.alt}`
    : `Previewing image: ${image.alt}`;
  const zoomInLabel = lang === "zh" ? "放大图片" : "Zoom in";
  const zoomOutLabel = lang === "zh" ? "缩小图片" : "Zoom out";
  const resetZoomLabel = lang === "zh" ? "重置缩放" : "Reset zoom";
  const zoomLevelTitle = lang === "zh" ? "当前缩放" : "Current zoom";
  const zoomToolbarLabel = lang === "zh"
    ? "图片缩放控制"
    : "Image zoom controls";

  const [previewScale, setPreviewScale] = useState(1);
  const [previewOffset, setPreviewOffset] = useState<ImagePreviewOffset>(
    IMAGE_PREVIEW_DEFAULT_OFFSET,
  );
  const [isPanning, setIsPanning] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const pointersRef = useRef(new Map<number, ImagePreviewPoint>());
  const dragStartRef = useRef<{
    offset: ImagePreviewOffset;
    pointer: ImagePreviewPoint;
  } | null>(null);
  const pinchStartRef = useRef<{ distance: number; scale: number } | null>(null);
  // Latest-transform mirror so native (non-passive) listeners never read stale state.
  const transformRef = useRef({ scale: previewScale, offset: previewOffset });
  transformRef.current = { scale: previewScale, offset: previewOffset };

  const measurePreview =
    useCallback((): PreviewMeasurements | null => {
      const imageElement = imageRef.current;
      const viewportElement = viewportRef.current;
      if (!imageElement || !viewportElement) return null;
      const imageSize = {
        width: imageElement.offsetWidth,
        height: imageElement.offsetHeight,
      };
      const viewportSize = {
        width: viewportElement.clientWidth,
        height: viewportElement.clientHeight,
      };
      if (
        imageSize.width <= 0
        || imageSize.height <= 0
        || viewportSize.width <= 0
        || viewportSize.height <= 0
      ) {
        return null;
      }
      return { imageSize, viewportSize };
    }, []);

  const resetPreviewTransform = useCallback(() => {
    const viewportElement = viewportRef.current;
    if (viewportElement) {
      for (const pointerId of pointersRef.current.keys()) {
        if (viewportElement.hasPointerCapture(pointerId)) {
          viewportElement.releasePointerCapture(pointerId);
        }
      }
    }
    pointersRef.current.clear();
    dragStartRef.current = null;
    pinchStartRef.current = null;
    setIsPanning(false);
    setPreviewScale(1);
    setPreviewOffset({ x: 0, y: 0 });
  }, []);

  const applyPreviewZoom = useCallback(
    (nextScale: number, anchor?: ImagePreviewPoint | null) => {
      const targetScale = clampImageScale(nextScale);
      const measured = measurePreview();
      const current = transformRef.current;
      const baseOffset = anchor && measured
        ? zoomImagePreviewAtAnchor({
          offset: current.offset,
          scale: current.scale,
          nextScale: targetScale,
          anchor,
          viewportSize: measured.viewportSize,
        })
        : current.offset;
      setPreviewScale(targetScale);
      setPreviewOffset(
        measured
          ? clampImagePreviewOffset(
            baseOffset,
            targetScale,
            measured.imageSize,
            measured.viewportSize,
          )
          : baseOffset,
      );
    },
    [measurePreview],
  );

  const anchorFromEvent = useCallback(
    (clientX: number, clientY: number): ImagePreviewPoint | null => {
      const viewportElement = viewportRef.current;
      if (!viewportElement) return null;
      const rect = viewportElement.getBoundingClientRect();
      return { x: clientX - rect.left, y: clientY - rect.top };
    },
    [],
  );

  // Reset whenever the dialog shows a different image (or remounts).
  useEffect(() => {
    resetPreviewTransform();
  }, [image.src, resetPreviewTransform]);

  // React attaches root wheel listeners passively; a native non-passive
  // listener is required so preventDefault can stop page scroll behind the
  // lightbox while zooming.
  useEffect(() => {
    const viewportElement = viewportRef.current;
    if (!viewportElement) return;
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      const measured = measurePreview();
      if (!measured) return;
      const anchor = anchorFromEvent(event.clientX, event.clientY);
      const current = transformRef.current;
      const nextScale = wheelImagePreviewScale(current.scale, event.deltaY);
      const anchoredOffset = anchor
        ? zoomImagePreviewAtAnchor({
          offset: current.offset,
          scale: current.scale,
          nextScale,
          anchor,
          viewportSize: measured.viewportSize,
        })
        : current.offset;
      setPreviewScale(nextScale);
      setPreviewOffset(
        clampImagePreviewOffset(
          anchoredOffset,
          nextScale,
          measured.imageSize,
          measured.viewportSize,
        ),
      );
    };
    viewportElement.addEventListener("wheel", handleWheel, { passive: false });
    return () => viewportElement.removeEventListener("wheel", handleWheel);
  }, [anchorFromEvent, measurePreview]);

  // Keyboard zoom: +/- (and =/_) step through levels, 0 resets.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target
        && (target.isContentEditable
          || target.tagName === "INPUT"
          || target.tagName === "TEXTAREA"
          || target.tagName === "SELECT")
      ) {
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        applyPreviewZoom(
          nextImagePreviewStepScale(transformRef.current.scale, 1),
        );
      } else if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        applyPreviewZoom(
          nextImagePreviewStepScale(transformRef.current.scale, -1),
        );
      } else if (event.key === "0") {
        event.preventDefault();
        resetPreviewTransform();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [applyPreviewZoom, resetPreviewTransform]);

  // Keep the pan offset inside bounds when the window resizes.
  useEffect(() => {
    const handleResize = () => {
      const measured = measurePreview();
      if (!measured) return;
      setPreviewOffset((current) =>
        clampImagePreviewOffset(
          current,
          transformRef.current.scale,
          measured.imageSize,
          measured.viewportSize,
        ));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [measurePreview]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const pointer = { x: event.clientX, y: event.clientY };
    pointersRef.current.set(event.pointerId, pointer);
    if (pointersRef.current.size === 1) {
      dragStartRef.current = {
        offset: transformRef.current.offset,
        pointer,
      };
      pinchStartRef.current = null;
      setIsPanning(true);
      return;
    }
    const [first, second] = Array.from(pointersRef.current.values());
    if (!first || !second) return;
    const distance = Math.hypot(second.x - first.x, second.y - first.y);
    if (distance === 0) return;
    pinchStartRef.current = { distance, scale: transformRef.current.scale };
    dragStartRef.current = null;
    setIsPanning(false);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!pointersRef.current.has(event.pointerId)) return;
    pointersRef.current.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    });
    const pointers = Array.from(pointersRef.current.values());
    if (pointers.length >= 2) {
      const [first, second] = pointers;
      const pinchStart = pinchStartRef.current;
      const measured = measurePreview();
      if (!first || !second || !pinchStart || !measured) return;
      const distance = Math.hypot(second.x - first.x, second.y - first.y);
      const nextScale = pinchImagePreviewScale(
        pinchStart.scale,
        pinchStart.distance,
        distance,
      );
      const anchor = anchorFromEvent(
        (first.x + second.x) / 2,
        (first.y + second.y) / 2,
      );
      const current = transformRef.current;
      const anchoredOffset = anchor
        ? zoomImagePreviewAtAnchor({
          offset: current.offset,
          scale: current.scale,
          nextScale,
          anchor,
          viewportSize: measured.viewportSize,
        })
        : current.offset;
      setPreviewScale(nextScale);
      setPreviewOffset(
        clampImagePreviewOffset(
          anchoredOffset,
          nextScale,
          measured.imageSize,
          measured.viewportSize,
        ),
      );
      return;
    }
    const dragStart = dragStartRef.current;
    const pointer = pointers[0];
    const measured = measurePreview();
    if (!dragStart || !pointer || !measured) return;
    setPreviewOffset(
      clampImagePreviewOffset(
        panImagePreviewOffset(dragStart.offset, dragStart.pointer, pointer),
        transformRef.current.scale,
        measured.imageSize,
        measured.viewportSize,
      ),
    );
  };

  const handlePointerEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    // Release the drag capture explicitly; a stale capture keeps later
    // hover/click events hitting the viewport instead of overlay controls.
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    pointersRef.current.delete(event.pointerId);
    pinchStartRef.current = null;
    const remaining = Array.from(pointersRef.current.values())[0];
    dragStartRef.current = remaining
      ? { offset: transformRef.current.offset, pointer: remaining }
      : null;
    setIsPanning(Boolean(remaining));
  };

  const handleDoubleClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    applyPreviewZoom(
      toggleImagePreviewScale(transformRef.current.scale),
      anchorFromEvent(event.clientX, event.clientY),
    );
  };

  const isAtDefaultTransform =
    previewScale === 1
    && previewOffset.x === 0
    && previewOffset.y === 0;
  const zoomPercentLabel = `${Math.round(previewScale * 100)}%`;

  return (
    <VDialog
      open
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
      title={image.alt}
      description={description}
      size="xl"
      contentClassName={styles.imagePreviewDialog}
      aria-label={closeLabel}
      footer={(
        <div className={styles.imagePreviewFooter}>
          <div
            aria-label={zoomToolbarLabel}
            className={styles.zoomToolbar}
            role="group"
          >
            <button
              type="button"
              className={styles.zoomControlButton}
              disabled={previewScale <= IMAGE_PREVIEW_MIN_SCALE}
              title={zoomOutLabel}
              aria-label={zoomOutLabel}
              onClick={() =>
                applyPreviewZoom(
                  nextImagePreviewStepScale(previewScale, -1),
                )}
            >
              <ZoomOut size={14} aria-hidden="true" />
            </button>
            <span
              className={styles.zoomLevelLabel}
              title={zoomLevelTitle}
              aria-live="polite"
            >
              {zoomPercentLabel}
            </span>
            <button
              type="button"
              className={styles.zoomControlButton}
              disabled={previewScale >= IMAGE_PREVIEW_MAX_SCALE}
              title={zoomInLabel}
              aria-label={zoomInLabel}
              onClick={() =>
                applyPreviewZoom(
                  nextImagePreviewStepScale(previewScale, 1),
                )}
            >
              <ZoomIn size={14} aria-hidden="true" />
            </button>
            <button
              type="button"
              className={styles.zoomControlButton}
              disabled={isAtDefaultTransform}
              title={resetZoomLabel}
              aria-label={resetZoomLabel}
              onClick={resetPreviewTransform}
            >
              <RotateCcw size={14} aria-hidden="true" />
            </button>
          </div>
          <a
            className={styles.imageDownloadButton}
            href={image.downloadUrl}
            download={image.downloadName}
            title={downloadLabel}
            aria-label={downloadLabel}
          >
            <Download size={15} aria-hidden="true" />
            <span>{downloadBaseLabel}</span>
          </a>
        </div>
      )}
    >
      <div
        className={`${styles.imagePreviewViewport} ${
          isPanning ? styles.imagePreviewViewportGrabbing : ""
        }`}
        ref={viewportRef}
        onDoubleClick={handleDoubleClick}
        onPointerCancel={handlePointerEnd}
        onPointerDown={handlePointerDown}
        onLostPointerCapture={handlePointerEnd}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerEnd}
      >
        <img
          className={
            isPanning
              ? styles.imagePreviewLargePanning
              : styles.imagePreviewLarge
          }
          draggable={false}
          onLoad={resetPreviewTransform}
          ref={imageRef}
          src={image.src}
          alt={image.alt}
          style={{
            transform: `translate3d(${previewOffset.x}px, ${previewOffset.y}px, 0) scale(${previewScale})`,
          }}
        />
      </div>
    </VDialog>
  );
}
