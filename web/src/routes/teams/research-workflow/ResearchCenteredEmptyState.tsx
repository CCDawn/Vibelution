import { VEmptyState } from "../../../components/vui";
import styles from "./ResearchCenteredEmptyState.styles";

export function ResearchCenteredEmptyState({
  title,
  hint,
}: {
  title: string;
  hint?: string;
}) {
  return (
    <div className={styles.centered}>
      <VEmptyState title={title} className={styles.empty}>
        {hint ? <p className={styles.hint}>{hint}</p> : null}
      </VEmptyState>
    </div>
  );
}
