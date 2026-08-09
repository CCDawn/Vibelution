import styles from "./NodeHandoffSection.styles";

export function NodeHandoffSection(props: {
  pending: boolean;
  blockedReason: string;
}) {
  if (!props.pending && !props.blockedReason) return null;
  return (
    <section className={styles.root} data-vui="node-handoff-section">
      <h4 className={styles.title}>交接</h4>
      <dl className={styles.details}>
        <dt className={styles.label}>状态</dt>
        <dd className={styles.value}>{props.pending ? "等待人工" : "已处理"}</dd>
        {props.blockedReason ? <><dt className={styles.label}>阻塞</dt><dd className={styles.valueBreak}>{props.blockedReason}</dd></> : null}
      </dl>
    </section>
  );
}
