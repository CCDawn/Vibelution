import type { FileContent } from "../../api/types";
import { LazyFilePreview } from "../../components/preview/LazyFilePreview";
import { VStateSurface } from "../../components/vui";
import styles from "./ChatFilePreviewPanel.styles";

type ChatFilePreviewPanelProps = {
  changed: boolean;
  errorMessage: string;
  file: FileContent | null | undefined;
  loadingLabel: string;
  sourceLabel: string;
};

export function ChatFilePreviewPanel({
  changed,
  errorMessage,
  file,
  loadingLabel,
  sourceLabel,
}: ChatFilePreviewPanelProps) {
  if (errorMessage) {
    return (
      <VStateSurface className={styles.emptySurface} tone="error" title={errorMessage} role="alert" />
    );
  }

  if (file) {
    return (
      <LazyFilePreview
        file={file}
        changed={changed}
        sourceLabel={sourceLabel}
        fallback={
          <VStateSurface
            className={styles.emptySurface}
            tone="loading"
            title={loadingLabel}
            skeletonLines={2}
            role="status"
            aria-live="polite"
          />
        }
      />
    );
  }

  return (
    <VStateSurface
      className={styles.emptySurface}
      tone="empty"
      title={loadingLabel}
      role="status"
      aria-live="polite"
    />
  );
}
