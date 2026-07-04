import { TriangleAlert } from "lucide-react";

import styles from "./MemoryWarningStrip.styles";

type MemoryWarningStripProps = {
  label: string;
  warnings: string[];
};

export function MemoryWarningStrip({ label, warnings }: MemoryWarningStripProps) {
  if (warnings.length === 0) {
    return null;
  }

  return (
    <section className={styles.warningStrip} aria-label={label}>
      <TriangleAlert size={16} />
      <strong>{label}</strong>
      <span>{warnings.join("；")}</span>
    </section>
  );
}
