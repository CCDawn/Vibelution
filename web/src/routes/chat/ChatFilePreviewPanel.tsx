import type { FileContent } from "../../api/types";
import { LazyFilePreview } from "../../components/preview/LazyFilePreview";
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
    return <div className={styles.emptySurface}>{errorMessage}</div>;
  }

  if (file) {
    return (
      <LazyFilePreview
        file={file}
        changed={changed}
        sourceLabel={sourceLabel}
        fallback={<div className={styles.emptySurface}>{loadingLabel}</div>}
      />
    );
  }

  return <div className={styles.emptySurface}>{loadingLabel}</div>;
}
