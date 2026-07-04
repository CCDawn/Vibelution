import { Download } from "lucide-react";
import React from "react";

import type { ImageArtifactMessage } from "./conversationMessagePredicates";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import { VButton } from "../vui";
import styles from "./ConversationView.styles";

type ConversationImageArtifactViewProps = {
  artifact: ImageArtifactMessage;
  lang: "zh" | "en";
  onPreviewImage: (image: ConversationImagePreviewRequest) => void;
};

export function ConversationImageArtifactView({
  artifact,
  lang,
  onPreviewImage,
}: ConversationImageArtifactViewProps) {
  const downloadLabel = lang === "zh" ? "下载图片" : "Download image";
  const previewLabel = lang === "zh" ? "预览图片" : "Preview image";
  const imageAlt = artifact.prompt || (lang === "zh" ? "生成图片" : "Generated image");
  const metaItems = [artifact.size, artifact.quality, artifact.model].filter(Boolean);
  return (
    <figure className={styles.imageArtifact}>
      <VButton
        type="button"
        className={`${styles.imageArtifactFrame} ${styles.imagePreviewButton}`}
        onClick={() =>
          onPreviewImage({
            src: artifact.imageUrl,
            alt: imageAlt,
            downloadUrl: artifact.downloadUrl,
            downloadName: artifact.artifactId || true,
          })
        }
        aria-label={previewLabel}
        title={previewLabel}
      >
        <img className={styles.imagePreview} src={artifact.imageUrl} alt={imageAlt} loading="lazy" />
      </VButton>
      <figcaption className={styles.imageArtifactFooter}>
        <span className={styles.imageArtifactMeta}>
          {artifact.prompt ? <span className={styles.imageArtifactPrompt}>{artifact.prompt}</span> : null}
          {metaItems.length ? <span>{metaItems.join(" · ")}</span> : null}
        </span>
        <a
          className={styles.imageDownloadButton}
          href={artifact.downloadUrl}
          download={artifact.artifactId || true}
          title={downloadLabel}
          aria-label={downloadLabel}
        >
          <Download size={15} />
        </a>
      </figcaption>
    </figure>
  );
}
