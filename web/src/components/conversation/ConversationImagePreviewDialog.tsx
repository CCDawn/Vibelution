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
  const downloadBaseLabel = lang === "zh" ? "下载图片" : "Download image";
  const downloadLabel = `${downloadBaseLabel}${lang === "zh" ? "：" : ": "}${image.alt}`;
  const closeLabel = lang === "zh" ? "关闭预览" : "Close preview";
  const titleId = "conversation-image-preview-title";
  const descriptionId = "conversation-image-preview-description";
  const description = lang === "zh"
    ? `正在预览图片：${image.alt}`
    : `Previewing image: ${image.alt}`;
  const handleOverlayKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  };

  return (
    <div
      className={styles.imagePreviewOverlay}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      tabIndex={-1}
      onClick={onClose}
      onKeyDown={handleOverlayKeyDown}
    >
      <div className={styles.imagePreviewDialog} onClick={(event) => event.stopPropagation()}>
        <div className={styles.imagePreviewToolbar}>
          <span id={titleId} className={styles.imagePreviewTitle} title={image.alt}>
            {image.alt}
          </span>
          <span id={descriptionId} className="sr-only">
            {description}
          </span>
          <div className={styles.imagePreviewActions}>
            <a
              className={styles.imageDownloadButton}
              href={image.downloadUrl}
              download={image.downloadName}
              title={downloadLabel}
              aria-label={downloadLabel}
            >
              <Download size={15} aria-hidden="true" />
            </a>
            <VButton
              type="button"
              className={styles.imagePreviewCloseButton}
              onClick={onClose}
              title={closeLabel}
              aria-label={closeLabel}
              autoFocus
            >
              <X size={16} aria-hidden="true" />
            </VButton>
          </div>
        </div>
        <img className={styles.imagePreviewLarge} src={image.src} alt={image.alt} aria-describedby={descriptionId} />
      </div>
    </div>
  );
}
