import { Download, X } from "lucide-react";
import React from "react";

import { VButton } from "../vui";
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

export function ConversationImagePreviewDialog({
  image,
  lang,
  onClose,
}: ConversationImagePreviewDialogProps) {
  const downloadLabel = lang === "zh" ? "下载图片" : "Download image";
  const closeLabel = lang === "zh" ? "关闭预览" : "Close preview";

  return (
    <div
      className={styles.imagePreviewOverlay}
      role="dialog"
      aria-modal="true"
      aria-label={image.alt}
      onClick={onClose}
    >
      <div className={styles.imagePreviewDialog} onClick={(event) => event.stopPropagation()}>
        <div className={styles.imagePreviewToolbar}>
          <span title={image.alt}>{image.alt}</span>
          <div className={styles.imagePreviewActions}>
            <a
              className={styles.imageDownloadButton}
              href={image.downloadUrl}
              download={image.downloadName}
              title={downloadLabel}
              aria-label={downloadLabel}
            >
              <Download size={15} />
            </a>
            <VButton
              type="button"
              className={styles.imagePreviewCloseButton}
              onClick={onClose}
              title={closeLabel}
              aria-label={closeLabel}
            >
              <X size={16} />
            </VButton>
          </div>
        </div>
        <img className={styles.imagePreviewLarge} src={image.src} alt={image.alt} />
      </div>
    </div>
  );
}
