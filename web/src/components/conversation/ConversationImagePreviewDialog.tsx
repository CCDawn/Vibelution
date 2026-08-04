import { Download } from "lucide-react";

import { VDialog } from "../vui";
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
  const description = lang === "zh"
    ? `正在预览图片：${image.alt}`
    : `Previewing image: ${image.alt}`;

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
      )}
    >
      <img
        className={styles.imagePreviewLarge}
        src={image.src}
        alt={image.alt}
      />
    </VDialog>
  );
}
