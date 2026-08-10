import { VEmptyState } from "../../../components/vui";
import styles from "./ResearchCenteredEmptyState.styles";

export function ResearchCenteredEmptyState({ title }: { title: string }) {
  return (
    <div className={styles.centered}>
      <VEmptyState title={title} className={styles.empty} />
    </div>
  );
}
