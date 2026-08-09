import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import styles from "./NodeArtifactSection.styles";

export function NodeArtifactSection({ artifacts }: { artifacts: ResearchWorkflowNodeDetail["artifacts"] }) {
  const entries = Object.entries(artifacts ?? {});
  if (!entries.length) return null;
  return (
    <section data-vui="node-artifacts">
      <h4 className={styles.title}>产物</h4>
      <ul className={styles.list}>
        {entries.map(([key, value]) => (
          <li key={key} className={styles.item} title={typeof value === "string" ? value : JSON.stringify(value)}>
            <span className={styles.key}>{key}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
