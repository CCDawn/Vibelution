import type { ReactNode } from "react";
import { VEmptyState } from "../../../components/vui";
import styles from "./ResearchCenteredEmptyState.styles";

export function ResearchCenteredEmptyState({
  title,
  hint,
  actions,
}: {
  title: string;
  hint?: string;
  actions?: ReactNode;
}) {
  return (
    <div className={styles.centered}>
      <VEmptyState title={title} className={styles.empty}>
        {hint ? <p className={styles.hint}>{hint}</p> : null}
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </VEmptyState>
    </div>
  );
}
