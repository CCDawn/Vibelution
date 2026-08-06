import { TriangleAlert } from "lucide-react";

import { VStatusChip, VSurface } from "../components/vui";
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
    <VSurface
      as="section"
      tone="row"
      elevation="flat"
      padding="compact"
      className={styles.warningStrip}
      ariaLabel={label}
    >
      <VStatusChip tone="warning" className={styles.warningChip}>
        <TriangleAlert size={12} aria-hidden="true" />
        {label}
      </VStatusChip>
      <span className={styles.warningBody}>{warnings.join("；")}</span>
    </VSurface>
  );
}
