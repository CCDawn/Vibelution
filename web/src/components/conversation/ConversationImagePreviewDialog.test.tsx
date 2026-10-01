import { existsSync } from "node:fs";

import { describe, expect, it } from "vitest";

import dialogSource from "./ConversationImagePreviewDialog.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import zoomSource from "./conversationImageZoom.ts?raw";
import styles from "./ConversationImagePreviewDialog.styles";

describe("ConversationImagePreviewDialog", () => {
  it("keeps the image preview dialog out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./ConversationImagePreviewDialog.tsx", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./ConversationImagePreviewDialog"');
    expect(conversationViewSource).not.toContain("className={styles.imagePreviewOverlay}");
    expect(conversationViewSource).not.toContain("className={styles.imagePreviewDialog}");
    expect(conversationViewSource).not.toContain("className={styles.imagePreviewToolbar}");
  });

  it("hosts preview on VDialog with download footer and viewport clamp", () => {
    expect(dialogSource).toContain("<VDialog");
    expect(dialogSource).toContain("onOpenChange=");
    expect(dialogSource).toContain("contentClassName={styles.imagePreviewDialog}");
    expect(dialogSource).toContain("image.downloadUrl");
    expect(dialogSource).toContain("download={image.downloadName}");
    expect(dialogSource).toContain("downloadBaseLabel");
    expect(dialogSource).toContain("styles.imagePreviewLarge");
    expect(dialogSource).not.toContain("createPortal(");
    expect(dialogSource).not.toContain("imagePreviewOverlay");
    expect(styles.imagePreviewDialog).toContain("w-[min(100vw-2rem,72rem)]");
    expect(styles.imagePreviewDialog).toContain("100dvh");
    expect(styles.imagePreviewLarge).toContain("max-h-[calc(100dvh-10rem)]");
    expect(styles.imagePreviewLarge).toContain("object-contain");
    expect(styles.imageDownloadButton).toContain("inline-flex");
  });

  it("keeps zoom math in the pure conversationImageZoom module", () => {
    expect(dialogSource).toContain('from "./conversationImageZoom"');
    expect(zoomSource).not.toContain('from "react"');
    expect(zoomSource).not.toContain("useState");
    expect(zoomSource).toContain("IMAGE_PREVIEW_MIN_SCALE = 0.25");
    expect(zoomSource).toContain("IMAGE_PREVIEW_MAX_SCALE = 8");
    expect(zoomSource).toContain("clampImagePreviewOffset");
    expect(zoomSource).toContain("zoomImagePreviewAtAnchor");
    expect(zoomSource).toContain("toggleImagePreviewScale");
    expect(zoomSource).toContain("resetImagePreviewTransform");
  });

  it("wires wheel zoom, pointer pan/pinch, double-click and keyboard reset", () => {
    // Wheel zoom must attach a non-passive native listener (React root wheel
    // listeners are passive, so onWheel preventDefault cannot stop page scroll).
    expect(dialogSource).toContain('addEventListener("wheel", handleWheel, { passive: false })');
    expect(dialogSource).toContain("event.preventDefault()");
    // Pointer capture drag + two-finger pinch.
    expect(dialogSource).toContain("setPointerCapture");
    expect(dialogSource).toContain("releasePointerCapture");
    expect(dialogSource).toContain("pinchImagePreviewScale");
    expect(dialogSource).toContain("panImagePreviewOffset");
    // Double-click toggle between 1x and the anchored zoom level.
    expect(dialogSource).toContain("onDoubleClick");
    expect(dialogSource).toContain("toggleImagePreviewScale");
    // Reset on image swap and on load.
    expect(dialogSource).toContain("[image.src, resetPreviewTransform]");
    expect(dialogSource).toContain("onLoad={resetPreviewTransform}");
    // Toolbar: zoom out / percent / zoom in / reset next to the download link.
    expect(dialogSource).toContain("styles.zoomToolbar");
    expect(dialogSource).toContain("styles.zoomControlButton");
    expect(dialogSource).toContain("styles.zoomLevelLabel");
    expect(dialogSource).toContain("aria-live=\"polite\"");
    expect(dialogSource).toContain('aria-label={zoomInLabel}');
    expect(dialogSource).toContain('aria-label={zoomOutLabel}');
    expect(dialogSource).toContain('aria-label={resetZoomLabel}');
    // Keyboard: +/- step, 0 resets.
    expect(dialogSource).toContain('event.key === "0"');
    expect(dialogSource).toContain('event.key === "+"');
    expect(dialogSource).toContain('event.key === "-"');
  });

  it("keeps the transform viewport clipped and motion-reduction aware", () => {
    expect(styles.imagePreviewViewport).toContain("touch-none");
    expect(styles.imagePreviewViewport).toContain("overflow-hidden");
    expect(styles.imagePreviewViewport).toContain("cursor-grab");
    expect(styles.imagePreviewLarge).toContain("motion-reduce:transition-none");
    expect(styles.imagePreviewLargePanning).toContain("transition-none");
    expect(styles.imagePreviewLargePanning).toContain("object-contain");
    expect(dialogSource).toContain("translate3d(");
  });
});
