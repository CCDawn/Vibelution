import { existsSync } from "node:fs";

import { describe, expect, it } from "vitest";

import dialogSource from "./ConversationImagePreviewDialog.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
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
});
