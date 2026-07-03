import { Link2 } from "lucide-react";

import { VNativeButton } from "../components/vui";
import styles from "./TeamsRoute.styles";

type TeamSourceCollectionStorageActionsLang = "zh" | "en";

export type TeamSourceCollectionStorageAction = {
  target: string;
  label: string;
};

type TeamSourceCollectionStorageActionsPanelProps = {
  lang: TeamSourceCollectionStorageActionsLang;
  runDirectory: string;
  primaryAction: TeamSourceCollectionStorageAction;
  detailActions: TeamSourceCollectionStorageAction[];
  pending: boolean;
  openedPath: string;
  errorMessage: string;
  onOpenTarget: (target: string) => void;
};

export function TeamSourceCollectionStorageActionsPanel({
  lang,
  runDirectory,
  primaryAction,
  detailActions,
  pending,
  openedPath,
  errorMessage,
  onOpenTarget,
}: TeamSourceCollectionStorageActionsPanelProps) {
  const isZh = lang === "zh";

  return (
    <section className={styles.workflowSourceCollectionStorageActions} aria-label={isZh ? "搜集证据落盘位置" : "Source collection evidence storage"}>
      <div>
        <strong>{isZh ? "本轮产物" : "Run artifacts"}</strong>
      </div>
      <div className={styles.workflowSourceCollectionStorageButtons}>
        <VNativeButton type="button" disabled={pending} onClick={() => onOpenTarget(primaryAction.target)}>
          <Link2 size={12} />
          {primaryAction.label}
        </VNativeButton>
      </div>
      <details className={styles.workflowSourceCollectionStorageDetails}>
        <summary>{isZh ? "更多证据文件" : "More evidence files"}</summary>
        <div className={styles.workflowSourceCollectionStorageButtons}>
          {detailActions.map((action) => (
            <VNativeButton key={action.target} type="button" disabled={pending} onClick={() => onOpenTarget(action.target)}>
              <Link2 size={12} />
              {action.label}
            </VNativeButton>
          ))}
        </div>
        <small title={runDirectory}>{runDirectory}</small>
      </details>
      {openedPath ? (
        <small>
          {isZh ? "已打开" : "Opened"} {openedPath}
        </small>
      ) : null}
      {errorMessage ? <small className={styles.workflowSourceCollectionStorageError}>{errorMessage}</small> : null}
    </section>
  );
}
